"""Power and verified four-level fan control."""
import math
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import HomeAssistantError
from .entity import IoticsEntity, setup_entities


async def async_setup_entry(hass, entry, async_add_entities):
    setup_entities(hass, entry, async_add_entities, IoticsFan, "f")


class IoticsFan(IoticsEntity, FanEntity):
    @property
    def supported_features(self):
        features = FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
        device = (self.coordinator.data or {}).get(self.token)
        if device and device.supports_speed(self.channel):
            features |= FanEntityFeature.SET_SPEED
        return features

    @property
    def speed_count(self):
        return 4

    @property
    def percentage(self):
        if self.is_on is False:
            return 0
        level = self.coordinator.states.get((self.token, "l" + self.channel[1:]))
        return level * 25 if level is not None and self.is_on else None

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        if percentage == 0:
            await self.async_turn_off()
            return
        if percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self.coordinator.async_command(self.token, self.channel, 1)

    async def async_set_percentage(self, percentage):
        if not 0 <= percentage <= 100:
            raise HomeAssistantError("Fan percentage must be between 0 and 100")
        if percentage == 0:
            await self.async_turn_off()
            return
        device = (self.coordinator.data or {}).get(self.token)
        if not device or not device.supports_speed(self.channel):
            raise HomeAssistantError("Speed control is not verified for this fan")
        if self.is_on is not True:
            await self.coordinator.async_command(self.token, self.channel, 1)
        await self.coordinator.async_command(self.token, "l" + self.channel[1:], math.ceil(percentage / 25))
