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

"""What to hand over when something is wrong.

People paste this into bug reports, so it carries what is worth knowing and
nothing that says who anyone is. The same redaction the logs use covers it:
the tokens, and the serial number that names one particular machine.

What it does carry is the whole of what an appliance said about itself, which
is the one thing a report about a model nobody here has cannot do without.

There are two of these. The account is what the integration entry offers and
carries every appliance on it. One appliance is what its own device page
offers, and is the one to ask for: a report is nearly always about one
machine, and a household of them makes the other four times the size for no
gain.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from . import HomeConnectConfigEntry
from .capability import Feature, platform_for
from .const import DOMAIN
from .coordinator import Appliance
from .entity import serial_of
from .http import redact


def _described(features: dict[str, Feature]) -> list[dict[str, Any]]:
    """What the appliance said each of these will take, and what it became."""
    return [
        {**asdict(found), "values": list(found.values), "becomes": platform_for(found)}
        for found in features.values()
    ]


def _readings(readings: dict[str, Any]) -> dict[str, Any]:
    """What each of these is holding, and what the cloud calls that."""
    return {
        key: {"value": found.value, "shown": found.shown, "unit": found.unit}
        for key, found in readings.items()
    }


def _appliance(appliance: Appliance) -> dict[str, Any]:
    """Everything worth knowing about one machine."""
    serial = serial_of(appliance.id)
    return {
        "type": appliance.type,
        "brand": appliance.brand,
        "model": appliance.vib,
        "number": appliance.enumber,
        # The serial is the only part of the identifier that names one
        # household's machine, and the shape of the identifier is worth
        # keeping even so.
        "id": appliance.id.replace(serial, "<serial hidden>") if serial else "hidden",
        "connected": appliance.connected,
        "status": _readings(appliance.status),
        "settings": _readings(appliance.settings),
        "events": _readings(appliance.events),
        "options": _readings(appliance.options),
        "pending": appliance.pending,
        "programs": list(appliance.programs),
        "active": appliance.active,
        "selected": appliance.selected,
        "describes": {
            "settings": _described(appliance.model.settings),
            "commands": list(appliance.model.commands),
            "options": {
                program: _described(options)
                for program, options in appliance.model.options.items()
            },
        },
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HomeConnectConfigEntry
) -> dict[str, Any]:
    """Everything on the account."""
    coordinator = entry.runtime_data.coordinator
    interval = coordinator.update_interval
    return {
        "entry": redact(dict(entry.data)),
        # How often the account is being asked, which says whether the stream
        # is carrying the changes or the poll is.
        "polling_seconds": interval.total_seconds() if interval else None,
        "appliances": [
            _appliance(appliance) for appliance in coordinator.data.values()
        ],
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: HomeConnectConfigEntry, device: dr.DeviceEntry
) -> dict[str, Any]:
    """One appliance, being the one whose page this was asked from."""
    coordinator = entry.runtime_data.coordinator
    wanted = [
        identifier for domain, identifier in device.identifiers if domain == DOMAIN
    ]
    return {
        "entry": redact(dict(entry.data)),
        "appliances": [
            _appliance(appliance)
            for haid, appliance in coordinator.data.items()
            if haid in wanted
        ],
    }
