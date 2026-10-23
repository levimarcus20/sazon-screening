"""Mock recruiter calendar: generates interview slots per city and formats them.

In production this would read recruiter availability from a calendar/ATS. Here
each city has fixed daily times on business days; booked slots are excluded.
"""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .client_config import City

DAYS = {
    "es": ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MONTHS = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}


def available_slots(
    city: City,
    times: list[str],
    booked: set[datetime],
    exclude: set[datetime],
    count: int,
    now: datetime,
) -> list[datetime]:
    """Next `count` free slots, spread across different business days.

    Starts tomorrow (local time) so the recruiter always has notice, and takes one
    slot per day, rotating through the daily times, so the candidate gets real choice.
    """
    tz = ZoneInfo(city.timezone)
    day = now.astimezone(tz).date() + timedelta(days=1)
    slots: list[datetime] = []
    rotation = 0
    for _ in range(60):  # look at most ~2 months ahead
        if day.weekday() < 5:
            for i in range(len(times)):
                hh, mm = map(int, times[(rotation + i) % len(times)].split(":"))
                slot = datetime.combine(day, time(hh, mm), tzinfo=tz)
                if slot not in booked and slot not in exclude:
                    slots.append(slot)
                    rotation += 1
                    break
            if len(slots) == count:
                break
        day += timedelta(days=1)
    return slots


def format_slot(slot: datetime, language: str) -> str:
    """'martes 28 oct, 10:00' / 'Tuesday 28 Oct, 10:00' (local time of the slot)."""
    day = DAYS[language][slot.weekday()]
    month = MONTHS[language][slot.month - 1]
    return f"{day} {slot.day} {month}, {slot:%H:%M}"
