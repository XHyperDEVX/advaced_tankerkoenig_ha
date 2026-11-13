"""Prices, local weekday schedules, location and overview entities."""
from __future__ import annotations

import math

from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass

from .const import ATTRIBUTION, DOMAIN, FUEL_LABELS, FUEL_TYPES, WEEKDAYS
from .coordinator import utcnow
from .entity import AdvancedEntity, ClockEntity, register_station_entities
from .helpers import station_name
from .opening_hours import forecast, weekday_summary


class StationLocationSensor(AdvancedEntity, SensorEntity):
    """Static location with HA-standard latitude/longitude attributes."""

    _attr_icon = "mdi:map-marker"

    def __init__(self, coordinator, station):
        super().__init__(coordinator, station, "location", "Standort", suffix="standort")

    @property
    def native_value(self):
        return str(self.details.get("place") or station_name(self.details))[:255]

    @property
    def extra_state_attributes(self):
        result = {}
        for source, target, limit in (("lat", "latitude", 90), ("lng", "longitude", 180)):
            value = self.details.get(source)
            if type(value) in (int, float) and math.isfinite(value) and -limit <= value <= limit:
                result[target] = value
        return result


class StationPriceSensor(AdvancedEntity, SensorEntity):
    _attr_native_unit_of_measurement = "€/L"
    _attr_suggested_display_precision = 3
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gas-station"

    def __init__(self, coordinator, station, fuel):
        super().__init__(coordinator, station, f"price_{fuel}", f"{FUEL_LABELS[fuel]} Preis", suffix=f"{fuel}_preis")
        self.fuel = fuel

    @property
    def available(self):
        return (super().available and self.coordinator.data["prices_ok"]
                and self.fuel not in self.station_data.get("unavailable", [])
                and self.fuel in self.station_data.get("prices", {}))

    @property
    def native_value(self):
        return self.station_data.get("prices", {}).get(self.fuel)

    @property
    def extra_state_attributes(self):
        return {"preisstatus": self.station_data.get("price_status"), "attribution": ATTRIBUTION}


