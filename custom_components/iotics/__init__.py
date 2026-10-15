"""Unofficial account-based Iotics Home Assistant integration."""

__author__ = "Vinoth Sakthivel"
__email__ = "vinoth@kandiyar.com"

from datetime import timedelta
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from .api import IoticsApi
from .const import DOMAIN, PLATFORMS, PROFILE_FILE
from .coordinator import IoticsCoordinator
from .protocol import Profile, ProfileError
from .transport import Transport


async def async_setup_entry(hass, entry):
    try:
        profile = await hass.async_add_executor_job(Profile.load, hass.config.path(PROFILE_FILE))
    except ProfileError as err:
        raise ConfigEntryNotReady(f"Place the private {PROFILE_FILE} in the Home Assistant config folder") from err
    api = IoticsApi(async_get_clientsession(hass), profile, entry.data[CONF_EMAIL],
                    entry.data[CONF_PASSWORD], entry.data["device_id"])
    coordinator = IoticsCoordinator(hass, api, entry)
    await coordinator.async_config_entry_first_refresh()
    transport = await hass.async_add_executor_job(
        Transport, profile, hass.loop, coordinator.connection_changed, coordinator.message_received)
    coordinator.transport = transport
    transport.set_tokens(coordinator.data)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        transport.start()
    except Exception:
        coordinator.close()
        await hass.async_add_executor_job(transport.stop)
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise
    entry.async_on_unload(async_track_time_interval(hass, coordinator.async_probe, timedelta(seconds=60)))

    async def stop(_event):
        coordinator.close()
        await hass.async_add_executor_job(transport.stop)

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop))
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        coordinator.close()
        await hass.async_add_executor_job(coordinator.transport.stop)
        return True
    return False
