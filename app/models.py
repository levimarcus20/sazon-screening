"""Domain models: what we store about a candidate, and what the LLM returns."""

from datetime import date, datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

Language = Literal["es", "en"]


class Note(BaseModel):
    """A system-generated note for recruiters (a flag, a disqualification reason).

    Stored as a code + parameters rather than a finished sentence, so the dashboard
    can render it in any UI language (see i18n.NOTES).
    """

    code: str
    params: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _from_plain_text(cls, value):
        # Records saved before notes were structured hold plain English strings.
        return {"code": "text", "params": {"text": value}} if isinstance(value, str) else value

    def text(self, lang: str = "en") -> str:
        from .i18n import render_note
        return render_note(self, lang)

CandidateStatus = Literal[
    "in_progress",   # screening ongoing
    "qualified",     # passed every knockout, all data collected
    "disqualified",  # failed a knockout (no license, outside service area)
    "withdrawn",     # candidate said they're no longer interested
    "needs_review",  # agent couldn't resolve something; a human should look
]

RecruiterStatus = Literal["new", "contacted", "interviewed", "hired", "rejected"]

# Screening stages, in the order the agent asks them (knockouts first).
Stage = Literal[
    "full_name", "license", "vehicle", "location", "zone",
    "availability", "schedule", "experience", "start_date",
    "scheduling", "done",
]
STAGE_ORDER: list[str] = [
    "full_name", "license", "vehicle", "location", "zone",
    "availability", "schedule", "experience", "start_date",
]
KNOCKOUT_STAGES = {"license", "location"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScreeningData(BaseModel):
    """The structured screening output: every field the client asked us to collect."""

    full_name: str | None = None
    license_status: Literal["yes", "no", "in_progress"] | None = None
    vehicle_type: Literal["car", "motorcycle", "both", "bicycle", "other"] | None = None
    city: str | None = None          # canonical service-area city name
    city_id: str | None = None       # id in config/client.json
    country: Literal["ES", "MX"] | None = None
    zone: str | None = None          # neighbourhood / area, free text
    availability: Literal["full_time", "part_time", "weekends"] | None = None
    preferred_schedule: Literal["morning", "afternoon", "evening", "flexible"] | None = None
    experience_years: float | None = None
    experience_platforms: list[str] = Field(default_factory=list)
    start_date: date | None = None


class SummaryContent(BaseModel):
    headline: str = Field(description="One line, max ~12 words, e.g. 'Qualified, 3y Glovo experience, full-time in Madrid'")
    summary: str = Field(description="2-3 sentences a recruiter can read in 10 seconds")
    highlights: list[str] = Field(description="Positive points, short bullet phrases")
    concerns: list[str] = Field(description="Risks, gaps or things to verify, short bullet phrases; empty if none")
    recommended_action: str = Field(description="One concrete next step for the recruiter")


class RecruiterSummary(BaseModel):
    """Post-conversation summary for the recruiter (LLM structured output).

    Written in English (the canonical version) plus a Spanish translation in the
    same call, so the dashboard's language switch is instant and free.
    """

    en: SummaryContent = Field(description="The summary in English")
    es: SummaryContent = Field(description="A faithful Spanish translation of the English summary")

    @model_validator(mode="before")
    @classmethod
    def _from_english_only(cls, value):
        # Summaries saved before this change were a single English summary.
        if isinstance(value, dict) and "headline" in value:
            return {"en": value, "es": value}
        return value

    def in_lang(self, lang: str) -> SummaryContent:
        return self.es if lang == "es" else self.en


class Candidate(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    last_candidate_message_at: datetime | None = None

    status: CandidateStatus = "in_progress"
    stage: Stage = "full_name"
    closed: bool = False             # True once the agent has sent its closing message
    language: Language = "es"
    data: ScreeningData = Field(default_factory=ScreeningData)

    # Conversation bookkeeping used by the state machine
    attempts: dict[str, int] = Field(default_factory=dict)   # failed tries per stage
    skipped_stages: list[str] = Field(default_factory=list)  # gave up asking (non-knockout)
    flags: list[Note] = Field(default_factory=list)          # notes for the recruiter
    disqualification_reason: Note | None = None
    abusive_count: int = 0
    pending_place: str | None = None  # ambiguous place waiting for the country (e.g. Guadalajara)

    # Interview scheduling
    offered_slots: list[datetime] = Field(default_factory=list)
    slot_offer_rounds: int = 0
    interview_status: Literal["not_applicable", "pending", "booked"] = "not_applicable"
    interview_at: datetime | None = None

    summary: RecruiterSummary | None = None

    # Recruiter-side tracking
    recruiter_status: RecruiterStatus = "new"
    recruiter_notes: str = ""

    @property
    def first_name(self) -> str | None:
        return self.data.full_name.split()[0] if self.data.full_name else None


class Message(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    candidate_id: str
    role: Literal["agent", "candidate"]
    content: str
    created_at: datetime = Field(default_factory=utcnow)
    meta: dict = Field(default_factory=dict)  # extraction result, plan, errors (for audit)


# ---------------------------------------------------------------------------
# LLM extraction output. Every value is a string in a prescribed format; Python
# validates and converts it. Keeping the schema flat and string-typed makes the
# structured output simple and puts every rule in code we can test.
# ---------------------------------------------------------------------------

ExtractableField = Literal[
    "full_name", "license_status", "vehicle_type", "city", "country", "zone",
    "availability", "preferred_schedule", "experience_years", "experience_platforms",
    "start_date", "slot_choice",
]

Intent = Literal[
    "answer",         # answering the current question (or volunteering data)
    "question",       # asking something about the job/process
    "smalltalk",      # greetings, thanks, filler
    "wants_to_stop",  # explicitly no longer interested / wants to stop
    "delete_data",    # asks for their data to be deleted
    "off_topic",      # unrelated content, or tries to manipulate the agent
    "abusive",        # insults / inappropriate content
    "unclear",        # can't tell what they mean
]


class FieldUpdate(BaseModel):
    field: ExtractableField
    value: str
    evidence: str = Field(description="The exact words from the candidate that support this value")


class Extraction(BaseModel):
    language: Language = Field(description="Language of the candidate's latest message (dominant language if mixed)")
    intent: Intent
    candidate_question: str = Field(description="The candidate's question, if intent is 'question'; otherwise empty string")
    updates: list[FieldUpdate]
    ambiguity: str = Field(description="What was unclear or could not be extracted, empty string if nothing")


class Translations(BaseModel):
    """LLM output for transcript translation: one item per input message, same order."""

    items: list[str]
