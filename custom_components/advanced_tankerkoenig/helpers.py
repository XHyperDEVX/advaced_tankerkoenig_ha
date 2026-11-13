"""Pure validation, naming and price helpers; no Home Assistant side effects."""
from __future__ import annotations

import math
import re
import unicodedata

UUID_RE = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.IGNORECASE)


def parse_stations(value: str) -> list[str]:
    """Accept canonical UUIDs, not links, with a hard limit of ten."""
    stations = [item.lower() for item in re.split(r"[,;\s]+", value.strip()) if item]
    if not 1 <= len(stations) <= 10 or len(set(stations)) != len(stations):
        raise ValueError("invalid_stations")
    if any(not UUID_RE.fullmatch(item) for item in stations):
        raise ValueError("invalid_stations")
    return stations


def place_slug(place: str) -> str:
    text = str(place).lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_") or "tankstelle"


def allocate_prefix(station: str, details: dict, identities: dict[str, str]) -> str:
    """Never renumber or recycle an identity, including after station removal."""
    if station not in identities:
        base = place_slug(details.get("place") or "")
        number = 1
        while f"{base}{number}" in identities.values():
            number += 1
        identities[station] = f"{base}{number}"
    return identities[station]


def station_name(details: dict) -> str:
    name = str(details.get("name") or details.get("brand") or "Tankstelle").strip()
    street = str(details.get("street") or "").strip()
    house = str(details.get("houseNumber") or "").strip()
    address = street
    if house and not street.casefold().endswith(house.casefold()):
        address = f"{street} {house}".strip()
    if address and address.casefold() not in name.casefold():
        name = f"{name} – {address}"
    place = str(details.get("place") or "").strip()
    if place and place.casefold() not in name.casefold():
        name = f"{name}, {place}"
    return name[:255]


def valid_price(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def apply_prices(state: dict, item: dict) -> None:
    """Apply a validated station response, keeping closed stations' last prices."""
    state["price_status"] = item["status"]
    if item["status"] == "closed":
        return
    fuels = ("diesel", "e10", "e5")
    if item["status"] == "no prices":
        state["unavailable"] = list(fuels)
        state["prices"] = {}
        return
    state["unavailable"] = [fuel for fuel in fuels if not valid_price(item.get(fuel))]
    state["prices"] = {fuel: float(item[fuel]) for fuel in fuels if valid_price(item.get(fuel))}
