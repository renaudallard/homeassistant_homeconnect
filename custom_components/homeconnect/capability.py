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

"""What an appliance says about itself, and what it becomes in Home Assistant.

Every appliance describes itself the same way. A key names one thing, and
beside it come the type it holds, whether it can be written, and either the
values it will take or the range it will take them in. That is enough to
decide what kind of entity it should be, so nothing here is specific to a
model of oven or to a make of washing machine.

Three lists arrive in that shape and are read the same way: what the appliance
reports about itself, what can be set on it, and what the programme it is
running can be adjusted by. Where a thing came from decides only how it is
sent back, which is the caller's business rather than this module's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .content import OBJECT, STRING

# What a key becomes. These are Home Assistant platform names, kept as plain
# strings so this module does not need Home Assistant to be tested.
SENSOR = "sensor"
BINARY_SENSOR = "binary_sensor"
SWITCH = "switch"
SELECT = "select"
NUMBER = "number"
TEXT = "text"

# Which of the three lists a key came out of, which is what says how to write
# it back: a setting goes to the appliance, an option goes to the programme.
SETTING = "setting"
STATUS = "status"
OPTION = "option"

# What the cloud calls a value that is true or false. Everything else is
# either a number or one of a named set.
BOOLEAN = "Boolean"

# What a thing is carried as when it is not a figure at all. Bounds on one of
# these are how long it may be, or how many things are in it.
NOT_A_FIGURE = frozenset({STRING, OBJECT})

# When an option can be given. One that can only be given as a programme
# starts is not refused the rest of the time, it is silently ignored, so it is
# held back and sent along with the start instead.
START_ONLY = "startonly"

# The leaf of an enumerated value that means the appliance is running.
RUN = "Run"

# Leaves of the power setting. Standby is how an appliance that cannot be
# switched off from outside says it is off, so as far as anything here is
# concerned the two mean the same thing.
ON = "On"
OFF = frozenset({"Off", "Standby"})


def leaf(key: str) -> str:
    """The last part of a key, which is what one value is called."""
    return key.rsplit(".", 1)[-1]


def happening(value: Any) -> bool:
    """Whether an event's value says it is happening now.

    An event is named by a present state, or now and then given as a plain
    flag. The one value that means it has stopped is Off; one that is present,
    or present and acknowledged at the appliance, is still happening.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return leaf(str(value)) != "Off"


