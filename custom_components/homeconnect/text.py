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


"""Something an appliance will take words for.

A favourite is given a name, and a name is not a figure between two ends.
What the description says about one is how long it may be, so that is what
the bounds are read as here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .capability import OPTION, SETTING, TEXT
from .coordinator import HomeConnectCoordinator
from .entity import SettableEntity, follow, options, settings

# What Home Assistant allows when the appliance has not said. Its own default
# is a hundred, which is longer than anything an appliance has been seen to
# take, and a box that accepts more than the appliance will is a box that
# earns a refusal.
LONGEST = 255


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _settings, _setting_text)
    follow(entry, coordinator, add, _options, _option_text)


def _settings(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return settings(coordinator, TEXT)


def _options(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    return options(coordinator, TEXT)


class HomeConnectText(SettableEntity, TextEntity):
    """Words one appliance will take, as long as it will take them."""

    @property
    def native_min(self) -> int:
        """The shortest it will take.

        A programme narrows what its options will take, so the ends are read
        afresh rather than fixed when the entity was made.
        """
        described = self.described
        if described is None or described.minimum is None:
            return 0
        return int(described.minimum)

    @property
    def native_max(self) -> int:
        described = self.described
        if described is None or described.maximum is None:
            return LONGEST
        return int(described.maximum)

    @property
    def native_value(self) -> str | None:
        value = self.held
        return value if isinstance(value, str) else None

    async def async_set_value(self, value: str) -> None:
        await self.apply(value)


def _setting_text(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectText:
    return HomeConnectText(coordinator, haid, key, SETTING)


def _option_text(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectText:
    return HomeConnectText(coordinator, haid, key, OPTION)
