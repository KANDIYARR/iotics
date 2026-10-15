"""Offline tests: synthetic devices and mocked Iotics endpoints only."""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import json
import time
import pytest
from botocore.auth import SigV4QueryAuth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from custom_components.iotics.api import IoticsApi, AuthError, ApiError
from custom_components.iotics.protocol import Profile, ProfileError, parse_devices, command, websocket_path
from custom_components.iotics.coordinator import IoticsCoordinator
from custom_components.iotics.switch import IoticsSwitch
from custom_components.iotics.fan import IoticsFan
from custom_components.iotics.transport import Transport

PROFILE = Profile('app', 'bootstrap', 'FAKEACCESS', 'fakesecret', 'ap-south-1', 'example.iot.ap-south-1.amazonaws.com')
RECORDS = [{'hardwaretoken': 'owned-device', 'hardwarename': 'Living room', 'hardwaretype': 'io-touch-3s1f',
            'switches': {'b1': {'label': 'Light', 'status': 0}, 'f1': {'label': 'Fan'}, 'l1': {'status': 2}, 'c1': {}, 'dl1': {}}}]


def test_signing_matches_aws_sdk():
    now = datetime(2026, 10, 15, 10, 0, tzinfo=timezone.utc)
    request = AWSRequest(method='GET', url=f'https://{PROFILE.host}/mqtt')
    with patch('botocore.auth.get_current_datetime', return_value=now):
        SigV4QueryAuth(Credentials(PROFILE.access_key, PROFILE.secret_key), 'iotdevicegateway', PROFILE.region, expires=900).add_auth(request)
    assert request.url.split(PROFILE.host)[1] == websocket_path(PROFILE, now)


def test_command_scope_and_ranges():
    devices = parse_devices(RECORDS)
    assert command(devices, 'owned-device', 'b1', 1) == ('io/owned-device/b1/sw', '1')
    assert command(devices, 'owned-device', 'l1', 4)[1] == '4'
    for token, channel, value in [('other', 'b1', 1), ('owned-device', 'c1', 1), ('owned-device', 'l1', 5), ('owned-device', 'b1', 2)]:
        with pytest.raises(ValueError): command(devices, token, channel, value)
    devices['owned-device'].channels['f1']['is_bldc'] = 1
    with pytest.raises(ValueError): command(devices, 'owned-device', 'l1', 3)
    assert command(devices, 'owned-device', 'f1', 1)[1] == '1'


def test_reject_topic_injection_and_bad_profile(tmp_path):
    for token in ['#', 'x/+/y', '../b', '']:
        with pytest.raises(ValueError): parse_devices([{**RECORDS[0], 'hardwaretoken': token}])
    path = tmp_path / 'profile.json'
    path.write_text('{}')
    with pytest.raises(ProfileError): Profile.load(path)
    assert 'fakesecret' not in repr(PROFILE)


class Response:
    def __init__(self, data, status=200): self.data, self.status = data, status
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def json(self): return self.data


def api_with(*responses):
    session = MagicMock()
    session.post.side_effect = responses
    return IoticsApi(session, PROFILE, 'user@example.test', 'not-real', 'stable-id')


LOGIN = {'status': 'success', 'response': {'access_token': 'session', 'user': {'user_id': 123}}}
LIST = {'status': 'success', 'response': {'devices': RECORDS}}


@pytest.mark.asyncio
async def test_account_discovery_and_payload():
    api = api_with(Response(LOGIN), Response(LIST))
    assert await api.devices() == RECORDS
    login, listing = api.session.post.call_args_list
    assert login.kwargs['json']['action'] == 'login'
    assert login.kwargs['json']['password'] == 'not-real'
    assert listing.kwargs['json']['user_id'] == '123'
    assert listing.kwargs['headers']['Authorization'] == 'Bearer session'
    assert listing.kwargs['allow_redirects'] is False
    assert 'password' not in listing.kwargs['json']


@pytest.mark.asyncio
async def test_expired_session_retries_once():
    api = api_with(Response(LOGIN), Response({}, 401), Response(LOGIN), Response({}, 401))
    with pytest.raises(AuthError): await api.devices()
    assert api.session.post.call_count == 4


@pytest.mark.asyncio
async def test_network_error_not_misreported_as_bad_password():
    api = api_with(Response({}, 503))
    with pytest.raises(ApiError): await api.login()


def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    api = MagicMock()
    api.devices = AsyncMock(return_value=RECORDS)
    c = IoticsCoordinator(hass, api)
    c.data = parse_devices(RECORDS)
    c.connected = True
    c.transport = MagicMock()
    c.message_received('io/owned-device/hwstatus', b'1')
    return c


@pytest.mark.asyncio
async def test_hardware_confirmation_and_ignored_messages(tmp_path):
    c = coordinator(tmp_path)
    switch = IoticsSwitch(c, 'account', 'owned-device', 'b1')
    c.message_received('io/owned-device/b1/hw', b'0')
    task = asyncio.create_task(switch.async_turn_on())
    await asyncio.sleep(0)
    assert switch.is_on is False
    for topic, payload, retained in [('io/other/b1/hw', b'1', False), ('io/owned-device/b1/sw', b'1', False), ('io/owned-device/b1/hw', b'1', True), ('io/owned-device/b1/hw', b'2', False)]:
        c.message_received(topic, payload, retained)
    assert not task.done()
    c.message_received('io/owned-device/b1/hw', b'1')
    await task
    assert switch.is_on is True
    assert switch.device_info['name'] == 'Living room'


