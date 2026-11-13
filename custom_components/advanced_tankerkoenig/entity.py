"""Shared identity, device naming and clock handling for every entity type."""
from __future__ import annotations

from datetime import timedelta

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, NAME
from .coordinator import utcnow
from .helpers import station_name


class AdvancedEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, station, key, name, platform="sensor", suffix=None):
        super().__init__(coordinator)
        self.station = station
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{station or 'overview'}_{key}"
        prefix = coordinator.identities[station] if station else "uebersicht"
        # Only a default: the entity registry always preserves user customisations.
        self.entity_id = f"{platform}.{DOMAIN}_{prefix}_{suffix or key}"

    @property
    def station_data(self):
        return self.coordinator.data["stations"].get(self.station, {})

    @property
    def details(self):
        return self.station_data.get("details") or {}

    @property
    def device_info(self):
        if self.station is None:
            return {"identifiers": {(DOMAIN, "overview")}, "name": f"{NAME} Übersicht", "manufacturer": NAME}
        return {
            "identifiers": {(DOMAIN, self.station)},
            "name": station_name(self.details),
            "manufacturer": self.details.get("brand") or "Tankerkönig",
            "configuration_url": f"https://www.tankerkoenig.de/tankstelle/{self.station}",
            "via_device": (DOMAIN, "overview"),
        }


class ClockEntity(AdvancedEntity):
    """One local callback at the next boundary; never another API request."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._clock_cancel = None
        self._next_boundary = None
        self._calculate_clock()

    def _calculate_clock(self):
        raise NotImplementedError

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._reset_clock()

    async def async_will_remove_from_hass(self):
        if self._clock_cancel:
            self._clock_cancel()
            self._clock_cancel = None
        await super().async_will_remove_from_hass()

    @callback
    def _reset_clock(self):
        if self._clock_cancel:
            self._clock_cancel()
            self._clock_cancel = None
        self._calculate_clock()
        # Retry unknown/long-term schedules locally tomorrow, without API traffic.
        next_time = self._next_boundary or (utcnow() + timedelta(days=1))
        self._clock_cancel = async_track_point_in_utc_time(
            self.hass, self._clock_tick, next_time + timedelta(milliseconds=100)
        )

    @callback
    def _clock_tick(self, _now):
        self._reset_clock()
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self):
        self._reset_clock()
        super()._handle_coordinator_update()


def register_station_entities(coordinator, entry, async_add_entities, factory):
    """A failed initial detail call does not block all other stations.

    Entities for a station appear only once its real place/name are known.
    """
    added = set()

    @callback
    def add_ready_stations():
        entities = []
        for station in coordinator.stations:
            if station in added or not coordinator.data["stations"][station]["details"]:
                continue
            added.add(station)
            entities.extend(factory(station))
        if entities:
            async_add_entities(entities)

    add_ready_stations()
    entry.async_on_unload(coordinator.async_add_listener(add_ready_stations))
