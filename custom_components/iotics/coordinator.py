"""Cloud discovery and hardware-confirmed live state."""
import asyncio
from datetime import timedelta
import logging
import time
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from .api import AuthError, ApiError
from .protocol import command, feedback_value, integer, parse_devices

_LOGGER = logging.getLogger(__name__)


class IoticsCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, api, entry=None):
        super().__init__(hass, _LOGGER, name="Iotics", config_entry=entry, update_interval=timedelta(minutes=5))
        self.api = api
        self.transport = None
        self.connected = False
        self.states = {}
        self.confirmed = set()
        self.last_seen = {}
        self.online = {}
        self._pending = {}
        self._echoed = set()
        self._feedback_revision = {}
        self._command_locks = {}
        self._closed = False
        self.command_stats = dict(sent=0, confirmed=0, timed_out=0, send_failed=0, assumed=0)
        self.feedback_stats = dict(retained=0, invalid=0, status=0, channel=0, command_echo=0)


    async def _async_update_data(self):
        try:
            devices = parse_devices(await self.api.devices())
        except AuthError as err:
            if self.transport:
                self.transport.set_tokens([])
            self.connected = False
            raise ConfigEntryAuthFailed("Sign in to Iotics again") from err
        except (ApiError, ValueError) as err:
            raise UpdateFailed("Unable to refresh Iotics devices") from err
        if self.transport:
            self.transport.set_tokens(devices)
        # Cloud values are provisional until that channel sends hardware feedback.
        for token, device in devices.items():
            for channel, metadata in device.channels.items():
                key = (token, channel)
                if key not in self.confirmed:
                    value = integer(metadata.get("status"), 1, 4) if channel in ("l1", "l2") else integer(metadata.get("status"))
                    if value is not None:
                        self.states[key] = value
        valid_keys = {(t, ch) for t, d in devices.items() for ch in d.channels}
        self.states = {k: v for k, v in self.states.items() if k in valid_keys}
        self.confirmed.intersection_update(valid_keys)
        for token in set(self.last_seen) - devices.keys():
            self.last_seen.pop(token, None)
            self.online.pop(token, None)
        return devices

    def connection_changed(self, connected):
        if self._closed:
            return
        self.connected = connected
        self.confirmed.clear()
        self.last_seen.clear()
        self.online.clear()
        if not connected:
            for _, future in self._pending.values():
                if not future.done():
                    future.set_exception(HomeAssistantError("Iotics connection lost"))
        self.async_update_listeners()

    def message_received(self, topic, payload, retained=False):
        if self._closed:
            return
        parts = topic.split("/")
        if len(parts) not in (3, 4) or parts[0] != "io" or parts[1] not in (self.data or {}):
            return
        token = parts[1]
        if retained:
            self.feedback_stats["retained"] += 1
            return
        if len(parts) == 4 and parts[3] == "sw":
            self.feedback_stats["command_echo"] += 1
            feedback = topic[:-2] + "hw"
            pending = self._pending.get(feedback)
            if pending and payload == str(pending[0]).encode("ascii"):
                self._echoed.add(feedback)
            return
        if len(parts) == 3 and parts[2] == "hwstatus":
            value = feedback_value(payload)
            if value is None:
                self.feedback_stats["invalid"] += 1
                return
            self.feedback_stats["status"] += 1
            self.online[token] = value == 1
        elif len(parts) == 4 and parts[3] == "hw" and parts[2] in self.data[token].channels:
            channel = parts[2]
            value = feedback_value(payload, 1, 4) if channel in ("l1", "l2") else feedback_value(payload)
            if value is None:
                self.feedback_stats["invalid"] += 1
                return
            self.feedback_stats["channel"] += 1
            key = (token, channel)
            self._feedback_revision[key] = self._feedback_revision.get(key, 0) + 1
            self.states[key] = value
            self.confirmed.add((token, channel))
            self.online[token] = True
            pending = self._pending.get(topic)
            if pending and pending[0] == value and not pending[1].done():
                pending[1].set_result(None)
        else:
            return
        self.last_seen[token] = time.monotonic()
        self.async_update_listeners()

    def is_available(self, token):
        return (self.last_update_success and self.connected and token in (self.data or {})
                and self.online.get(token, False)
                and time.monotonic() - self.last_seen.get(token, 0) < 150)

    async def async_probe(self, _now):
        if self.transport and not self._closed:
            self.transport.query()
            self.async_update_listeners()

    async def async_command(self, token, channel, value):
        lock = self._command_locks.setdefault((token, channel), asyncio.Lock())
        async with lock:
            if not self.is_available(token):
                raise HomeAssistantError("Iotics device is unavailable")
            try:
                topic, payload = command(self.data, token, channel, value)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
            feedback = topic[:-2] + "hw"
            key = (token, channel)
            revision = self._feedback_revision.get(key, 0)
            self._echoed.discard(feedback)
            future = self.hass.loop.create_future()
            self._pending[feedback] = (int(payload), future)
            try:
                self.transport.publish(topic, payload)
                self.command_stats["sent"] += 1
                await asyncio.wait_for(future, timeout=10)
                self.command_stats["confirmed"] += 1
            except ConnectionError as err:
                self.command_stats["send_failed"] += 1
                raise HomeAssistantError(
                    "Unable to send the Iotics command; check the MQTT connection"
                ) from err
            except TimeoutError as err:
                self.command_stats["timed_out"] += 1
                if self._feedback_revision.get(key, 0) != revision:
                    raise HomeAssistantError(
                        "Iotics reported a different state after the command; check the device"
                    ) from err
                if feedback not in self._echoed or not self.is_available(token):
                    raise HomeAssistantError(
                        "No Iotics command confirmation; check the connection and physical device"
                    ) from err
                # An echoed command confirms broker receipt, not physical actuation.
                # Panels without channel feedback need an explicitly assumed state.
                self.states[key] = int(payload)
                self.confirmed.discard(key)
                self.command_stats["assumed"] += 1
                self.async_update_listeners()
            finally:
                self._pending.pop(feedback, None)
                self._echoed.discard(feedback)
                if not future.done():
                    future.cancel()

    def close(self):
        self._closed = True
        for _, future in self._pending.values():
            if not future.done():
                future.cancel()
