"""Tests for Candy Wine Cooler light platform."""

from homeassistant.const import CONF_IP_ADDRESS, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry, load_fixture
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.candy import CONF_KEY_USE_ENCRYPTION, DOMAIN

from .common import TEST_IP, init_integration


async def test_wine_cooler_light_state_on(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wine cooler light entity is created and reports On."""
    payload = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"1"}}'
    await init_integration(hass, aioclient_mock, payload)

    state = hass.states.get("light.wine_cooler_light")
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get("friendly_name") == "Wine cooler Light"


async def test_wine_cooler_light_state_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test wine cooler light entity reports Off."""
    payload = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"0"}}'
    await init_integration(hass, aioclient_mock, payload)

    state = hass.states.get("light.wine_cooler_light")
    assert state is not None
    assert state.state == "off"


async def test_wine_cooler_light_turn_on(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test turning on wine cooler light sends write command."""
    payload_off = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"0"}}'
    payload_on = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"1"}}'

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123-456",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    entry.add_to_hass(hass)

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=payload_off,
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Write=1&w1=1&w2=16&w7=1",
        text='{"response":"OK"}',
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Change read mock to return light ON after command
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=payload_on,
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Write=1&w1=1&w2=16&w7=1",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "light",
        "turn_on",
        {"entity_id": "light.wine_cooler_light"},
        blocking=True,
    )

    state = hass.states.get("light.wine_cooler_light")
    assert state is not None
    assert state.state == "on"


async def test_wine_cooler_light_turn_off(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test turning off wine cooler light sends write command."""
    payload_on = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"1"}}'
    payload_off = '{"statusWCool":{"r1":"1","r2":"E0","r3":"1","r4":"16","r5":"2","r6":"0","r7":"0","r8":"0","r9":"0","r10":"0"}}'

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="123-456",
        data={
            CONF_IP_ADDRESS: TEST_IP,
            CONF_KEY_USE_ENCRYPTION: False,
            CONF_PASSWORD: "",
        },
    )
    entry.add_to_hass(hass)

    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=payload_on,
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Write=1&w1=1&w2=16&w7=0",
        text='{"response":"OK"}',
    )

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    # Change read mock to return light OFF after command
    aioclient_mock.clear_requests()
    aioclient_mock.get(
        f"http://{TEST_IP}/http-read.json?encrypted=0",
        text=payload_off,
    )
    aioclient_mock.get(
        f"http://{TEST_IP}/http-write.json?encrypted=0&Write=1&w1=1&w2=16&w7=0",
        text='{"response":"OK"}',
    )

    await hass.services.async_call(
        "light",
        "turn_off",
        {"entity_id": "light.wine_cooler_light"},
        blocking=True,
    )

    state = hass.states.get("light.wine_cooler_light")
    assert state is not None
    assert state.state == "off"


async def test_non_wine_cooler_no_light_entity(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
):
    """Test that non-wine-cooler appliances (washing machine) do not create a light entity."""
    await init_integration(
        hass, aioclient_mock, load_fixture("washing_machine/idle.json")
    )

    state = hass.states.get("light.wine_cooler_light")
    assert state is None
