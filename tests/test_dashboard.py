"""Recruiter-side logic: activity log and translate-button visibility."""

from app.i18n import conversation_languages
from app.models import Candidate, Message


def test_status_change_and_note_are_logged():
    c = Candidate()
    event = c.record_recruiter_action("contacted", "  Emailed him on Tuesday  ")
    assert c.recruiter_status == "contacted"
    assert (event.from_status, event.to_status, event.note) == ("new", "contacted", "Emailed him on Tuesday")
    assert c.activity == [event]


def test_note_only_keeps_status_and_is_appended():
    c = Candidate()
    c.record_recruiter_action("contacted", "first")
    event = c.record_recruiter_action("contacted", "second")
    assert event.to_status is None and event.note == "second"
    assert [e.note for e in c.activity] == ["first", "second"]  # nothing is overwritten


def test_nothing_changed_logs_nothing():
    c = Candidate()
    assert c.record_recruiter_action("new", "   ") is None and c.activity == []


def test_old_single_note_becomes_first_activity_entry():
    c = Candidate.model_validate({"recruiter_notes": "Old note", "recruiter_status": "contacted"})
    assert [e.note for e in c.activity] == ["Old note"]


def _msg(role, lang=None):
    meta = {"extraction": {"language": lang}} if lang else {}
    return Message(candidate_id="x", role=role, content="...", meta=meta)


def test_conversation_languages_ignore_agent_and_template_messages():
    messages = [_msg("agent"), _msg("candidate", "es"), _msg("agent"), _msg("candidate", "en")]
    assert conversation_languages(messages) == {"es", "en"}
    assert conversation_languages([_msg("agent")]) == set()  # nobody answered yet: nothing to translate
