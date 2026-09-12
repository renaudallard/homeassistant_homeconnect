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

"""Lamps in and on an appliance.

An appliance describes a lamp as two or three separate settings: whether it is
on, how bright, and for the decorative sort what colour. Left alone those
become three unrelated controls for one thing, so they are gathered here into
the one light they are, and the platforms that would otherwise have made the
three leave them alone.

Brightness is a percentage between whatever two ends the appliance named. A
hood will not go below a tenth and a fridge will, so the ends come from the
appliance rather than from here.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGB_COLOR,
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import brightness_to_value, value_to_brightness

from .capability import LAMPS, Feature, Lamp
from .coordinator import HomeConnectCoordinator
from .entity import HomeConnectEntity, follow
from .errors import HomeConnectError

# What a colour looks like written down, as in #4a88f8.
HEX = 6


def _rgb(written: Any) -> tuple[int, int, int] | None:
    """A colour out of what the appliance wrote, if it wrote one."""
    if not isinstance(written, str):
        return None
    digits = written.lstrip("#")
    if len(digits) != HEX:
        return None
    try:
        return (
            int(digits[0:2], 16),
            int(digits[2:4], 16),
            int(digits[4:6], 16),
        )
    except ValueError:
        return None


def _written(colour: tuple[int, int, int]) -> str:
    """A colour in the shape the appliance writes them."""
    return "#{:02x}{:02x}{:02x}".format(*colour)


async def async_setup_entry(
    hass: HomeAssistant, entry: Any, add: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data.coordinator
    follow(entry, coordinator, add, _lamps, _light)


def _lamps(coordinator: HomeConnectCoordinator) -> Iterator[tuple[str, str]]:
    """Every lamp an appliance has, being every lamp it has the switch for."""
    for haid, appliance in coordinator.data.items():
        for lamp in LAMPS:
            if lamp.on in appliance.model.settings:
                yield haid, lamp.on


class HomeConnectLight(HomeConnectEntity, LightEntity):
    """One lamp, however many settings the appliance keeps it in."""

    def __init__(
        self, coordinator: HomeConnectCoordinator, haid: str, lamp: Lamp
    ) -> None:
        super().__init__(coordinator, haid)
        self._lamp = lamp
        self._attr_unique_id = f"{haid}-{lamp.on}"
        self._attr_translation_key = lamp.translation_key
        described = coordinator.data[haid].model.settings
        self._dims = lamp.brightness is not None and lamp.brightness in described
        self._colours = lamp.colour is not None and lamp.colour in described
        mode = (
            ColorMode.RGB
            if self._colours
            else ColorMode.BRIGHTNESS
            if self._dims
            else ColorMode.ONOFF
        )
        self._attr_color_mode = mode
        self._attr_supported_color_modes = {mode}

    def _described(self, key: str | None) -> Feature | None:
        appliance = self.appliance
        if appliance is None or key is None:
            return None
        return appliance.model.settings.get(key)

    def _value(self, key: str | None) -> Any:
        appliance = self.appliance
        if appliance is None or key is None:
            return None
        found = appliance.settings.get(key)
        return None if found is None else found.value

    @property
    def _range(self) -> tuple[float, float]:
        """How dim and how bright this lamp goes, as the appliance said.

        An appliance that describes the setting without saying is taken to
        mean the whole of a percentage, that being what it is measured in.
        """
        described = self._described(self._lamp.brightness)
        if described is None or described.maximum is None:
            return (1.0, 100.0)
        return (described.minimum or 1.0, described.maximum)

    @property
    def is_on(self) -> bool | None:
        value = self._value(self._lamp.on)
        return None if value is None else bool(value)

    @property
    def brightness(self) -> int | None:
        if not self._dims:
            return None
        value = self._value(self._lamp.brightness)
        if not isinstance(value, (int, float)):
            return None
        return value_to_brightness(self._range, float(value))

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        if not self._colours:
            return None
        return _rgb(self._value(self._lamp.colour))

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Switch the lamp on, and set whatever else was asked for.

        The colour goes first, because an appliance that keeps a palette of
        its own will not take a colour until it has been told to expect one,
        and the switch goes last so that nothing is changed under a lamp that
        turns out not to take it.
        """
        colour = kwargs.get(ATTR_RGB_COLOR)
        if colour is not None and self._colours:
            await self._set(self._lamp.palette, self._lamp.custom)
            await self._set(self._lamp.colour, _written(colour))
        brightness = kwargs.get(ATTR_BRIGHTNESS)
        if brightness is not None and self._dims:
            # Kept at or above the dimmest the appliance allows: the scale Home
            # Assistant rounds by can land a notch under the stated minimum,
            # which the appliance refuses.
            span = self._range
            await self._set(
                self._lamp.brightness,
                max(round(span[0]), round(brightness_to_value(span, brightness))),
            )
        await self._set(self._lamp.on, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(self._lamp.on, False)

    async def _set(self, key: str | None, value: Any) -> None:
        """Change one of the settings this lamp is kept in.

        A lamp with no palette skips that step rather than making one up, so
        the setting that is not there is not written.
        """
        if key is None or self._described(key) is None:
            return
        try:
            await self.coordinator.apply_setting(self._haid, key, value)
        except HomeConnectError as err:
            raise HomeAssistantError(str(err)) from err


def _light(
    coordinator: HomeConnectCoordinator, haid: str, key: str
) -> HomeConnectLight:
    lamp = next(one for one in LAMPS if one.on == key)
    return HomeConnectLight(coordinator, haid, lamp)
