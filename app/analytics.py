"""Conversation analytics: completion rate, drop-off stage and duration across screenings.

Metrics are computed from one flat record per screening, built either from the real
conversations in the database or from a simulated sample (demo data). Demo records
only exist in memory for the analytics view: they are never stored as candidates.
"""

import random
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import mean, median

from .models import STAGE_ORDER, Candidate, Message

STAGES = STAGE_ORDER + ["scheduling"]          # funnel order, last stage = picking an interview time
OUTCOMES = ["qualified", "disqualified", "withdrawn", "needs_review"]
CLOSING_ACTIONS = {"confirm_booking", "scheduling_pending", "disqualify", "withdrawn", "delete_data", "needs_review"}
SCHEDULING_ACTIONS = {"offer_slots", "slot_taken", "reoffer_slots", "confirm_booking", "scheduling_pending"}
FIELD_STAGE = {"experience_platforms": "experience"}


@dataclass
class ScreeningRecord:
    started_at: datetime            # Sofía's first message (the application)
    last_activity_at: datetime      # the candidate's last message
    ended_at: datetime | None       # when the screening reached an outcome; None if still open
    outcome: str                    # one of OUTCOMES, or "in_progress"
    stage: str                      # last stage reached: where it ended or where the candidate stopped
    country: str | None = None
    language: str = "es"
    voice: bool = False             # switched to a voice call at some point
    booked: bool = False            # qualified and picked an interview slot


# --------------------------------------------------------------------------- sources

def record_from_conversation(c: Candidate, messages: list[Message]) -> ScreeningRecord:
    """One record from a real conversation, read from what the engine logged on each turn."""
    stage, ended_at = "full_name", None
    for m in messages:
        plan = m.meta.get("plan") or {}
        action = plan.get("action")
        if action == "ask" and plan.get("field"):
            stage = FIELD_STAGE.get(plan["field"], plan["field"])
        elif action in SCHEDULING_ACTIONS:
            stage = "scheduling"
        if action in CLOSING_ACTIONS:
            ended_at = m.created_at   # the latest close counts (a screening can be reopened once)
    return ScreeningRecord(
        started_at=c.created_at,
        last_activity_at=c.last_candidate_message_at or c.created_at,
        ended_at=ended_at if c.closed else None,
        outcome=c.status if c.closed else "in_progress",
        stage=stage,
        country=c.data.country,
        language=c.language,
        voice=any(m.meta.get("channel") == "voice" for m in messages),
        booked=c.interview_at is not None,
    )


# Simulated behaviour per stage: chance of going silent there, and of failing a knockout.
DEMO_ABANDON = {"full_name": .07, "license": .02, "vehicle": .015, "location": .03, "zone": .025,
                "availability": .02, "schedule": .015, "experience": .045, "start_date": .02, "scheduling": .06}
DEMO_DISQUALIFY = {"license": .09, "location": .07}
DEMO_SECONDS_PER_STAGE = 22     # median time a candidate takes to read and answer one question


def demo_records(now: datetime, days: int = 90, seed: int = 7) -> list[ScreeningRecord]:
    """A realistic, reproducible sample of screenings over the last `days` days."""
    rng = random.Random(seed)
    records = []
    for day in range(days):
        weekday = (now - timedelta(days=day)).weekday()
        for _ in range(rng.randint(12, 20) + (6 if weekday == 0 else 0) - (5 if weekday >= 5 else 0)):
            started = now - timedelta(days=day, seconds=rng.uniform(0, 86_400))
            records.append(_simulate(rng, started, now))
    return sorted(records, key=lambda r: r.started_at)


def _simulate(rng: random.Random, started: datetime, now: datetime) -> ScreeningRecord:
    voice = rng.random() < .12
    elapsed = 0.0
    outcome, booked = "in_progress", False
    for stage in STAGES:
        elapsed += rng.lognormvariate(0, .6) * DEMO_SECONDS_PER_STAGE * (1.4 if voice else 1)
        if rng.random() < .015:                     # stepped away mid-chat and came back later
            elapsed += rng.uniform(5, 90) * 60
        if rng.random() < DEMO_ABANDON[stage]:
            break                                   # went silent at this question
        if rng.random() < DEMO_DISQUALIFY.get(stage, 0):
            outcome = "disqualified"
        elif stage in ("full_name", "license", "location") and rng.random() < .01:
            outcome = "needs_review"
        elif rng.random() < .004:
            outcome = "withdrawn"
        elif stage == "scheduling":
            outcome, booked = "qualified", rng.random() < .87
        if outcome != "in_progress":
            break
    last = min(started + timedelta(seconds=elapsed), now)
    return ScreeningRecord(
        started_at=started, last_activity_at=last, ended_at=last if outcome != "in_progress" else None,
        outcome=outcome, stage=stage, country="ES" if rng.random() < .6 else "MX",
        language="en" if rng.random() < .12 else "es", voice=voice, booked=booked,
    )


