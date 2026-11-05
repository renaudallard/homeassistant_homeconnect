"""The zone geometry a hob describes, turned into where to draw each zone."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import hob
from custom_components.homeconnect.capability import Reading
from custom_components.homeconnect.errors import HomeConnectError
from custom_components.homeconnect.hob import layout
from custom_components.homeconnect.iddf import Entry

from .common import device_for, noting_the_loop, set_up

HAID = "BOSCH-WAV28MH0GB-1234567890AB"


def _zone(uid: int, number: int, field: str, static: str) -> Entry:
    return Entry(
        uid=uid,
        kind="status",
        key=f"Cooking.Hob.Status.Zone.{number}.{field}",
        static=static,
    )


def _hob(*specs: tuple[int, int, str, str]) -> dict[int, Entry]:
    return {
        uid: _zone(uid, number, field, static) for uid, number, field, static in specs
    }


def test_a_zone_is_placed_where_the_description_says() -> None:
    entries = _hob(
        (1, 100, "Position", '{"x":147,"y":194,"angleX":0}'),
        (2, 100, "LengthX", "230"),
        (3, 100, "LengthY", "190"),
        (4, 100, "Shape", "2"),
    )
    assert layout(entries) == [
        {"zone": 100, "x": 147.0, "y": 194.0, "w": 230.0, "h": 190.0, "round": False},
    ]


def test_shape_zero_is_a_round_zone() -> None:
    entries = _hob(
        (1, 300, "Position", '{"x":448,"y":398}'),
        (2, 300, "LengthX", "150"),
        (3, 300, "LengthY", "150"),
        (4, 300, "Shape", "0"),
    )
    (drawn,) = layout(entries)
    assert drawn["round"] is True


def test_zones_come_back_in_order() -> None:
    entries = _hob(
        (1, 400, "Position", '{"x":448,"y":190}'),
        (2, 400, "LengthX", "210"),
        (3, 400, "LengthY", "210"),
        (4, 100, "Position", '{"x":147,"y":194}'),
        (5, 100, "LengthX", "230"),
        (6, 100, "LengthY", "190"),
    )
    assert [zone["zone"] for zone in layout(entries)] == [100, 400]


def test_a_zone_without_a_place_is_left_out() -> None:
    """Size but no position says nothing about where to draw it, so it is not
    drawn rather than drawn in the wrong spot."""
    entries = _hob(
        (1, 100, "LengthX", "230"),
        (2, 100, "LengthY", "190"),
    )
    assert layout(entries) == []


def test_an_appliance_with_no_zones_has_no_layout() -> None:
    entries = {
        1: Entry(uid=1, kind="status", key="BSH.Common.Status.DoorState"),
        2: Entry(uid=2, kind="setting", key="BSH.Common.Setting.PowerState"),
    }
    assert layout(entries) == []


def test_a_place_that_does_not_read_is_left_out() -> None:
    entries = _hob(
        (1, 100, "Position", "not json"),
        (2, 100, "LengthX", "230"),
        (3, 100, "LengthY", "190"),
    )
    assert layout(entries) == []


def test_a_size_that_is_not_a_number_leaves_the_zone_out() -> None:
    """A place but a dimension that will not read as a figure says nothing
    about how big to draw it, so the zone is left out."""
    entries = _hob(
        (1, 100, "Position", '{"x":147,"y":194}'),
        (2, 100, "LengthX", "wide"),
        (3, 100, "LengthY", "190"),
    )
    assert layout(entries) == []


def test_a_place_that_is_not_a_point_is_left_out() -> None:
    """Valid JSON that is not an object is not somewhere to put a zone."""
    entries = _hob(
        (1, 100, "Position", "5"),
        (2, 100, "LengthX", "230"),
        (3, 100, "LengthY", "190"),
    )
    assert layout(entries) == []


async def test_no_geometry_for_a_device_that_is_not_known(
    hass: HomeAssistant,
) -> None:
    assert await hob._for_device(hass, "a-device-that-does-not-exist") == []


async def test_the_card_can_ask_where_a_hobs_zones_are(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: Any,
) -> None:
    """The card asks over the websocket by device. A washer describes no zones,
    so it answers with an empty list rather than an error."""
    made = await set_up(hass, aioclient_mock, "washer")
    device = device_for(hass, made, HAID)
    assert device is not None
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "homeconnect/hob_layout", "device_id": device.id}
    )
    answer = await client.receive_json()
    assert answer["success"]
    assert answer["result"] == {"zones": []}


DESCRIPTION = "custom_components.homeconnect.api.HomeConnectAccount.description"

# The left side of the hob in the diagnostics of 2026-11-05: two flex halves
# and the zone they make when joined. Over the cloud only the halves carry
# their place in the readings; the joined one arrives with none.
FLEX = _hob(
    (1, 100, "Position", '{"x":147,"y":194,"angleX":0}'),
    (2, 100, "LengthX", "230"),
    (3, 100, "LengthY", "190"),
    (4, 100, "Shape", "2"),
    (5, 120, "Position", '{"x":147,"y":290,"angleX":0}'),
    (6, 120, "LengthX", "230"),
    (7, 120, "LengthY", "380"),
    (8, 120, "Shape", "2"),
    (9, 200, "Position", '{"x":147,"y":385,"angleX":0}'),
    (10, 200, "LengthX", "230"),
    (11, 200, "LengthY", "190"),
    (12, 200, "Shape", "2"),
)

JOINED = {"zone": 120, "x": 147.0, "y": 290.0, "w": 230.0, "h": 380.0, "round": False}


async def _a_cloud_hob(
    hass: HomeAssistant, mock: AiohttpClientMocker
) -> tuple[MockConfigEntry, dr.DeviceEntry]:
    """An entry over the cloud whose one appliance reports a zone, and its
    device. The washer fixture stands in, given the reading a hob makes."""
    made = await set_up(hass, mock, "washer")
    appliance = made.runtime_data.coordinator.data[HAID]
    appliance.status["Cooking.Hob.Status.Zone.120.State"] = Reading(
        value="Cooking.Hob.EnumType.ZoneState.Active"
    )
    device = device_for(hass, made, HAID)
    assert device is not None
    return made, device


async def test_a_hob_over_the_cloud_is_laid_out_from_its_description(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The joined zone is placed too, which the cloud readings cannot do."""
    _made, device = await _a_cloud_hob(hass, aioclient_mock)
    with (
        patch(DESCRIPTION, AsyncMock(return_value=b"a zip")),
        patch.object(hob, "unpack", lambda _archive: FLEX),
    ):
        zones = await hob._for_device(hass, device.id)
    assert [zone["zone"] for zone in zones] == [100, 120, 200]
    assert zones[1] == JOINED


