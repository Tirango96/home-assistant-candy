"""Tests for the remote control binary sensor."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from .common import init_integration

_REMOTE_CONTROL = "binary_sensor.remote_control"


async def test_remote_control_on_when_enabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get(_REMOTE_CONTROL)
    assert state is not None
    assert state.state == "on"


async def test_remote_control_off_when_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    status = load_fixture("washing_machine/idle.json").replace(
        '"WiFiStatus": "1"', '"WiFiStatus": "0"'
    )
    await init_integration(hass, aioclient_mock, status)

    state = hass.states.get(_REMOTE_CONTROL)
    assert state is not None
    assert state.state == "off"
