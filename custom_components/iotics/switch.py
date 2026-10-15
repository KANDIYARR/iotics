"""Iotics switch channels."""
from homeassistant.components.switch import SwitchEntity
from .entity import IoticsEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_entities(hass, entry, async_add_entities, IoticsSwitch, "b")


class IoticsSwitch(IoticsEntity, SwitchEntity):
    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_command(self.token, self.channel, 1)
