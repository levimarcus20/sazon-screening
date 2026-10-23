"""Deterministic validation of LLM-extracted values.

The LLM proposes values (as strings); these functions decide whether they are
valid and convert them to typed data. Every business rule lives here, in plain
Python that is unit-tested, never in a prompt.
"""

import re
from dataclasses import dataclass, field as dc_field
from datetime import date, timedelta
from typing import Any

from .client_config import ClientConfig, normalize
from .models import Extraction, FieldUpdate, Note

START_DATE_MAX_DAYS = 365      # beyond this we treat the date as a mistake
START_DATE_FLAG_DAYS = 60      # beyond this we accept but flag it for the recruiter


@dataclass
class FieldResult:
    field: str                       # data field (or "location" / "slot_choice")
    ok: bool
    value: Any = None                # typed value when ok
    error: str | None = None         # machine-readable error code
    detail: str = ""                 # human-readable explanation, used in the turn plan
    raw: str = ""                    # what the candidate actually said
    extra: dict = dc_field(default_factory=dict)


def _fail(name: str, error: str, detail: str, raw: str = "") -> FieldResult:
    return FieldResult(field=name, ok=False, error=error, detail=detail, raw=raw)


def validate_full_name(value: str) -> FieldResult:
    name = " ".join(value.split())
    if len(name) < 2 or len(name) > 80:
        return _fail("full_name", "invalid_name", f"'{value}' doesn't look like a name", value)
    if any(ch.isdigit() for ch in name) or not re.search(r"[^\W\d_]", name):
        return _fail("full_name", "invalid_name", f"'{value}' doesn't look like a name", value)
    if name.islower() or name.isupper():
        name = name.title()
    return FieldResult("full_name", True, name, raw=value)


def validate_choice(name: str, value: str, allowed: set[str]) -> FieldResult:
    v = value.strip().lower()
    if v in allowed:
        return FieldResult(name, True, v, raw=value)
    return _fail(name, "invalid_value", f"'{value}' is not one of {sorted(allowed)}", value)


def validate_experience_years(value: str) -> FieldResult:
    try:
        years = float(value.strip().replace(",", "."))
    except ValueError:
        return _fail("experience_years", "not_a_number", f"couldn't read a number of years from '{value}'", value)
    if years < 0 or years > 50:
        return _fail("experience_years", "out_of_range", f"{years} years of experience isn't plausible", value)
    return FieldResult("experience_years", True, round(years, 1), raw=value)


def validate_platforms(value: str, config: ClientConfig) -> FieldResult:
    parts = [p.strip() for p in re.split(r"[,;/]| y | and ", value) if p.strip()]
    if any(p.lower() in {"none", "ninguna", "ninguno", "no"} for p in parts):
        return FieldResult("experience_platforms", True, [], raw=value)
    platforms = list(dict.fromkeys(config.normalize_platform(p) for p in parts))
    return FieldResult("experience_platforms", True, platforms, raw=value)


def validate_start_date(value: str, today: date) -> FieldResult:
    try:
        start = date.fromisoformat(value.strip())
    except ValueError:
        return _fail("start_date", "invalid_date", f"couldn't read a date from '{value}'", value)
    if start < today:
        return _fail("start_date", "past_date", f"{start.isoformat()} is in the past", value)
    if start > today + timedelta(days=START_DATE_MAX_DAYS):
        return _fail("start_date", "too_far", f"{start.isoformat()} is more than a year away", value)
    result = FieldResult("start_date", True, start, raw=value)
    if start > today + timedelta(days=START_DATE_FLAG_DAYS):
        result.extra["flag"] = Note(code="late_start", params={"date": start.isoformat()})
    return result


