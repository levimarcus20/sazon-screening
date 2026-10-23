"""State-machine tests with a scripted fake LLM (no API calls)."""

from datetime import datetime, timezone

import pytest

from app.client_config import get_client_config
from app.engine import ScreeningEngine
from app.llm import LLMError
from app.models import Extraction, FieldUpdate
from app.settings import Settings
from app.storage import Storage

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)  # a Friday


def ex(intent="answer", lang="es", question="", **fields) -> Extraction:
    return Extraction(
        language=lang, intent=intent, candidate_question=question, ambiguity="",
        updates=[FieldUpdate(field=k, value=str(v), evidence=str(v)) for k, v in fields.items()],
    )


class FakeLLM:
    """Returns pre-scripted extractions; replies echo the planned action."""

    def __init__(self):
        self.extractions: list[Extraction] = []
        self.fail_reply = False
        self.last_instructions = ""

    def extract(self, user_input, today):
        if not self.extractions:
            raise LLMError("no scripted extraction")
        return self.extractions.pop(0)

    def reply(self, history, instructions):
        self.last_instructions = instructions
        self.last_history = history
        if self.fail_reply:
            raise LLMError("down")
        return "REPLY: " + instructions.splitlines()[-1]

    def summarize(self, summary_input):
        raise LLMError("no summary in tests")

    def translate(self, texts, lang):
        self.translate_calls = getattr(self, "translate_calls", 0) + 1
        return [f"[{lang}] {t}" for t in texts]


@pytest.fixture
def setup(tmp_path):
    llm = FakeLLM()
    storage = Storage(tmp_path / "test.db")
    engine = ScreeningEngine(storage, llm, get_client_config(), Settings(), clock=lambda: NOW)
    return engine, llm, storage


def say(engine, llm, cid, extraction):
    llm.extractions.append(extraction)
    return engine.handle_message(cid, "message")


def test_happy_path_to_booked_interview(setup):
    engine, llm, storage = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García"))
    say(engine, llm, cid, ex(license_status="yes", vehicle_type="motorcycle"))
    say(engine, llm, cid, ex(city="Madrid", country="ES", zone="Chamberí"))
    say(engine, llm, cid, ex(availability="part_time", preferred_schedule="evening"))
    say(engine, llm, cid, ex(experience_years="2", experience_platforms="Glovo"))
    r = say(engine, llm, cid, ex(start_date="2026-11-02"))
    c = r.candidate
    assert c.status == "qualified" and c.stage == "scheduling" and len(c.offered_slots) == 3
    assert "Good news" in llm.last_instructions

    r = say(engine, llm, cid, ex(slot_choice="2"))
    c = r.candidate
    assert c.interview_status == "booked" and c.interview_at == c.offered_slots[1]
    assert c.closed and r.closed_now
    assert storage.booked_slots("madrid") == {c.interview_at}


def _reach_scheduling(engine, llm, cid):
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car",
                             city="Madrid", zone="Retiro", availability="weekends",
                             preferred_schedule="morning", experience_years="0"))
    return say(engine, llm, cid, ex(start_date="2026-11-02"))


