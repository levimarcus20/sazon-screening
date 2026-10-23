"""Loads the client configuration (service areas, job facts, platforms) and matches
free-text places to service-area cities."""

import difflib
import json
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .settings import settings


def normalize(text: str) -> str:
    """Lowercase, strip accents and punctuation noise: 'Málaga ' -> 'malaga'."""
    text = unicodedata.normalize("NFKD", text.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.replace(".", " ").replace(",", " ").split())


@dataclass(frozen=True)
class City:
    id: str
    name: str
    country: str
    timezone: str
    locations: list[str]
    aliases: list[str]
    nearby: list[str]


@dataclass
class LocationMatch:
    status: str                     # "match" | "ambiguous" | "no_match"
    city: City | None = None
    candidates: list[City] = field(default_factory=list)


@dataclass
class ClientConfig:
    raw: dict
    cities: list[City]
    # normalized place name -> ids of the cities it can refer to
    _index: dict[str, set[str]]

    @property
    def client_name(self) -> str:
        return self.raw["client_name"]

    @property
    def agent_name(self) -> str:
        return self.raw["agent_name"]

    @property
    def job_facts(self) -> list[str]:
        return self.raw["job_facts"]

    @property
    def interview(self) -> dict:
        return self.raw["interview"]

    def city_by_id(self, city_id: str) -> City | None:
        return next((c for c in self.cities if c.id == city_id), None)

    def cities_in(self, country: str) -> list[str]:
        return [c.name for c in self.cities if c.country == country]

    def match_location(self, place: str, country: str | None = None) -> LocationMatch:
        """Map a place name ('Barna', 'Zapopan', 'Polanco') to a service-area city.

        Exact lookup on names, aliases, nearby areas and restaurant neighbourhoods,
        then a fuzzy fallback for typos. `country` (ES/MX) breaks ties such as
        Guadalajara, which exists in both countries.
        """
        key = normalize(place)
        if not key:
            return LocationMatch("no_match")
        ids = self._index.get(key)
        if not ids:
            close = difflib.get_close_matches(key, self._index.keys(), n=1, cutoff=0.85)
            ids = self._index[close[0]] if close else set()
        matches = [c for c in self.cities if c.id in ids]
        if country in ("ES", "MX"):
            matches = [c for c in matches if c.country == country]
        if len(matches) == 1:
            return LocationMatch("match", city=matches[0])
        if len(matches) > 1:
            return LocationMatch("ambiguous", candidates=matches)
        return LocationMatch("no_match")

    def normalize_platform(self, name: str) -> str:
        key = normalize(name)
        for canonical, aliases in self.raw["known_platforms"].items():
            if key == normalize(canonical) or key in (normalize(a) for a in aliases):
                return canonical
        return name.strip().title()


def _build_index(cities: list[City]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = {}
    for city in cities:
        for name in [city.name, *city.aliases, *city.nearby, *city.locations]:
            index.setdefault(normalize(name), set()).add(city.id)
    return index


def load_client_config(path: Path) -> ClientConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cities = [City(**c) for c in raw["cities"]]
    return ClientConfig(raw=raw, cities=cities, _index=_build_index(cities))


@lru_cache
def get_client_config() -> ClientConfig:
    return load_client_config(settings.client_config_path)
