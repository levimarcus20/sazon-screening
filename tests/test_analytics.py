"""Conversation analytics: metric definitions, the real-data adapter and the demo sample."""

from datetime import datetime, timedelta, timezone

from app.analytics import ScreeningRecord, demo_records, record_from_conversation, summarize
from app.models import Candidate, Message

NOW = datetime(2026, 10, 23, 18, 0, tzinfo=timezone.utc)
QUIET = timedelta(hours=24)


def rec(outcome="qualified", stage="scheduling", minutes=5.0, hours_ago=48, **kw) -> ScreeningRecord:
    started = NOW - timedelta(hours=hours_ago)
    end = started + timedelta(minutes=minutes)
    return ScreeningRecord(started_at=started, last_activity_at=end,
                           ended_at=None if outcome == "in_progress" else end,
                           outcome=outcome, stage=stage, **kw)


def test_rates_count_concluded_conversations_only():
    records = [
        rec("qualified", booked=True), rec("qualified"), rec("disqualified", "license"),
        rec("in_progress", "experience"),                    # quiet for 2 days: abandoned
        rec("in_progress", "zone", hours_ago=1),             # replied an hour ago: still active
    ]
    s = summarize(records, NOW, QUIET, days=30)
    assert (s["started"], s["concluded"], s["active"], s["finished"], s["abandoned"]) == (5, 4, 1, 3, 1)
    assert s["completion_rate"] == 3 / 4 and s["drop_rate"] == 1 / 4
    assert s["qualified_rate"] == 2 / 4 and s["booked_rate"] == 1 / 2


def test_drop_off_stage_and_funnel():
    records = [rec("in_progress", "full_name"), rec("in_progress", "full_name"), rec("in_progress", "experience"),
               rec("disqualified", "license"), rec("qualified")]
    s = summarize(records, NOW, QUIET, days=30)
    funnel = {f["stage"]: f for f in s["funnel"]}
    assert s["top_dropoff"]["stage"] == "full_name"
    assert funnel["full_name"]["reached"] == 5 and funnel["full_name"]["dropped"] == 2
    assert funnel["license"]["reached"] == 3 and funnel["license"]["disqualified"] == 1
    assert funnel["experience"]["drop_rate"] == 1 / 2      # 2 got there (one abandoned, one qualified)
    assert funnel["scheduling"]["reached"] == 1


def test_duration_uses_finished_conversations():
    records = [rec(minutes=m) for m in (2, 4, 6, 100)] + [rec("in_progress", "zone", minutes=300)]
    d = summarize(records, NOW, QUIET, days=30)["duration"]
    assert d["count"] == 4 and d["median"] == 5 and d["avg"] == 28 and d["p90"] == 100


def test_period_filter():
    records = [rec(hours_ago=24 * 3), rec(hours_ago=24 * 20)]
    assert summarize(records, NOW, QUIET, days=7)["started"] == 1
    assert summarize(records, NOW, QUIET, days=30)["started"] == 2


def test_record_from_real_conversation():
    t0 = NOW - timedelta(days=2)
    c = Candidate(created_at=t0, status="disqualified", closed=True, language="en",
                  last_candidate_message_at=t0 + timedelta(minutes=2))
    c.data.country = "ES"

    def agent(minute, **plan):
        return Message(candidate_id=c.id, role="agent", content="...", created_at=t0 + timedelta(minutes=minute),
                       meta={"plan": plan} if plan else {})

    messages = [agent(0), agent(1, action="ask", field="license"),
                agent(2, action="disqualify"), agent(9, action="post_close")]
    r = record_from_conversation(c, messages)
    assert (r.outcome, r.stage, r.country, r.language) == ("disqualified", "license", "ES", "en")
    assert r.ended_at == t0 + timedelta(minutes=2)   # the close, not a later post-close reply


def test_open_real_conversation_has_no_end():
    c = Candidate(created_at=NOW - timedelta(hours=3))
    msg = Message(candidate_id=c.id, role="agent", content="...", meta={"plan": {"action": "ask", "field": "experience_platforms"}})
    r = record_from_conversation(c, [msg])
    assert r.ended_at is None and r.outcome == "in_progress" and r.stage == "experience"


def test_demo_sample_is_reproducible_and_plausible():
    a, b = demo_records(NOW), demo_records(NOW)
    assert a == b and 900 < len(a) < 2000
    s = summarize(a, NOW, QUIET, days=30)
    assert 0.6 < s["completion_rate"] < 0.9
    assert s["top_dropoff"]["stage"] == "full_name"     # most people who leave never answer the first question
    assert 2 < s["duration"]["median"] < 10