class WeekdayOpeningHoursSensor(AdvancedEntity, SensorEntity):
    """One compact, human-readable regular opening-hours sensor per weekday."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, station, weekday, slug, name):
        super().__init__(
            coordinator, station, f"opening_hours_{slug}", f"{name} Öffnungszeiten",
            suffix=f"{slug}_oeffnungszeiten",
        )
        self.weekday = weekday

    @property
    def native_value(self):
        return weekday_summary(self.details, self.weekday)[0]

    @property
    def extra_state_attributes(self):
        _summary, periods, complete = weekday_summary(self.details, self.weekday)
        return {
            "zeitraeume": periods,
            "vollstaendig_interpretierbar": complete,
            "quelle": "Tankerkoenig",
            "hinweis": "Reguläre Öffnungszeiten; Sonderöffnungszeiten können abweichen.",
        }


class OverridesSensor(AdvancedEntity, SensorEntity):
    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator, station):
        super().__init__(coordinator, station, "overrides", "Besondere Öffnungszeiten", suffix="sonderoeffnungszeiten")

    @property
    def native_value(self):
        # Lists must be attributes: HA states are capped at 255 characters.
        return len(self.details.get("overrides") or [])

    @property
    def extra_state_attributes(self):
        return {"eintraege": self.details.get("overrides") or [], "quelle": "Tankerkoenig"}


class StationNextChangeSensor(ClockEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:store-clock"

    def __init__(self, coordinator, station):
        super().__init__(coordinator, station, "next_change", "Öffnet/Schließt", suffix="oeffnet_schliesst")

    def _calculate_clock(self):
        self._next_boundary, self._action, self._reason = forecast(self.details, utcnow())

    @property
    def native_value(self):
        return self._next_boundary

    @property
    def extra_state_attributes(self):
        return {
            "aktion": self._action,
            "hinweis": self._reason,
            "quelle": "Tankerkoenig",
            "berechnung": "Öffnungszeitenplan, einschließlich interpretierbarer Ausnahmen",
            "prognose": True,
            "zeitzone": "Europe/Berlin",
        }


class OverviewTimestampSensor(AdvancedEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-check-outline"

    def __init__(self, coordinator, key, name, suffix):
        super().__init__(coordinator, None, key, name, suffix=suffix)

    @property
    def native_value(self):
        return self.coordinator.data.get(self.key)


def cheapest(coordinator, fuel):
    if not coordinator.data["prices_ok"]:
        return None
    candidates = []
    for station, state in coordinator.data["stations"].items():
        price = state.get("prices", {}).get(fuel)
        if price is not None and fuel not in state.get("unavailable", []):
            candidates.append((price, station, state))
    return min(candidates, default=None, key=lambda item: (item[0], item[1]))


def winner_attributes(winner):
    if winner is None:
        return {}
    price, station, state = winner
    details = state.get("details") or {}
    return {
        "station_id": station, "name": station_name(details), "brand": details.get("brand"),
        "street": details.get("street"), "house_number": details.get("houseNumber"),
        "postcode": details.get("postCode"), "place": details.get("place"), "state": details.get("state"),
        "latitude": details.get("lat"), "longitude": details.get("lng"),
        "price_eur_per_litre": price, "preisstatus": state.get("price_status"), "attribution": ATTRIBUTION,
    }


class CheapestPriceSensor(AdvancedEntity, SensorEntity):
    _attr_native_unit_of_measurement = "€/L"
    _attr_suggested_display_precision = 3
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cash-check"

    def __init__(self, coordinator, fuel):
        super().__init__(coordinator, None, f"cheapest_{fuel}", f"Günstigster {FUEL_LABELS[fuel]} Preis", suffix=f"guenstigster_{fuel}_preis")
        self.fuel = fuel

    @property
    def available(self):
        return super().available and cheapest(self.coordinator, self.fuel) is not None

    @property
    def native_value(self):
        winner = cheapest(self.coordinator, self.fuel)
        return winner[0] if winner else None

    @property
    def extra_state_attributes(self):
        return winner_attributes(cheapest(self.coordinator, self.fuel))


class CheapestStationSensor(AdvancedEntity, SensorEntity):
    _attr_icon = "mdi:map-marker-star"

    def __init__(self, coordinator, fuel):
        super().__init__(coordinator, None, f"cheapest_station_{fuel}", f"Günstigste {FUEL_LABELS[fuel]} Tankstelle", suffix=f"guenstigste_{fuel}_tankstelle")
        self.fuel = fuel

    @property
    def available(self):
        return super().available and cheapest(self.coordinator, self.fuel) is not None

    @property
    def native_value(self):
        winner = cheapest(self.coordinator, self.fuel)
        return station_name(winner[2].get("details") or {}) if winner else None

    @property
    def extra_state_attributes(self):
        return winner_attributes(cheapest(self.coordinator, self.fuel))


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    overview = [
        OverviewTimestampSensor(coordinator, "last_price", "Letzter Preisabruf", "letzter_preisabruf"),
        OverviewTimestampSensor(coordinator, "last_detail", "Letzter Detailabruf", "letzter_detailabruf"),
    ]
    for fuel in FUEL_TYPES:
        overview.extend([CheapestPriceSensor(coordinator, fuel), CheapestStationSensor(coordinator, fuel)])
    async_add_entities(overview)

    def factory(station):
        details = coordinator.data["stations"][station]["details"]
        entities = [StationLocationSensor(coordinator, station)]
        entities.extend(StationPriceSensor(coordinator, station, fuel) for fuel in FUEL_TYPES)
        if details.get("wholeDay") is not True:
            entities.extend(
                WeekdayOpeningHoursSensor(coordinator, station, day, slug, name)
                for day, slug, name in WEEKDAYS
            )
            entities.append(StationNextChangeSensor(coordinator, station))
            if details.get("overrides"):
                entities.append(OverridesSensor(coordinator, station))
        return entities

    register_station_entities(coordinator, entry, async_add_entities, factory)