@pytest.mark.asyncio
async def test_disconnect_fails_pending_and_expires_availability(tmp_path):
    c = coordinator(tmp_path)
    task = asyncio.create_task(c.async_command('owned-device', 'b1', 1))
    await asyncio.sleep(0)
    c.connection_changed(False)
    with pytest.raises(HomeAssistantError): await task
    assert not c.is_available('owned-device')
    c.connection_changed(True)
    assert not c.is_available('owned-device')
    c.message_received('io/owned-device/hwstatus', b'1')
    c.last_seen['owned-device'] = time.monotonic() - 151
    assert not c.is_available('owned-device')


@pytest.mark.asyncio
async def test_fan_waits_for_power_before_speed(tmp_path):
    c = coordinator(tmp_path)
    fan = IoticsFan(c, 'account', 'owned-device', 'f1')
    c.message_received('io/owned-device/f1/hw', b'0')
    task = asyncio.create_task(fan.async_set_percentage(60))
    await asyncio.sleep(0)
    c.transport.publish.assert_called_once_with('io/owned-device/f1/sw', '1')
    c.message_received('io/owned-device/f1/hw', b'1')
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    c.transport.publish.assert_called_with('io/owned-device/l1/sw', '3')
    c.message_received('io/owned-device/l1/hw', b'3')
    await task
    assert fan.percentage == 75


@pytest.mark.asyncio
async def test_auth_failure_revokes_mqtt_scope(tmp_path):
    c = coordinator(tmp_path)
    c.api.devices.side_effect = AuthError()
    with pytest.raises(ConfigEntryAuthFailed): await c._async_update_data()
    c.transport.set_tokens.assert_called_once_with([])
    assert not c.connected


@pytest.mark.asyncio
async def test_transport_scopes_subscriptions_and_no_retained_controls():
    with patch('custom_components.iotics.transport.mqtt.Client') as client:
        mock = client.return_value
        mock.subscribe.return_value = (0, 12)
        mock.publish.return_value.rc = 0
        mock.is_connected.return_value = True
        transport = Transport(PROFILE, asyncio.get_running_loop(), MagicMock(), MagicMock())
        transport.set_tokens(['owned-device'])
        mock.subscribe.assert_called_once_with('io/owned-device/#', qos=0)
        transport.publish('io/owned-device/b1/sw', '1')
        mock.publish.assert_called_with('io/owned-device/b1/sw', '1', qos=0, retain=False)
        transport.set_tokens([])
        mock.unsubscribe.assert_called_once_with('io/owned-device/#')
        with pytest.raises(ConnectionError): transport.publish('io/owned-device/b1/sw', '1')


@pytest.mark.asyncio
async def test_setup_form_reports_missing_profile(tmp_path):
    from custom_components.iotics.config_flow import IoticsConfigFlow
    flow = IoticsConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    result = await flow.async_step_user({'email': 'user@example.test', 'password': 'fake'})
    assert result['errors'] == {'base': 'missing_profile'}


@pytest.mark.asyncio
async def test_setup_form_authenticates_and_stores_no_profile_secrets(tmp_path):
    from custom_components.iotics.config_flow import IoticsConfigFlow
    flow = IoticsConfigFlow()
    flow.hass = HomeAssistant(str(tmp_path))
    flow.context = {'source': 'user'}
    with patch('custom_components.iotics.config_flow.Profile.load', return_value=PROFILE), \
         patch('custom_components.iotics.config_flow.IoticsApi') as api_class, \
         patch.object(flow, 'async_set_unique_id', new=AsyncMock()), \
         patch.object(flow, '_abort_if_unique_id_configured'), \
         patch('custom_components.iotics.config_flow.async_get_clientsession'):
        api = api_class.return_value
        api.login = AsyncMock()
        api.devices = AsyncMock(return_value=RECORDS)
        api.user_id = 'account'
        result = await flow.async_step_user({'email': ' user@example.test ', 'password': 'fake'})
    assert result['type'] == 'create_entry'
    assert result['data']['email'] == 'user@example.test'
    assert set(result['data']) == {'email', 'password', 'device_id'}


@pytest.mark.asyncio
async def test_setup_and_unload_lifecycle(tmp_path):
    from custom_components.iotics import async_setup_entry, async_unload_entry
    from custom_components.iotics.const import DOMAIN
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = MagicMock()
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    entry = MagicMock()
    from homeassistant.config_entries import ConfigEntryState
    entry.state = ConfigEntryState.SETUP_IN_PROGRESS
    entry.pref_disable_polling = False
    entry.entry_id = 'entry'
    entry.data = {'email': 'user@example.test', 'password': 'fake', 'device_id': 'installation'}
    with patch('custom_components.iotics.Profile.load', return_value=PROFILE), \
         patch('custom_components.iotics.IoticsApi') as api_class, \
         patch('custom_components.iotics.Transport') as transport_class, \
         patch('custom_components.iotics.async_get_clientsession'), \
         patch('custom_components.iotics.async_track_time_interval', return_value=lambda: None):
        api_class.return_value.devices = AsyncMock(return_value=RECORDS)
        assert await async_setup_entry(hass, entry)
        transport_class.return_value.start.assert_called_once()
        assert len(hass.data[DOMAIN]['entry'].data) == 1
        assert await async_unload_entry(hass, entry)
        transport_class.return_value.stop.assert_called_once()
        assert not hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_discovery_additions_and_removals(tmp_path):
    from custom_components.iotics.entity import setup_entities
    from custom_components.iotics.const import DOMAIN
    c = coordinator(tmp_path)
    entry = MagicMock(entry_id='entry', unique_id='account')
    c.hass.data[DOMAIN] = {'entry': c}
    add = MagicMock()
    setup_entities(c.hass, entry, add, IoticsSwitch, 'b')
    entity = add.call_args.args[0][0]
    assert entity.available
    c.api.devices.return_value = []
    c.data = await c._async_update_data()
    c.async_update_listeners()
    assert not entity.available
    c.transport.set_tokens.assert_called_with({})