def validate_location(city: str, country: str, zone: str, config: ClientConfig) -> FieldResult:
    """Combine the city/country/zone updates into one service-area decision."""
    raw = ", ".join(v for v in (zone, city, country) if v)

    def out_of_area(detail: str) -> FieldResult:
        result = _fail("location", "out_of_area", detail, raw)
        result.extra = {"place": city or zone, "country": country.upper() or None}
        return result

    if country.upper() == "OTHER":
        return out_of_area(f"{city or zone} is outside Spain/Mexico")

    country_code = country.upper() if country.upper() in ("ES", "MX") else None
    match = config.match_location(city, country_code) if city else None
    if (match is None or match.status == "no_match") and zone:
        match = config.match_location(zone, country_code)  # e.g. only "Zapopan" given

    if match is None:
        return _fail("location", "missing_city", "a neighbourhood was given but no city", raw)
    if match.status == "ambiguous":
        options = " / ".join(f"{c.name} ({'Spain' if c.country == 'ES' else 'Mexico'})" for c in match.candidates)
        result = _fail("location", "ambiguous_city", f"'{city or zone}' could be {options}; ask which country", raw)
        result.extra = {"place": city or zone}
        return result
    if match.status == "no_match":
        return out_of_area(f"{city or zone} is not in a Grupo Sazón service area")

    c = match.city
    # "Chamberí" or "Zapopan" given as the city: keep the city match, and record
    # the neighbourhood/municipality they named as their zone.
    if city and not zone and normalize(city) not in {normalize(n) for n in (c.name, *c.aliases)}:
        zone = city
    return FieldResult(
        "location", True,
        {"city": c.name, "city_id": c.id, "country": c.country, "zone": zone or None},
        raw=raw,
    )


def validate_extraction(extraction: Extraction, config: ClientConfig, today: date,
                        pending_place: str | None = None, known_city_id: str | None = None) -> list[FieldResult]:
    """Validate every field update the LLM proposed in one message.

    `pending_place` is an earlier ambiguous place ("Guadalajara"): if the candidate
    now only gives a country ("in Spain"), the two are combined.
    `known_city_id` is the city we already have: a neighbourhood given afterwards is
    accepted as their zone even if it isn't in our config.
    """
    by_field: dict[str, FieldUpdate] = {}
    for update in extraction.updates:
        by_field[update.field] = update  # if repeated, the last mention wins

    results: list[FieldResult] = []
    for name, update in by_field.items():
        v = update.value
        if name == "full_name":
            results.append(validate_full_name(v))
        elif name == "license_status":
            results.append(validate_choice(name, v, {"yes", "no", "in_progress"}))
        elif name == "vehicle_type":
            results.append(validate_choice(name, v, {"car", "motorcycle", "both", "bicycle", "other"}))
        elif name == "availability":
            results.append(validate_choice(name, v, {"full_time", "part_time", "weekends"}))
        elif name == "preferred_schedule":
            results.append(validate_choice(name, v, {"morning", "afternoon", "evening", "flexible"}))
        elif name == "experience_years":
            results.append(validate_experience_years(v))
        elif name == "experience_platforms":
            results.append(validate_platforms(v, config))
        elif name == "start_date":
            results.append(validate_start_date(v, today))
        elif name == "slot_choice":
            results.append(FieldResult("slot_choice", True, v.strip().lower(), raw=v))

    if any(f in by_field for f in ("city", "country", "zone")):
        get = lambda f: by_field[f].value.strip() if f in by_field else ""
        city, country, zone = get("city"), get("country"), get("zone")
        if known_city_id and not country and (zone or city):
            # City already known; a new place without a country is a neighbourhood
            # unless it clearly names a different service-area city.
            match = config.match_location(city) if city else None
            if match and match.status == "match" and not zone:
                # Another service-area city (they moved), the same city restated, or a
                # neighbourhood we know (validate_location turns that into the zone).
                results.append(validate_location(city, "", "", config))
            else:
                results.append(FieldResult("zone", True, zone or city, raw=zone or city))
        elif city or zone:
            results.append(validate_location(city, country, zone, config))
        elif country and pending_place:
            results.append(validate_location(pending_place, country, "", config))
    return results