def test_slot_offer_has_buttons_and_tap_books_without_llm(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    r = _reach_scheduling(engine, llm, cid)
    buttons = r.replies[0].meta["quick_replies"]
    assert [b["payload"] for b in buttons] == ["slot:1", "slot:2", "slot:3", "slot:none"]
    # No scripted extraction: if the engine called the LLM extractor this would fail over to "unclear".
    r = engine.handle_message(cid, buttons[2]["label"], payload="slot:3")
    assert r.candidate.interview_status == "booked" and r.candidate.interview_at == r.candidate.offered_slots[2]


def test_none_button_offers_new_slots(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    first = _reach_scheduling(engine, llm, cid).candidate.offered_slots
    r = engine.handle_message(cid, "Ninguna me va bien", payload="slot:none")
    assert set(r.candidate.offered_slots).isdisjoint(first)
    assert r.replies[0].meta["quick_replies"]


def test_stale_button_is_not_trusted(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    llm.extractions.append(ex(full_name="Ana García"))
    c = engine.handle_message(cid, "Ana García", payload="slot:1").candidate  # not scheduling yet
    assert c.data.full_name == "Ana García" and c.interview_status == "not_applicable"


def test_notes_render_in_both_languages(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Luis Pérez", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Toledo", country="ES")).candidate
    assert c.disqualification_reason.text("en") == "Outside service area (Toledo)"
    assert c.disqualification_reason.text("es") == "Fuera de la zona de servicio (Toledo)"
    assert c.flags[0].text("es") == "Vive en Toledo (fuera de la zona de servicio)"


def test_old_records_with_plain_text_still_load():
    from app.models import Candidate
    c = Candidate.model_validate({
        "flags": ["Some old flag"], "disqualification_reason": "No driving license",
        "summary": {"headline": "h", "summary": "s", "highlights": [], "concerns": [], "recommended_action": "a"},
    })
    assert c.flags[0].text("es") == "Some old flag" and c.summary.in_lang("es").headline == "h"


def test_fallback_summary_is_bilingual(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Luis Pérez"))
    say(engine, llm, cid, ex(license_status="no"))
    s = engine.generate_summary(cid)  # FakeLLM.summarize fails -> template
    assert "Disqualified" in s.en.headline and "Descartado" in s.es.headline


def test_transcript_translation_is_cached(setup):
    engine, llm, storage = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García"))
    engine.translate_transcript(cid, "en")
    engine.translate_transcript(cid, "en")
    assert llm.translate_calls == 1
    msgs = storage.get_messages(cid)
    assert all(m.meta["translations"]["en"] == f"[en] {m.content}" for m in msgs)


def test_no_license_disqualifies_and_invites_correction(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Luis Pérez"))
    r = say(engine, llm, cid, ex(license_status="no"))
    c = r.candidate
    assert c.status == "disqualified" and c.closed
    assert c.disqualification_reason.code == "no_license"
    assert r.replies[0].meta["plan"]["allow_correction"] is True
    assert "answered by mistake" in llm.last_instructions


def test_unsure_license_extraction_is_asked_again_not_disqualified(setup):
    """Regression: "de moto pero no de coche" was extracted as in_progress (with an ambiguity note) and disqualified."""
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Juan Bernal"))
    unsure = ex(license_status="in_progress", vehicle_type="motorcycle")
    unsure.ambiguity = "Has a motorcycle license but not a car license; in_progress is uncertain"
    c = say(engine, llm, cid, unsure).candidate
    assert c.status == "in_progress" and not c.closed and c.stage == "license"
    assert c.data.license_status is None and c.data.vehicle_type == "motorcycle"
    assert "car or a motorbike (either one is enough)" in llm.last_instructions


def _disqualify_for_license(engine, llm, cid):
    say(engine, llm, cid, ex(full_name="Pablo García"))
    return say(engine, llm, cid, ex(license_status="no")).candidate


def test_license_correction_after_close_reopens_once(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    assert _disqualify_for_license(engine, llm, cid).status == "disqualified"
    c = say(engine, llm, cid, ex(license_status="yes", vehicle_type="car")).candidate
    assert c.status == "in_progress" and not c.closed and c.stage == "location"
    assert c.disqualification_reason is None and c.knockout_corrections == 1
    assert any(f.code == "license_corrected" for f in c.flags)
    assert "application continues" in llm.last_instructions


def test_second_knockout_flip_goes_to_human_review(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    _disqualify_for_license(engine, llm, cid)
    say(engine, llm, cid, ex(license_status="yes"))               # correction 1: reopened
    r = say(engine, llm, cid, ex(license_status="no"))            # disqualified again...
    assert r.candidate.status == "disqualified"
    assert r.replies[0].meta["plan"]["allow_correction"] is False  # ...without the invitation this time
    c = say(engine, llm, cid, ex(license_status="yes")).candidate  # correction 2
    assert c.status == "needs_review" and c.closed
    assert any(f.code == "repeated_knockout_change" for f in c.flags)


def test_location_correction_after_close_reopens(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Luis Pérez", license_status="yes", vehicle_type="car"))
    assert say(engine, llm, cid, ex(city="Toledo", country="ES")).candidate.status == "disqualified"
    c = say(engine, llm, cid, ex(city="Madrid", zone="Retiro")).candidate
    assert c.status == "in_progress" and c.data.city == "Madrid" and c.stage == "availability"
    assert any(f.text() == "First said they live in Toledo, then corrected it to Madrid after being disqualified"
               for f in c.flags)


def test_correction_during_background_summary_is_not_overwritten(setup):
    """Regression: a slow summary used to save a stale 'disqualified' copy over a reopened screening."""
    engine, llm, storage = setup
    cid = engine.start_conversation().id
    _disqualify_for_license(engine, llm, cid)

    def slow_summary(summary_input):
        # While the summary model is "thinking", the candidate corrects their answer.
        llm.extractions.append(ex(license_status="yes"))
        engine.handle_message(cid, "sí tengo, me equivoqué")
        raise LLMError("use template")

    llm.summarize = slow_summary
    engine.generate_summary(cid, only_if_closed=True)
    c = storage.get_candidate(cid)
    assert c.status == "in_progress" and c.knockout_corrections == 1 and c.summary is None


def test_reopened_screening_discards_stale_summary(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    _disqualify_for_license(engine, llm, cid)
    say(engine, llm, cid, ex(license_status="yes"))  # reopened before the background summary ran
    engine.generate_summary(cid, only_if_closed=True)
    assert engine.storage.get_candidate(cid).summary is None


def test_out_of_area_disqualifies_and_flags_place(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Luis Pérez", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Toledo", country="ES")).candidate
    assert c.status == "disqualified"
    assert "Toledo" in c.disqualification_reason.text()
    assert "Madrid" in llm.last_instructions  # tells them where we do operate


def test_multiple_fields_in_one_message(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    c = say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car",
                                  city="Barcelona", zone="Gràcia", availability="full_time")).candidate
    assert c.stage == "schedule"


def test_single_first_name_asks_once_for_surname(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    c = say(engine, llm, cid, ex(full_name="Ana")).candidate
    assert c.stage == "full_name"
    c = say(engine, llm, cid, ex(intent="unclear")).candidate
    assert c.stage == "license"


def test_unclear_knockout_goes_to_human_review(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García"))
    for _ in range(2):
        c = say(engine, llm, cid, ex(intent="unclear")).candidate
        assert c.status == "in_progress"
    c = say(engine, llm, cid, ex(intent="unclear")).candidate
    assert c.status == "needs_review" and c.closed


def test_unclear_optional_field_is_skipped(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car", city="Sevilla", zone="Triana"))
    say(engine, llm, cid, ex(intent="unclear"))
    c = say(engine, llm, cid, ex(intent="unclear")).candidate
    assert "availability" in c.skipped_stages and c.stage == "schedule"


def test_question_does_not_count_as_failed_attempt(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    c = say(engine, llm, cid, ex(intent="question", question="¿Cuánto pagan?")).candidate
    assert c.attempts.get("full_name", 0) == 0
    assert "¿Cuánto pagan?" in llm.last_instructions


def test_invalid_value_is_reasked(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car", city="Madrid", zone="Retiro",
                             availability="weekends", preferred_schedule="morning", experience_years="0"))
    c = say(engine, llm, cid, ex(start_date="2026-01-01")).candidate
    assert c.stage == "start_date" and c.data.start_date is None
    assert "in the past" in llm.last_instructions


def test_ambiguous_city_resolved_by_country_only_answer(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana Torres", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Guadalajara")).candidate
    assert c.stage == "location" and c.pending_place == "Guadalajara"
    c = say(engine, llm, cid, ex(country="ES")).candidate
    assert c.data.city_id == "guadalajara_es" and c.stage == "availability" and c.pending_place is None


def test_zone_asked_in_multi_restaurant_city(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Madrid", country="ES")).candidate
    assert c.stage == "zone"
    # A neighbourhood that isn't in our config is still accepted once the city is known
    c = say(engine, llm, cid, ex(zone="Barrio del Pilar")).candidate
    assert c.data.zone == "Barrio del Pilar" and c.data.city == "Madrid" and c.stage == "availability"


def test_neighbourhood_given_as_city_becomes_zone(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Malasaña")).candidate
    assert c.data.city == "Madrid" and c.data.zone == "Malasaña" and c.stage == "availability"


def test_zone_skipped_in_single_restaurant_city(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car"))
    c = say(engine, llm, cid, ex(city="Murcia", country="ES")).candidate
    assert c.stage == "availability"


def test_unknown_zone_is_optional(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García", license_status="yes", vehicle_type="car", city="Madrid"))
    say(engine, llm, cid, ex(intent="unclear"))
    c = say(engine, llm, cid, ex(intent="unclear")).candidate
    assert "zone" in c.skipped_stages and c.stage == "availability"


def test_language_switch_is_followed(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    c = say(engine, llm, cid, ex(lang="en", full_name="John Smith")).candidate
    assert c.language == "en" and "Reply in English" in llm.last_instructions


def test_llm_outage_degrades_gracefully(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    llm.fail_reply = True
    r = engine.handle_message(cid, "hola")  # extraction also fails: nothing scripted
    assert r.replies[0].content.startswith("¿Me dices tu nombre completo")
    assert r.candidate.status == "in_progress"


def test_prompt_injection_cannot_qualify(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    c = say(engine, llm, cid, ex(intent="off_topic")).candidate
    assert c.status == "in_progress" and "off-topic" in llm.last_instructions


def test_post_close_change_of_other_field_is_only_flagged(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    _disqualify_for_license(engine, llm, cid)
    c = say(engine, llm, cid, ex(availability="full_time")).candidate
    assert c.status == "disqualified" and c.closed
    assert any("tried to change" in f.text() for f in c.flags)


# ------------------------------------------------------------------ voice


def voice(engine, llm, cid, extraction):
    llm.extractions.append(extraction)
    return engine.handle_message(cid, "transcript", channel="voice")


def test_voice_turn_is_marked_and_phrased_for_speech(setup):
    engine, llm, storage = setup
    cid = engine.start_conversation().id
    voice(engine, llm, cid, ex(full_name="Ana García"))
    assert "VOICE CALL" in llm.last_instructions
    candidate_msg, agent_msg = storage.get_messages(cid)[-2:]
    assert candidate_msg.meta["channel"] == agent_msg.meta["channel"] == "voice"
    say(engine, llm, cid, ex(license_status="yes"))  # back to typing: chat style again
    assert "VOICE CALL" not in llm.last_instructions
    assert "channel" not in storage.get_messages(cid)[-1].meta


def test_name_heard_on_a_call_is_flagged_for_spelling_once(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    voice(engine, llm, cid, ex(full_name="Ana"))
    c = voice(engine, llm, cid, ex(full_name="Ana García")).candidate
    assert [f.code for f in c.flags] == ["name_by_voice"]


def test_call_start_greets_and_repeats_the_pending_question(setup):
    engine, llm, storage = setup
    cid = engine.start_conversation().id
    say(engine, llm, cid, ex(full_name="Ana García"))
    r = engine.start_call(cid)
    assert r.replies[0].meta["call_event"] == "start" and r.replies[0].meta["channel"] == "voice"
    assert "switched from text chat to a voice call" in llm.last_instructions
    assert "driving license" in llm.last_instructions  # the question still pending
    # The opening + greeting are consecutive agent messages: merged into one assistant turn.
    roles = [m["role"] for m in llm.last_history]
    assert all(a != b for a, b in zip(roles, roles[1:])) and roles[-1] == "user"
    assert r.candidate.stage == "license" and len(storage.get_messages(cid)) == 4


def test_call_during_scheduling_reads_slots_out_instead_of_buttons(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    _reach_scheduling(engine, llm, cid)
    r = engine.start_call(cid)
    assert "reading them out" in llm.last_instructions and "tap" not in llm.last_instructions
    assert r.replies[0].meta["quick_replies"]  # buttons stay visible in the chat window


def test_call_fallback_greeting_when_llm_is_down(setup):
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    llm.fail_reply = True
    assert engine.start_call(cid).replies[0].content.startswith("Hola, soy Sofía.")


def test_no_call_after_screening_finished(setup):
    from app.engine import CallNotAvailable
    engine, llm, _ = setup
    cid = engine.start_conversation().id
    _disqualify_for_license(engine, llm, cid)
    with pytest.raises(CallNotAvailable):
        engine.start_call(cid)


def test_empty_message_is_ignored(setup):
    engine, _, _ = setup
    cid = engine.start_conversation().id
    assert engine.handle_message(cid, "   \x00 ").replies == []
