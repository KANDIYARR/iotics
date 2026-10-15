"""Shared hardware entity behavior."""
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN


class IoticsEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, account_id, token, channel):
        super().__init__(coordinator)
        self.token, self.channel = token, channel
        device = coordinator.data[token]
        self._attr_unique_id = f"{account_id}_{token}_{channel}"
        self._attr_name = str(device.channels[channel].get("label") or channel.upper())
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{account_id}_{token}")},
            name=device.name, manufacturer="Iotics", model=device.model,
        )

    @property
    def available(self):
        device = (self.coordinator.data or {}).get(self.token)
        return bool(device and self.channel in device.controls and self.coordinator.is_available(self.token))

    @property
    def assumed_state(self):
        return (self.token, self.channel) not in self.coordinator.confirmed

    @property
    def is_on(self):
        value = self.coordinator.states.get((self.token, self.channel))
        return None if value is None else value == 1

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_command(self.token, self.channel, 0)


def setup_entities(hass, entry, async_add_entities, entity_type, prefix):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    known = set()

    def discover():
        entities = []
        for token, device in (coordinator.data or {}).items():
            for channel in device.controls:
                key = (token, channel)
                if channel.startswith(prefix) and key not in known:
                    known.add(key)
                    entities.append(entity_type(coordinator, entry.unique_id, token, channel))
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))
