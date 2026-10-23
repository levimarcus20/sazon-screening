"""Mock recruiter calendar: interview slots per city, and the calendar shown in the chat.

In production this would read recruiter availability from a calendar/ATS. Here
each city has fixed daily times on business days; booked slots are excluded.
"""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .client_config import City

DAYS = {
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
SHORT_DAYS = {
    "es": ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"],
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
}
MONTHS = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
PICKER_TEXT = {
    "es": {"title": "Elige día y hora", "today": "Hoy", "tomorrow": "Mañana", "confirm": "Confirmar",
           "none": "Ninguna me va bien", "empty": "No quedan huecos este día"},
    "en": {"title": "Pick a day and time", "today": "Today", "tomorrow": "Tomorrow", "confirm": "Confirm",
           "none": "None of these work", "empty": "No times left on this day"},
}


def business_days(now: datetime, tz: ZoneInfo, count: int) -> list[date]:
    """Today (if it's a weekday) and the following weekdays, `count` days in total."""
    day, days = now.astimezone(tz).date(), []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _at(day: date, hhmm: str, tz: ZoneInfo) -> datetime:
    hh, mm = map(int, hhmm.split(":"))
    return datetime.combine(day, time(hh, mm), tzinfo=tz)


def available_slots(city: City, times: list[str], booked: set[datetime], now: datetime,
                    days: int, min_notice: timedelta) -> list[datetime]:
    """Every free slot from today through the next business days, in order.

    A slot is free if nobody booked it and it's at least `min_notice` away, so the
    recruiter always has time to prepare (late in the day, today has nothing left).
    """
    tz = ZoneInfo(city.timezone)
    return [slot for day in business_days(now, tz, days) for hhmm in times
            if (slot := _at(day, hhmm, tz)) >= now + min_notice and slot not in booked]


def slot_calendar(city: City, times: list[str], offered: list[datetime], now: datetime, days: int,
                  language: str) -> dict:
    """The day-by-day calendar under the slot offer: every daily time, with the
    offered (free) ones selectable and the rest greyed out (taken or too soon)."""
    tz = ZoneInfo(city.timezone)
    text = PICKER_TEXT[language]
    today = now.astimezone(tz).date()
    free = set(offered)
    calendar_days = []
    for day in business_days(now, tz, days):
        name = (text["today"] if day == today else text["tomorrow"] if day == today + timedelta(days=1)
                else SHORT_DAYS[language][day.weekday()].capitalize())
        slots = []
        for hhmm in times:
            slot = _at(day, hhmm, tz)
            slots.append({"time": hhmm, "label": format_slot(slot, language).capitalize(),
                          "payload": f"slot:{slot.isoformat()}"} if slot in free else {"time": hhmm})
        calendar_days.append({"name": name, "date": f"{day.day} {MONTHS[language][day.month - 1]}", "slots": slots})
    return {**text, "days": calendar_days, "none_payload": "slot:none"}


def slot_key(slot: datetime) -> str:
    """Unambiguous local date + time ('2026-10-29 18:00'): how the extractor names a chosen slot."""
    return f"{slot:%Y-%m-%d %H:%M}"


def format_slot(slot: datetime, language: str) -> str:
    """'martes 28 oct, 10:00' / 'Tuesday 28 Oct, 10:00' (local time of the slot)."""
    day = DAYS[language][slot.weekday()]
    month = MONTHS[language][slot.month - 1]
    return f"{day} {slot.day} {month}, {slot:%H:%M}"
