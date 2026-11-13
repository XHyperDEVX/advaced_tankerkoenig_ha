"""Shared price polling, independent detail timers, persisted station identities."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import math
import random

from homeassistant.components import persistent_notification
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import AdvancedTankerkoenigApi
from .const import (
    CONF_API_KEY, CONF_STATIONS, DETAIL_MAX_SECONDS, DETAIL_MIN_SECONDS,
    DETAIL_RETRY_SECONDS, DOMAIN, FUEL_TYPES, NAME, PRICE_MAX_SECONDS, PRICE_MIN_SECONDS,
)
from .helpers import allocate_prefix, apply_prices, station_name, valid_price

_LOGGER = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def parse_date(value):
    try:
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def valid_due(value):
    return type(value) in (int, float) and math.isfinite(value)


def new_state():
    return {"details": None, "prices": {}, "price_status": None, "unavailable": [],
            "last_detail": None, "next_detail_due": None}


class AdvancedTankerkoenigCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, _LOGGER, name=NAME, update_interval=None)
        self.entry = entry
        self.stations = list(entry.options.get(CONF_STATIONS, entry.data[CONF_STATIONS]))
        if not 1 <= len(self.stations) <= 10 or len(set(self.stations)) != len(self.stations):
            raise ValueError("Expected 1–10 unique station UUIDs")
        self.api = AdvancedTankerkoenigApi(async_get_clientsession(hass), entry.data[CONF_API_KEY])
        self.data = {"stations": {station: new_state() for station in self.stations},
                     "last_price": None, "last_detail": None, "prices_ok": False}
        self.identities = {}
        self._store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")
        self._price_handle = None
        self._detail_handles = {}
        self._tasks = set()
        self._stopped = False
        self._started = False
        self._next_price_due = None
        self._save_lock = asyncio.Lock()
        self._price_lock = asyncio.Lock()
        self._detail_semaphore = asyncio.Semaphore(2)
        self._active_notifications = {}

    async def async_prepare(self):
        """Restore cache only; never hold Home Assistant setup open for API I/O."""
        try:
            saved = await self._store.async_load() or {}
        except Exception:
            _LOGGER.warning("%s: Cache konnte nicht geladen werden", NAME)
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        self.identities = {
            key: value for key, value in saved.get("identities", {}).items()
            if isinstance(value, str) and value and all(c in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in value)
        } if isinstance(saved.get("identities"), dict) else {}
        stored_stations = saved.get("stations", {})
        if not isinstance(stored_stations, dict):
            stored_stations = {}
        for station, state in self.data["stations"].items():
            stored = stored_stations.get(station, {})
            if not isinstance(stored, dict):
                continue
            details = stored.get("details")
            if isinstance(details, dict) and details.get("id") == station:
                state["details"] = details
                allocate_prefix(station, details, self.identities)
                state["last_detail"] = parse_date(stored.get("last_detail"))
            due = stored.get("next_detail_due")
            if valid_due(due):
                state["next_detail_due"] = min(due, utcnow().timestamp() + DETAIL_MAX_SECONDS)
            prices = stored.get("prices", {})
            if isinstance(prices, dict):
                state["prices"] = {fuel: prices[fuel] for fuel in FUEL_TYPES if valid_price(prices.get(fuel))}
            unavailable = stored.get("unavailable")
            state["unavailable"] = [fuel for fuel in FUEL_TYPES if fuel in unavailable] if isinstance(unavailable, list) else []
            status = stored.get("price_status")
            state["price_status"] = status if status in ("open", "closed", "no prices") else None
        self.data["last_price"] = parse_date(saved.get("last_price"))
        detail_dates = [s["last_detail"] for s in self.data["stations"].values() if s["last_detail"]]
        self.data["last_detail"] = max(detail_dates, default=None)
        due = saved.get("next_price_due")
        if valid_due(due) and set(stored_stations) == set(self.stations):
            self._next_price_due = min(due, utcnow().timestamp() + PRICE_MAX_SECONDS)
            last = self.data["last_price"]
            self.data["prices_ok"] = bool(saved.get("prices_ok") and last and (utcnow() - last).total_seconds() < 900)
        for station in set(stored_stations) - set(self.stations):
            self._clear_notification(f"details_{station}")
            self._clear_notification(f"no_prices_{station}")

    def start(self):
        """Start the shared price timer and independent station detail timers.

        A missing or expired detail deadline is scheduled immediately, but after
        all platforms have registered their listeners. This keeps startup fast
        and lets a newly discovered station create correctly named entities.
        """
        self._started = True
        self._schedule_prices()
        for station in self.stations:
            # detail.php has no batch endpoint; each callback is deliberately
            # independent, while the semaphore prevents startup request bursts.
            self._schedule_detail(station)

    def _spawn(self, coroutine):
        task = self.hass.async_create_task(coroutine)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def async_stop(self):
        self._stopped = True
        if self._price_handle:
            self._price_handle.cancel()
        for handle in self._detail_handles.values():
            handle.cancel()
        self._detail_handles.clear()
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self._save()

    def _schedule_prices(self):
        if self._stopped or not self._started:
            return
        if self._price_handle:
            self._price_handle.cancel()
        delay = max(0, (self._next_price_due or 0) - utcnow().timestamp())
        self._price_handle = self.hass.loop.call_later(delay, lambda: self._spawn(self._refresh_prices()))

    def _schedule_detail(self, station):
        if self._stopped or not self._started:
            return
        old = self._detail_handles.pop(station, None)
        if old:
            old.cancel()
        delay = max(0, (self.data["stations"][station]["next_detail_due"] or 0) - utcnow().timestamp())
        self._detail_handles[station] = self.hass.loop.call_later(
            delay, lambda: self._spawn(self._refresh_details(station))
        )

    async def async_request_refresh(self):
        """HA update_entity must not create extra requests between batch polls."""
        if not self._next_price_due or self._next_price_due <= utcnow().timestamp():
            await self._refresh_prices()

    async def _refresh_prices(self):
        async with self._price_lock:
            if self._stopped:
                return
            if self._next_price_due and self._next_price_due > utcnow().timestamp():
                return
            try:
                payload = await self.api.request("prices", ids=",".join(self.stations))
                prices = payload.get("prices")
                if not isinstance(prices, dict):
                    raise UpdateFailed("Tankerkönig API: prices fehlt")
                # Validate the entire batch first: no partial updates on malformed data.
                for station in self.stations:
                    item = prices.get(station)
                    if not isinstance(item, dict) or item.get("status") not in ("open", "closed", "no prices"):
                        raise UpdateFailed(f"Tankerkönig API: ungültiger Preisstatus für {station}")
                for station in self.stations:
                    state = self.data["stations"][station]
                    apply_prices(state, prices[station])
                    if state["price_status"] == "no prices":
                        self._notify(f"no_prices_{station}", f"{station_name(state['details'] or {})} ({station}): no prices. Automatischer Neuversuch beim nächsten Preisabruf.")
                    else:
                        self._clear_notification(f"no_prices_{station}")
                self.data["last_price"] = utcnow()
                self.data["prices_ok"] = True
                self._clear_notification("prices_api")
            except UpdateFailed as err:
                self.data["prices_ok"] = False
                self._notify("prices_api", str(err))
            except Exception as err:
                self.data["prices_ok"] = False
                self._notify("prices_api", f"Interner Preisabruf-Fehler ({type(err).__name__})")
            finally:
                if not self._stopped:
                    self._next_price_due = utcnow().timestamp() + random.randint(PRICE_MIN_SECONDS, PRICE_MAX_SECONDS)
                    self.async_set_updated_data(self.data)
                    self._schedule_prices()
                    await self._save()

    async def _refresh_details(self, station):
        if self._stopped or station not in self.data["stations"]:
            return
        state = self.data["stations"][station]
        previous = state["details"]
        shape_changed = False
        try:
            async with self._detail_semaphore:
                if self._stopped:
                    return
                payload = await self.api.request("detail", id=station)
            if self._stopped:
                return
            details = payload.get("station")
            if not isinstance(details, dict) or str(details.get("id", "")).lower() != station:
                raise UpdateFailed("Tankerkönig API: ungültige Tankstellendetails")
            details = {**details, "id": station}
            state["details"] = details
            state["last_detail"] = utcnow()
            self.data["last_detail"] = max(
                filter(None, (self.data.get("last_detail"), state["last_detail"]))
            )
            allocate_prefix(station, details, self.identities)
            state["next_detail_due"] = utcnow().timestamp() + random.randint(DETAIL_MIN_SECONDS, DETAIL_MAX_SECONDS)
            self._clear_notification(f"details_{station}")
            registry = dr.async_get(self.hass)
            device = registry.async_get_device(identifiers={(DOMAIN, station)})
            if device:
                # name_by_user is deliberately left unchanged.
                registry.async_update_device(device.id, name=station_name(details))
            shape_changed = previous is not None and (
                (previous.get("wholeDay") is True, bool(previous.get("overrides")))
                != (details.get("wholeDay") is True, bool(details.get("overrides")))
            )
        except UpdateFailed as err:
            self._notify(f"details_{station}", f"Tankstelle {station}: {err}")
            state["next_detail_due"] = utcnow().timestamp() + DETAIL_RETRY_SECONDS
        except Exception as err:
            self._notify(f"details_{station}", f"Tankstelle {station}: interner Detailfehler ({type(err).__name__})")
            state["next_detail_due"] = utcnow().timestamp() + DETAIL_RETRY_SECONDS
        finally:
            if not self._stopped:
                await self._save()
                if self._started:
                    self.async_set_updated_data(self.data)
                    self._schedule_detail(station)
                    if shape_changed:
                        # Rebuild the conditional entities when wholeDay/overrides change.
                        self.hass.async_create_task(self.hass.config_entries.async_reload(self.entry.entry_id))

    async def _save(self):
        async with self._save_lock:
            stations = {}
            for station, state in self.data["stations"].items():
                stations[station] = {**state, "last_detail": state["last_detail"].isoformat() if state["last_detail"] else None}
            payload = {
                "identities": self.identities, "stations": stations,
                "last_price": self.data["last_price"].isoformat() if self.data["last_price"] else None,
                "next_price_due": self._next_price_due, "prices_ok": self.data["prices_ok"],
            }
            try:
                await self._store.async_save(payload)
            except Exception:
                _LOGGER.warning("%s: Cache konnte nicht gespeichert werden", NAME)

    def _notification_id(self, key):
        return f"{DOMAIN}_{self.entry.entry_id}_{key}"

    def _notify(self, key, message):
        if self._active_notifications.get(key) == message:
            return
        self._active_notifications[key] = message
        _LOGGER.error("%s: %s", NAME, message)
        persistent_notification.async_create(
            self.hass, message, title=NAME, notification_id=self._notification_id(key)
        )

    def _clear_notification(self, key):
        self._active_notifications.pop(key, None)
        persistent_notification.async_dismiss(self.hass, self._notification_id(key))
