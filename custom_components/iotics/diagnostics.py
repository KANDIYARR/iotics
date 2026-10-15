"""Diagnostics intentionally omit account data, tokens and connection profiles."""
from .const import DOMAIN


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "mqtt_connected": coordinator.connected,
        "last_discovery_success": coordinator.last_update_success,
        "device_count": len(coordinator.data or {}),
        "control_count": sum(len(d.controls) for d in (coordinator.data or {}).values()),
        "available_count": sum(coordinator.is_available(t) for t in (coordinator.data or {})),
        "unverified_channels_omitted": sum(len(set(d.channels) - set(d.controls) - {"l1", "l2"})
                                           for d in (coordinator.data or {}).values()),
    }