# --------------------------------------------------------------------------- metrics

def state(r: ScreeningRecord, now: datetime, inactive_after: timedelta) -> str:
    """The record's outcome, or 'abandoned' / 'active' for screenings that never finished."""
    if r.ended_at is not None:
        return r.outcome
    return "abandoned" if now - r.last_activity_at > inactive_after else "active"


def _minutes(r: ScreeningRecord) -> float:
    return (r.ended_at - r.started_at).total_seconds() / 60


def _durations(records: list[ScreeningRecord]) -> dict:
    values = sorted(_minutes(r) for r in records)
    if not values:
        return {"count": 0, "avg": None, "median": None, "p90": None}
    return {"count": len(values), "avg": mean(values), "median": median(values),
            "p90": values[min(len(values) - 1, int(len(values) * .9))]}


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def summarize(records: list[ScreeningRecord], now: datetime, inactive_after: timedelta, days: int) -> dict:
    """Every metric on the analytics page for one period.

    Rates use concluded screenings only (finished + abandoned): a conversation whose
    last reply is more recent than `inactive_after` may still finish, so counting it
    as a drop-off would understate the completion rate.
    """
    since = now - timedelta(days=days)
    pairs = [(r, state(r, now, inactive_after)) for r in records if r.started_at >= since]
    concluded = [(r, s) for r, s in pairs if s != "active"]
    finished = [r for r, s in pairs if s in OUTCOMES]
    counts = Counter(s for _, s in pairs)

    funnel = []
    for i, stage in enumerate(STAGES):
        here = [s for r, s in concluded if r.stage == stage]
        reached = sum(1 for r, _ in concluded if STAGES.index(r.stage) >= i)
        dropped = here.count("abandoned")
        funnel.append({
            "stage": stage, "reached": reached, "reached_rate": _rate(reached, len(concluded)),
            "dropped": dropped, "drop_rate": _rate(dropped, reached), "disqualified": here.count("disqualified"),
        })
    top = max(funnel, key=lambda f: f["dropped"]) if counts["abandoned"] else None

    qualified = [r for r in finished if r.outcome == "qualified"]
    booked = sum(1 for r in qualified if r.booked)
    outcomes = [
        ("qualified_booked", booked),
        ("qualified_manual", len(qualified) - booked),
        ("disqualified", counts["disqualified"]),
        ("needs_review", counts["needs_review"]),
        ("withdrawn", counts["withdrawn"]),
        ("abandoned", counts["abandoned"]),
    ]

    def segment(name: str, keep) -> dict:
        part = [(r, s) for r, s in concluded if keep(r)]
        done = [r for r, s in part if s in OUTCOMES]
        return {"name": name, "concluded": len(part), "completion": _rate(len(done), len(part)),
                "median": _durations(done)["median"]}

    by_day = Counter(r.started_at.date() for r, _ in pairs)
    finished_by_day = Counter(r.started_at.date() for r in finished)
    daily = []
    for d in range(days - 1, -1, -1):
        day = (now - timedelta(days=d)).date()
        daily.append({"date": day, "started": by_day[day], "finished": finished_by_day[day]})

    return {
        "days": days,
        "started": len(pairs),
        "concluded": len(concluded),
        "active": counts["active"],
        "finished": len(finished),
        "abandoned": counts["abandoned"],
        "completion_rate": _rate(len(finished), len(concluded)),
        "drop_rate": _rate(counts["abandoned"], len(concluded)),
        "qualified_rate": _rate(len(qualified), len(concluded)),
        "booked_rate": _rate(booked, len(qualified)),
        "duration": _durations(finished),
        "duration_by_outcome": [(o, _durations([r for r in finished if r.outcome == o])) for o in OUTCOMES],
        "funnel": funnel,
        "top_dropoff": top,
        "outcomes": [(name, n, _rate(n, len(concluded))) for name, n in outcomes],
        "segments": [
            segment("Spain", lambda r: r.country == "ES"),
            segment("Mexico", lambda r: r.country == "MX"),
            segment("Spanish", lambda r: r.language == "es"),
            segment("English", lambda r: r.language == "en"),
            segment("Chat only", lambda r: not r.voice),
            segment("Used voice", lambda r: r.voice),
        ],
        "daily": daily,
        "daily_max": max((d["started"] for d in daily), default=0),
    }
