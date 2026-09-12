"""The zone geometry a hob describes, turned into where to draw each zone."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import hob
from custom_components.homeconnect.hob import layout
from custom_components.homeconnect.iddf import Entry

from .common import device_for, set_up

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
    assert hob._for_device(hass, "a-device-that-does-not-exist") == []


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
