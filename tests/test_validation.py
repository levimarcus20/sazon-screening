from datetime import date

from app.client_config import get_client_config
from app.validation import (
    validate_experience_years, validate_full_name, validate_location, validate_platforms,
    validate_start_date,
)

config = get_client_config()
TODAY = date(2026, 10, 23)


def test_config_has_45_locations():
    assert sum(len(c.locations) for c in config.cities) == 45


def test_location_aliases_and_nearby_areas():
    assert validate_location("Barna", "", "", config).value["city"] == "Barcelona"
    assert validate_location("CDMX", "", "", config).value["city"] == "Ciudad de México"
    assert validate_location("Zapopan", "", "", config).value["city_id"] == "guadalajara_mx"
    assert validate_location("", "", "Polanco", config).value["city_id"] == "cdmx"


def test_location_typo_is_fuzzy_matched():
    assert validate_location("Barcelna", "", "", config).value["city"] == "Barcelona"


def test_guadalajara_is_ambiguous_without_country():
    r = validate_location("Guadalajara", "", "", config)
    assert not r.ok and r.error == "ambiguous_city"
    assert validate_location("Guadalajara", "MX", "", config).value["city_id"] == "guadalajara_mx"


def test_out_of_area():
    r = validate_location("Toledo", "ES", "", config)
    assert not r.ok and r.error == "out_of_area"
    assert r.extra == {"place": "Toledo", "country": "ES"}
    assert validate_location("Bogotá", "OTHER", "", config).error == "out_of_area"


def test_full_name():
    assert validate_full_name("maría lópez").value == "María López"
    assert not validate_full_name("1234").ok
    assert not validate_full_name("x").ok


def test_experience_years():
    assert validate_experience_years("2,5").value == 2.5
    assert not validate_experience_years("lots").ok
    assert not validate_experience_years("80").ok


def test_platforms_normalized():
    assert validate_platforms("glovo, ubereats", config).value == ["Glovo", "Uber Eats"]
    assert validate_platforms("none", config).value == []


def test_start_date_rules():
    assert validate_start_date("2026-11-02", TODAY).ok
    assert validate_start_date("2026-10-01", TODAY).error == "past_date"
    assert validate_start_date("2028-01-01", TODAY).error == "too_far"
    assert "flag" in validate_start_date("2027-02-01", TODAY).extra
    assert validate_start_date("next week", TODAY).error == "invalid_date"