async def test_a_hobs_description_is_fetched_once(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Two cards asking at the same moment share one fetch, and a later ask
    is answered from what was kept."""
    _made, device = await _a_cloud_hob(hass, aioclient_mock)
    fetched = AsyncMock(return_value=b"a zip")
    with patch(DESCRIPTION, fetched), patch.object(hob, "unpack", lambda _a: FLEX):
        first, second = await asyncio.gather(
            hob._for_device(hass, device.id), hob._for_device(hass, device.id)
        )
        third = await hob._for_device(hass, device.id)
    assert first == second == third
    assert JOINED in first
    assert fetched.await_count == 1


async def test_a_description_that_cannot_be_had_is_asked_for_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A failed fetch leaves the card a grid that time and is not kept."""
    _made, device = await _a_cloud_hob(hass, aioclient_mock)
    fetched = AsyncMock(side_effect=[HomeConnectError("nothing doing"), b"a zip"])
    with patch(DESCRIPTION, fetched), patch.object(hob, "unpack", lambda _a: FLEX):
        assert await hob._for_device(hass, device.id) == []
        assert JOINED in await hob._for_device(hass, device.id)
    assert fetched.await_count == 2


async def test_an_appliance_with_no_zones_costs_no_fetch(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = await set_up(hass, aioclient_mock, "washer")
    device = device_for(hass, made, HAID)
    assert device is not None
    fetched = AsyncMock(return_value=b"a zip")
    with patch(DESCRIPTION, fetched):
        assert await hob._for_device(hass, device.id) == []
    fetched.assert_not_awaited()


async def test_the_description_is_read_off_the_event_loop(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    _made, device = await _a_cloud_hob(hass, aioclient_mock)
    on_loop: list[bool] = []
    with (
        patch(DESCRIPTION, AsyncMock(return_value=b"a zip")),
        patch.object(hob, "unpack", lambda _a: FLEX),
        patch.object(hob, "_drawn", noting_the_loop(hob._drawn, on_loop)),
    ):
        await hob._for_device(hass, device.id)
    assert on_loop == [False]


async def test_a_hob_reached_directly_is_laid_out_from_what_local_kept(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Local control already holds the description, so nothing is fetched."""
    made, device = await _a_cloud_hob(hass, aioclient_mock)
    made.runtime_data.local = SimpleNamespace(entries=lambda _haid: FLEX)
    fetched = AsyncMock(return_value=b"a zip")
    with patch(DESCRIPTION, fetched):
        zones = await hob._for_device(hass, device.id)
    assert JOINED in zones
    fetched.assert_not_awaited()


async def test_the_card_gets_a_cloud_hobs_layout(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    hass_ws_client: Any,
) -> None:
    _made, device = await _a_cloud_hob(hass, aioclient_mock)
    client = await hass_ws_client(hass)
    with (
        patch(DESCRIPTION, AsyncMock(return_value=b"a zip")),
        patch.object(hob, "unpack", lambda _a: FLEX),
    ):
        await client.send_json_auto_id(
            {"type": "homeconnect/hob_layout", "device_id": device.id}
        )
        answer = await client.receive_json()
    assert answer["success"]
    assert JOINED in answer["result"]["zones"]
