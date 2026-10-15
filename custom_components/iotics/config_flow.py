"""Sign in using the user's own Iotics account."""
import uuid
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from .api import ApiError, AuthError, IoticsApi
from .const import DOMAIN, PROFILE_FILE
from .protocol import Profile, ProfileError, parse_devices


class IoticsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            email = user_input[CONF_EMAIL].strip()
            device_id = getattr(self, "_device_id", None) or str(uuid.uuid4())
            try:
                profile = await self.hass.async_add_executor_job(Profile.load, self.hass.config.path(PROFILE_FILE))
                api = IoticsApi(async_get_clientsession(self.hass), profile, email,
                                user_input[CONF_PASSWORD], device_id)
                await api.login()
                parse_devices(await api.devices())
            except ProfileError:
                errors["base"] = "missing_profile"
            except AuthError:
                errors["base"] = "invalid_auth"
            except (ApiError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(api.user_id)
                data = {CONF_EMAIL: email, CONF_PASSWORD: user_input[CONF_PASSWORD], "device_id": device_id}
                if self.source == "reauth":
                    entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
                    if entry.unique_id != api.user_id:
                        return self.async_abort(reason="wrong_account")
                    self.hass.config_entries.async_update_entry(entry, data=data)
                    await self.hass.config_entries.async_reload(entry.entry_id)
                    return self.async_abort(reason="reauth_successful")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=email, data=data)
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_EMAIL): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.EMAIL)),
            vol.Required(CONF_PASSWORD): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
        }), errors=errors)

    async def async_step_reauth(self, entry_data):
        self._device_id = entry_data["device_id"]
        return await self.async_step_user()
