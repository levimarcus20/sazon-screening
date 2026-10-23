"""FastAPI app: candidate chat (web, WhatsApp-style) + recruiter dashboard."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from pydantic import BaseModel

from .analytics import demo_records, record_from_conversation, summarize
from .client_config import get_client_config
from .engine import CallNotAvailable, CandidateNotFound, ScreeningEngine, TurnResult
from .i18n import (
    COOKIE_NAME, LANGUAGES, code_name, conversation_languages, get_language, i18n_context, translate,
)
from .llm import ClaudeLLM, LLMError
from .models import Candidate, RecruiterStatus, utcnow
from .scheduling import MONTHS, format_slot
from .settings import settings
from .storage import Storage

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

BASE_DIR = Path(__file__).resolve().parent
config = get_client_config()
storage = Storage(settings.database_path)
engine = ScreeningEngine(storage, ClaudeLLM(settings, config), config, settings)

app = FastAPI(title="Grupo Sazón · Candidate Screening")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates", context_processors=[i18n_context])


# ---------------------------------------------------------------- view helpers

def display_status(c: Candidate) -> str:
    """Status shown to recruiters: 'inactive' if an in-progress candidate went silent."""
    if c.status == "in_progress":
        last = c.last_candidate_message_at or c.created_at
        if utcnow() - last > timedelta(hours=settings.inactive_after_hours):
            return "inactive"
    return c.status


@pass_context
def fmt_dt(ctx, value: datetime | None) -> str:
    if not value:
        return "—"
    local = value.astimezone()
    return f"{local.day:02d} {MONTHS[ctx['lang']][local.month - 1]} {local.year}, {local:%H:%M}"


@pass_context
def fmt_day(ctx, value) -> str:
    return f"{value.day:02d} {MONTHS[ctx['lang']][value.month - 1]}" if value else "—"


LABELS = {
    "full_time": "Full-time", "part_time": "Part-time", "weekends": "Weekends",
    "morning": "Morning", "afternoon": "Afternoon", "evening": "Evening", "flexible": "Flexible",
    "car": "Car", "motorcycle": "Motorbike", "both": "Car + motorbike", "bicycle": "Bicycle", "other": "Other",
    "yes": "Yes", "no": "No", "in_progress": "In progress",
    "in_progress_status": "In progress", "qualified": "Qualified", "disqualified": "Disqualified",
    "withdrawn": "Withdrawn", "needs_review": "Needs review", "inactive": "Inactive",
}


@pass_context
def label(ctx, value) -> str:
    if value is None or value == "":
        return "—"
    return translate(LABELS.get(str(value), str(value)), ctx["lang"])


@pass_context
def status_label(ctx, value: str) -> str:
    return translate(LABELS["in_progress_status"], ctx["lang"]) if value == "in_progress" else label(ctx, value)


@pass_context
def t(ctx, text: str) -> str:
    return translate(text, ctx["lang"])


@pass_context
def slot(ctx, value: datetime) -> str:
    return format_slot(value, ctx["lang"])


@pass_context
def note(ctx, value) -> str:
    """Render a system Note (flag / disqualification reason) in the UI language."""
    return value.text(ctx["lang"]) if value else "—"


@pass_context
def stage_label(ctx, value: str) -> str:
    return code_name(value, ctx["lang"])


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def mins(value: float | None) -> str:
    """Minutes as '4.8 min' or '1 h 25 min'."""
    if value is None:
        return "—"
    if value < 60:
        return f"{value:.1f} min"
    hours, minutes = divmod(round(value), 60)
    return f"{hours} h {minutes} min"


templates.env.filters.update(dt=fmt_dt, day=fmt_day, label=label, status_label=status_label, slot=slot,
                             note=note, stage_label=stage_label, pct=pct, mins=mins)
templates.env.globals.update(display_status=display_status, config=config, t=t)


@app.get("/lang/{code}")
def set_language(request: Request, code: str):
    """EN/ES switch: remember the choice in a cookie and go back to the same page."""
    # Only redirect to a path on this site (never to an external URL from the Referer).
    back = urlparse(request.headers.get("referer", "")).path or "/dashboard"
    query = urlparse(request.headers.get("referer", "")).query
    response = RedirectResponse(back + (f"?{query}" if query else ""), status_code=303)
    if code in LANGUAGES:
        response.set_cookie(COOKIE_NAME, code, max_age=365 * 24 * 3600, samesite="lax")
    return response


# ------------------------------------------------------------- candidate side

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/apply")
def apply():
    """Simulates 'a candidate applied to the job ad' -> the agent opens the conversation."""
    candidate = engine.start_conversation()
    return RedirectResponse(f"/chat/{candidate.id}", status_code=303)


@app.get("/chat/{candidate_id}", response_class=HTMLResponse)
def chat_page(request: Request, candidate_id: str):
    candidate = storage.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(404, "Conversation not found")
    return templates.TemplateResponse(request, "chat.html", {
        "candidate": candidate, "messages": storage.get_messages(candidate_id),
    })


class IncomingMessage(BaseModel):
    text: str
    payload: str | None = None  # set when the candidate taps a quick-reply button
    channel: Literal["chat", "voice"] = "chat"  # "voice": text is a speech-to-text transcript


def candidate_snapshot(c: Candidate) -> dict:
    """What the demo side panel shows: live structured data + state."""
    return {
        "status": c.status, "stage": c.stage, "language": c.language, "closed": c.closed,
        "data": c.data.model_dump(mode="json"), "flags": [f.text("en") for f in c.flags], "attempts": c.attempts,
        "interview_at": c.interview_at.isoformat() if c.interview_at else None,
    }


templates.env.globals.update(candidate_snapshot=candidate_snapshot)


def turn_response(result: TurnResult) -> dict:
    return {
        "replies": [{"content": m.content, "created_at": m.created_at.isoformat(),
                     "quick_replies": m.meta.get("quick_replies", [])} for m in result.replies],
        "candidate": candidate_snapshot(result.candidate),
    }


@app.post("/api/chat/{candidate_id}/messages")
def post_message(candidate_id: str, body: IncomingMessage, background: BackgroundTasks):
    try:
        result = engine.handle_message(candidate_id, body.text, body.payload, body.channel)
    except CandidateNotFound:
        raise HTTPException(404, "Conversation not found")
    except Exception:
        log.exception("unexpected error handling message for %s", candidate_id)
        return JSONResponse(status_code=500, content={
            "error": "Something went wrong on our side. Please send your message again in a moment.",
        })
    if result.closed_now:
        background.add_task(engine.generate_summary, candidate_id, only_if_closed=True)
    return turn_response(result)


@app.post("/api/chat/{candidate_id}/call")
def start_call(candidate_id: str):
    """Voice mode: the browser does speech-to-text / text-to-speech; turns then go to /messages."""
    try:
        return turn_response(engine.start_call(candidate_id))
    except CandidateNotFound:
        raise HTTPException(404, "Conversation not found")
    except CallNotAvailable:
        raise HTTPException(409, "This screening has already finished.")


@app.get("/api/candidates/{candidate_id}")
def candidate_json(candidate_id: str):
    """Full structured record: screening data, state, summary and transcript."""
    candidate = storage.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    return {
        "candidate": candidate.model_dump(mode="json"),
        "transcript": [m.model_dump(mode="json") for m in storage.get_messages(candidate_id)],
    }


@app.get("/api/candidates")
def candidates_json():
    return [c.model_dump(mode="json") for c in storage.list_candidates()]


# ------------------------------------------------------------- recruiter side

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, status: str = "", country: str = "", city: str = "",
              availability: str = "", schedule: str = "", recruiter_status: str = "", q: str = ""):
    everyone = storage.list_candidates()
    counts: dict[str, int] = {}
    for c in everyone:
        counts[display_status(c)] = counts.get(display_status(c), 0) + 1

    def keep(c: Candidate) -> bool:
        d = c.data
        return all([
            not status or display_status(c) == status,
            not country or d.country == country,
            not city or d.city_id == city,
            not availability or d.availability == availability,
            not schedule or d.preferred_schedule == schedule,
            not recruiter_status or c.recruiter_status == recruiter_status,
            not q or q.lower() in (d.full_name or "").lower(),
        ])

    # Most actionable first: qualified, then needs review, then the rest by recency.
    priority = {"qualified": 0, "needs_review": 1, "in_progress": 2, "inactive": 3}
    rows = sorted(filter(keep, everyone), key=lambda c: (priority.get(display_status(c), 4), -c.updated_at.timestamp()))
    return templates.TemplateResponse(request, "dashboard.html", {
        "rows": rows, "counts": counts, "total": len(everyone),
        "filters": {"status": status, "country": country, "city": city, "availability": availability,
                    "schedule": schedule, "recruiter_status": recruiter_status, "q": q},
    })


OUTCOME_NAMES = {
    "qualified_booked": "Qualified, interview booked", "qualified_manual": "Qualified, recruiter schedules",
    "disqualified": "Disqualified", "needs_review": "Needs review", "withdrawn": "Withdrawn",
    "abandoned": "Stopped replying",
}


@app.get("/analytics", response_class=HTMLResponse)
def analytics(request: Request, source: str = "demo", days: int = 30, country: str = ""):
    """Conversation metrics, aggregated only: completion rate, drop-off stage, duration."""
    days = days if days in (7, 30, 90) else 30
    now = utcnow().replace(minute=0, second=0, microsecond=0)  # demo sample stays stable within the hour
    candidates = storage.list_candidates()
    if source == "live":
        records = [record_from_conversation(c, storage.get_messages(c.id)) for c in candidates]
    else:
        source, records = "demo", demo_records(now)
    if country in ("ES", "MX"):
        records = [r for r in records if r.country == country]
    stats = summarize(records, now, timedelta(hours=settings.inactive_after_hours), days)
    return templates.TemplateResponse(request, "analytics.html", {
        "s": stats, "live_total": len(candidates), "outcome_names": OUTCOME_NAMES,
        "inactive_hours": f"{settings.inactive_after_hours:g}",
        "filters": {"source": source, "days": days, "country": country},
    })


@app.get("/dashboard/candidates/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, candidate_id: str, translated: int = 0, translate_error: int = 0):
    candidate = storage.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(404, "Candidate not found")
    messages = storage.get_messages(candidate_id)
    # Offer translation only if the candidate wrote in a language other than the UI's.
    can_translate = bool(conversation_languages(messages) - {get_language(request)})
    return templates.TemplateResponse(request, "candidate.html", {
        "c": candidate, "messages": messages, "can_translate": can_translate,
        "show_translation": bool(translated) and can_translate, "translate_error": bool(translate_error),
    })


@app.post("/dashboard/candidates/{candidate_id}/translate")
def translate_conversation(request: Request, candidate_id: str):
    """Machine-translate the transcript into the recruiter's UI language (cached per message)."""
    if storage.get_candidate(candidate_id) is None:
        raise HTTPException(404, "Candidate not found")
    try:
        engine.translate_transcript(candidate_id, get_language(request))
    except LLMError as e:
        log.warning("transcript translation failed for %s: %s", candidate_id, e)
        return RedirectResponse(f"/dashboard/candidates/{candidate_id}?translate_error=1#conversation", status_code=303)
    return RedirectResponse(f"/dashboard/candidates/{candidate_id}?translated=1#conversation", status_code=303)


@app.post("/dashboard/candidates/{candidate_id}/update")
def update_candidate(candidate_id: str, recruiter_status: RecruiterStatus = Form(...), note: str = Form("")):
    """Log a recruiter action (pipeline change and/or note) in the candidate's activity history."""
    with engine.candidate_lock(candidate_id):  # don't overwrite a chat turn happening right now
        candidate = storage.get_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(404, "Candidate not found")
        event = candidate.record_recruiter_action(recruiter_status, note)
        if event:
            storage.save_candidate(candidate)
    result = "saved=1" if event else "nothing=1"
    return RedirectResponse(f"/dashboard/candidates/{candidate_id}?{result}#activity", status_code=303)


@app.post("/dashboard/candidates/{candidate_id}/summary")
def regenerate_summary(candidate_id: str):
    if engine.generate_summary(candidate_id) is None:
        raise HTTPException(404, "Candidate not found")
    return RedirectResponse(f"/dashboard/candidates/{candidate_id}", status_code=303)


@app.post("/dashboard/candidates/{candidate_id}/delete")
def delete_candidate(candidate_id: str):
    storage.delete_candidate(candidate_id)
    return RedirectResponse("/dashboard", status_code=303)
