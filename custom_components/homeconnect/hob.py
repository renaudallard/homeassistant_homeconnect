# BSD 2-Clause License
#
# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


"""Where a hob's zones physically sit, for the card that draws them.

A hob writes the position, size and shape of every one of its zones into its
description, as fixed values the live stream never sends. The card that draws
the cooktop has no way to read those on its own, so it asks over the websocket
and this answers, one hob at a time, with the geometry read straight from what
the appliance said about itself.

The geometry rides on the appliance's own description. Reached directly, that
is parsed and kept already. Over the cloud the readings carry the place of a
zone only while it is a zone on its own: a flex zone made of two arrives
without one. So a hob reached that way has its description fetched from the
account the first time a card asks, and kept until the entry is reloaded.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.websocket_api import (  # type: ignore[attr-defined]
    ActiveConnection,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import HomeConnectAccount
from .const import DOMAIN
from .errors import HomeConnectError
from .iddf import Entry, unpack

if TYPE_CHECKING:
    from . import HomeConnectData

_LOGGER = logging.getLogger(__name__)

_REGISTERED = f"{DOMAIN}_hob_websocket"

# The geometry a hob writes for each zone: a point it sits at, its size along
# each side, and which of a round or a rounded-cornered shape it is.
_ZONE = re.compile(
    r"Cooking\.Hob\.Status\.Zone\.(\d+)\.(Position|LengthX|LengthY|Shape)$"
)

# What every reading about a zone starts with, which is what makes an
# appliance a hob as far as the card is concerned.
_ZONES = "Cooking.Hob.Status.Zone."

# The shape a hob calls zero is a plain round one; the rest are drawn as a
# rounded rectangle, which is what the long flex zones are.
_ROUND = "0"


def _figure(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def layout(entries: dict[int, Entry]) -> list[dict[str, Any]]:
    """The zones of a hob, each where the description says it sits.

    Read straight, the fixed values place every zone on the glass exactly as
    the appliance has it, the joinable ones among them. The card is handed the
    numbers as they are and works out the frame to fit them.
    """
    zones: dict[str, dict[str, str]] = {}
    for entry in entries.values():
        found = _ZONE.match(entry.key)
        if found and entry.static is not None:
            zones.setdefault(found.group(1), {})[found.group(2)] = entry.static

    drawn: list[dict[str, Any]] = []
    for number, field in zones.items():
        try:
            point = json.loads(field["Position"])
        except (KeyError, ValueError, TypeError):
            continue
        if not isinstance(point, dict):
            continue
        x, y = _figure(point.get("x")), _figure(point.get("y"))
        width, height = _figure(field.get("LengthX")), _figure(field.get("LengthY"))
        if x is None or y is None or width is None or height is None:
            continue
        drawn.append(
            {
                "zone": int(number),
                "x": x,
                "y": y,
                "w": width,
                "h": height,
                "round": (field.get("Shape") or "").strip() == _ROUND,
            }
        )
    drawn.sort(key=lambda zone: zone["zone"])
    return drawn


def _drawn(archive: bytes) -> list[dict[str, Any]]:
    """The zones out of a description archive, as layout() places them."""
    return layout(unpack(archive))


async def _from_account(
    hass: HomeAssistant, data: HomeConnectData, haid: str
) -> list[dict[str, Any]]:
    """The zones of a hob reached over the cloud, from its description.

    Asked for once and kept. A fetch that fails is not kept, so the card
    gets a grid this time and the next one to ask tries again.
    """
    appliance = data.coordinator.data.get(haid)
    if appliance is None or not any(key.startswith(_ZONES) for key in appliance.status):
        return []
    async with data.hob_lock:
        drawn = data.hob_layouts.get(haid)
        if drawn is None:
            try:
                archive = await HomeConnectAccount(data.api).description(haid)
                drawn = await hass.async_add_executor_job(_drawn, archive)
            except HomeConnectError as err:
                _LOGGER.debug("no zone layout for the hob: %s", err)
                return []
            data.hob_layouts[haid] = drawn
    return drawn


async def _for_device(hass: HomeAssistant, device_id: str) -> list[dict[str, Any]]:
    """The zone geometry of the appliance behind one device, if it has any."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        return []
    haid = next((who for kind, who in device.identifiers if kind == DOMAIN), None)
    if haid is None:
        return []
    entry = hass.config_entries.async_get_entry(device.config_entry_id)
    data: HomeConnectData | None = getattr(entry, "runtime_data", None)
    if data is None:
        return []
    if data.local is not None and data.coordinator.reached_locally(haid):
        return layout(data.local.entries(haid))
    return await _from_account(hass, data, haid)


@websocket_api.websocket_command(  # type: ignore[attr-defined]
    {
        vol.Required("type"): "homeconnect/hob_layout",
        vol.Required("device_id"): str,
    }
)
@websocket_api.async_response  # type: ignore[attr-defined]
async def _hob_layout(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Answer the card with where one hob's zones sit."""
    zones = await _for_device(hass, msg["device_id"])
    connection.send_result(msg["id"], {"zones": zones})


def register(hass: HomeAssistant) -> None:
    """Let the hob card ask where a hob's zones sit, once for the install."""
    if hass.data.get(_REGISTERED):
        return
    websocket_api.async_register_command(hass, _hob_layout)
    hass.data[_REGISTERED] = True