def number(value: Any) -> float | None:
    """A figure, if that is what it is. A flag is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class Reading:
    """What one thing is holding at the moment.

    The cloud gives three things about every value it reports: the value, what
    it calls that value in the user's own language, and what it is measured
    in. The middle one is the only readable form of an enumerated value that
    comes from anywhere but guesswork, so it travels with the value rather
    than being looked up again later.
    """

    value: Any = None
    shown: str | None = None
    unit: str | None = None


def reading(node: Mapping[str, Any]) -> Reading:
    """What the cloud said one thing is holding."""
    shown = node.get("displayvalue")
    unit = node.get("unit")
    return Reading(
        value=node.get("value"),
        shown=str(shown) if isinstance(shown, str) and shown else None,
        unit=str(unit) if unit else None,
    )


@dataclass(frozen=True)
class Feature:
    """One thing an appliance has, as the appliance describes it."""

    key: str
    kind: str
    value: Any = None
    unit: str | None = None
    type: str = ""
    access: str = "read"
    # The values it will take, and what the cloud calls each of them. The
    # cloud translates those names and this does not, so they are worth
    # keeping even though a name can be worked out from the key.
    values: tuple[str, ...] = ()
    shown: Mapping[str, str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    default: Any = None
    execution: str | None = None

    @property
    def writable(self) -> bool:
        return "write" in self.access.lower()

    @property
    def boolean(self) -> bool:
        """Whether it holds a flag.

        An appliance that does not say what type a thing is has still said
        what it currently holds, and a thing holding true or false is a flag
        whatever it calls itself.
        """
        return self.type == BOOLEAN or isinstance(self.value, bool)

    @property
    def textual(self) -> bool:
        """Whether it holds words.

        An appliance carries a name, a clock reading and a colour all as
        words, so this says how the thing travels rather than what it means.
        Anything it will take is something that can be typed.
        """
        return self.type == STRING

    @property
    def numeric(self) -> bool:
        """Whether it holds a figure within a range it named.

        Something holding words has bounds too, and they say how long it may
        be rather than how large. A favourite's name is written that way, and
        read as a range it becomes a slider that sets a name to a number.
        """
        if self.type in NOT_A_FIGURE:
            return False
        return self.minimum is not None and self.maximum is not None

    @property
    def start_only(self) -> bool:
        """Whether it can only be given as the programme starts."""
        return self.execution == START_ONLY

    @property
    def switchable(self) -> bool:
        """Whether the choice it offers is really just on and off.

        A power setting offering nothing but on and off is a switch, and one
        that also offers standby is a choice of three. The test is on the
        values themselves rather than on which key they belong to, so any
        other setting written the same way is treated the same way.
        """
        if len(self.values) != 2:
            return False
        leaves = {leaf(value) for value in self.values}
        return ON in leaves and bool(leaves & OFF)

    def on_value(self) -> str | None:
        """Which of two values means on, for the ones that work that way."""
        for value in self.values:
            if leaf(value) == ON:
                return value
        return None

    def off_value(self) -> str | None:
        """Which of two values means off, for the ones that work that way."""
        for value in self.values:
            if leaf(value) in OFF:
                return value
        return None


def _labels(node: Mapping[str, Any], values: tuple[str, ...]) -> dict[str, str]:
    """What the cloud calls each value it offers.

    The names arrive as a list beside the values and are matched up by
    position. A list of the wrong length is a list nothing can be matched
    against, so it is left alone rather than guessed at.
    """
    shown = node.get("displayvalues")
    if not isinstance(shown, list) or len(shown) != len(values):
        return {}
    return {
        value: str(text)
        for value, text in zip(values, shown, strict=True)
        if isinstance(text, str) and text
    }


def feature(node: Mapping[str, Any], kind: str) -> Feature | None:
    """One feature out of what the cloud said about it.

    Anything without a key is not a feature; the cloud has never sent one, but
    a list is read as it arrives rather than as it is meant to arrive.
    """
    key = node.get("key")
    if not isinstance(key, str) or not key:
        return None
    limits = node.get("constraints")
    limits = limits if isinstance(limits, Mapping) else {}
    allowed = limits.get("allowedvalues")
    values = tuple(str(value) for value in allowed) if isinstance(allowed, list) else ()
    # A status is never writable and does not always bother to say so.
    access = str(limits.get("access") or ("read" if kind == STATUS else "readWrite"))
    return Feature(
        key=key,
        kind=kind,
        value=node.get("value"),
        unit=str(node["unit"]) if node.get("unit") else None,
        type=str(node.get("type") or ""),
        access=access,
        values=values,
        shown=_labels(limits, values) or None,
        minimum=number(limits.get("min")),
        maximum=number(limits.get("max")),
        step=number(limits.get("stepsize")),
        default=limits.get("default"),
        execution=str(limits["execution"]) if limits.get("execution") else None,
    )


def platform_for(found: Feature) -> str | None:
    """What kind of entity a feature becomes, or nothing if it becomes none.

    A feature that can be written becomes something that can be set, and only
    if the appliance said enough about it to set it safely: a flag, a choice
    between named values, or a figure between two ends. One that says it can
    be written and then describes nothing at all is left as a reading, since
    an entity that cannot know what it would be allowed to send is an entity
    that only ever earns a refusal.
    """
    if found.writable:
        if found.boolean or found.switchable:
            return SWITCH
        if found.values:
            return SELECT
        if found.numeric:
            return NUMBER
        if found.textual:
            return TEXT
    if found.boolean:
        return BINARY_SENSOR
    return SENSOR


def is_running(state: Any) -> bool:
    """Whether an operation state says the appliance is working."""
    return isinstance(state, str) and leaf(state) == RUN


@dataclass(frozen=True)
class Lamp:
    """Settings that between them are one lamp.

    An appliance describes a lamp as separate settings: one for whether it is
    on, one for how bright, and for the decorative sort one for what colour.
    They are one thing to look at and one thing to work, so they are gathered
    into one light rather than left as three unrelated controls.
    """

    on: str
    translation_key: str
    brightness: str | None = None
    # What colour it is set to, which has to say custom before a colour of
    # one's own will be taken.
    palette: str | None = None
    colour: str | None = None
    # What the palette calls a colour that is not one of its own.
    custom: str = "BSH.Common.EnumType.AmbientLightColor.CustomColor"


LAMPS: tuple[Lamp, ...] = (
    Lamp(
        on="Cooking.Common.Setting.Lighting",
        translation_key="light",
        brightness="Cooking.Common.Setting.LightingBrightness",
    ),
    Lamp(
        on="BSH.Common.Setting.AmbientLightEnabled",
        translation_key="ambient_light",
        brightness="BSH.Common.Setting.AmbientLightBrightness",
        palette="BSH.Common.Setting.AmbientLightColor",
        colour="BSH.Common.Setting.AmbientLightCustomColor",
    ),
    Lamp(
        on="Refrigeration.Common.Setting.Light.Internal.Power",
        translation_key="interior_light",
        brightness="Refrigeration.Common.Setting.Light.Internal.Brightness",
    ),
    Lamp(
        on="Refrigeration.Common.Setting.Light.External.Power",
        translation_key="exterior_light",
        brightness="Refrigeration.Common.Setting.Light.External.Brightness",
    ),
)

# Every key that is part of a lamp, so that the platforms which would
# otherwise make three controls out of one lamp can leave them alone.
GATHERED = frozenset(
    key
    for lamp in LAMPS
    for key in (lamp.on, lamp.brightness, lamp.palette, lamp.colour)
    if key
)
