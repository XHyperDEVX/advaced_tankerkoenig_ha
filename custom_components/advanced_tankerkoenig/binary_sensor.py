"""Current station opening state and the API's whole-day marker."""
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass

from .const import DOMAIN
from .coordinator import utcnow
from .entity import AdvancedEntity, register_station_entities


class StationOpenBinarySensor(AdvancedEntity, BinarySensorEntity):
    """The only current opening-state entity for a station."""

    _attr_device_class = BinarySensorDeviceClass.OPENING

    def __init__(self, coordinator, station):
        # With has_entity_name, None presents the device/station name itself.
        super().__init__(coordinator, station, "open_now", None, "binary_sensor", "geoeffnet")

    @property
    def is_on(self):
        # wholeDay is part of the station metadata. The user explicitly wants
        # this current-state entity for 24/7 stations too.
        if self.details.get("wholeDay") is True:
            return True
        status = self.station_data.get("price_status")
        last_price = self.coordinator.data.get("last_price")
        if self.coordinator.data["prices_ok"] and last_price and (utcnow() - last_price).total_seconds() < 900:
            if status in ("open", "closed"):
                return status == "open"
        # A periodic details response may be days old, so it is never used as
        # a current state except immediately after it was obtained.
        fetched = self.station_data.get("last_detail")
        value = self.details.get("isOpen")
        if status is None and fetched and (utcnow() - fetched).total_seconds() <= 600:
            return value if isinstance(value, bool) else None
        return None

    @property
    def icon(self):
        return "mdi:store-clock" if self.is_on is None else ("mdi:store-check" if self.is_on else "mdi:store-off")

    @property
    def available(self):
        return super().available and self.is_on is not None

    @property
    def extra_state_attributes(self):
        return {
            "quelle": "Tankerkoenig",
            "preisstatus": self.station_data.get("price_status"),
            "ganztags_geoeffnet": self.details.get("wholeDay") is True,
        }


class WholeDayBinarySensor(AdvancedEntity, BinarySensorEntity):
    _attr_icon = "mdi:hours-24"

    def __init__(self, coordinator, station):
        super().__init__(coordinator, station, "whole_day", "24/7 geöffnet", "binary_sensor", "24_7")

    @property
    def is_on(self):
        value = self.details.get("wholeDay")
        return value if isinstance(value, bool) else None

    @property
    def extra_state_attributes(self):
        return {"quelle": "Tankerkoenig", "letzter_detailabruf": self.station_data.get("last_detail")}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]

    def factory(station):
        # Keep the opening-state entity for every station, including 24/7.
        return [WholeDayBinarySensor(coordinator, station), StationOpenBinarySensor(coordinator, station)]

    register_station_entities(coordinator, entry, async_add_entities, factory)
