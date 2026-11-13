"""Advanced Tankerkoenig: isolated from Home Assistant's tankerkoenig domain."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN, FUEL_TYPES, NAME, PLATFORMS, WEEKDAYS
from .coordinator import AdvancedTankerkoenigCoordinator

# Version 2.0 exposed a calendar platform. It is no longer forwarded, but it
# must still be explicitly unloaded once for in-place updates of existing HA
# entries; otherwise Home Assistant can retain its old platform component.
_LEGACY_PLATFORMS = ["calendar"]


def _prune_registry(hass, entry, coordinator):
    """Remove only obsolete entities owned by this integration's own domain."""
    allowed = set()

    def allow(platform, station, keys):
        allowed.update((platform, f"{DOMAIN}_{station}_{key}") for key in keys)

    allow("sensor", "overview", ["last_price", "last_detail"])
    allow("sensor", "overview", [f"cheapest_{fuel}" for fuel in FUEL_TYPES])
    allow("sensor", "overview", [f"cheapest_station_{fuel}" for fuel in FUEL_TYPES])
    for station in coordinator.stations:
        details = coordinator.data["stations"][station]["details"]
        allow("sensor", station, ["location"])
        allow("sensor", station, [f"price_{fuel}" for fuel in FUEL_TYPES])
        allow("binary_sensor", station, ["whole_day", "open_now"])
        # Keep conditionally created sensors on an unavailable cached station;
        # otherwise a temporary detail error could erase entities from HA.
        if details is None or details.get("wholeDay") is not True:
            allow("sensor", station, ["next_change"])
            allow("sensor", station, [f"opening_hours_{slug}" for _day, slug, _name in WEEKDAYS])
            if details is None or details.get("overrides"):
                allow("sensor", station, ["overrides"])
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.platform == DOMAIN and (entity.domain, entity.unique_id) not in allowed:
            registry.async_remove(entity.entity_id)
    devices = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(devices, entry.entry_id):
        station_ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
        if station_ids and not station_ids.intersection({"overview", *coordinator.stations}):
            devices.async_update_device(device.id, remove_config_entry_id=entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = AdvancedTankerkoenigCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    try:
        await coordinator.async_prepare()
        dr.async_get(hass).async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "overview")},
            name=f"{NAME} Übersicht",
            manufacturer=NAME,
            entry_type=dr.DeviceEntryType.SERVICE,
        )
        _prune_registry(hass, entry, coordinator)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Initial HTTP work begins only after platform listeners are registered.
        coordinator.start()
    except Exception:
        await coordinator.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise

    async def stop_at_shutdown(_event):
        await coordinator.async_stop()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_at_shutdown))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, [*PLATFORMS, *_LEGACY_PLATFORMS]):
        return False
    coordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_stop()
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await Store(hass, 1, f"{DOMAIN}_{entry.entry_id}").async_remove()
