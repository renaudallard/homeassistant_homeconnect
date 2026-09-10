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

"""Reading what an appliance said about itself."""

from __future__ import annotations

from custom_components.homeconnect.capability import (
    BINARY_SENSOR,
    NUMBER,
    OPTION,
    SELECT,
    SENSOR,
    SETTING,
    STATUS,
    SWITCH,
    feature,
    is_running,
    platform_for,
    reading,
)


def described(**node: object) -> object:
    return feature(node, SETTING)


def test_a_node_with_no_key_is_not_a_feature() -> None:
    assert feature({"value": 1}, SETTING) is None


def test_a_flag_that_can_be_written_is_a_switch() -> None:
    found = feature(
        {"key": "K", "type": "Boolean", "constraints": {"access": "readWrite"}},
        SETTING,
    )
    assert found is not None
    assert platform_for(found) is SWITCH


def test_a_flag_that_cannot_be_written_is_a_reading() -> None:
    found = feature(
        {"key": "K", "type": "Boolean", "constraints": {"access": "read"}}, SETTING
    )
    assert found is not None
    assert platform_for(found) is BINARY_SENSOR


def test_a_choice_is_a_select() -> None:
    found = feature(
        {
            "key": "K",
            "constraints": {
                "allowedvalues": ["A.B.C.One", "A.B.C.Two", "A.B.C.Three"],
                "access": "readWrite",
            },
        },
        SETTING,
    )
    assert found is not None
    assert platform_for(found) is SELECT


def test_a_choice_between_on_and_off_is_a_switch() -> None:
    """Two values, one of them on, is a switch however the appliance writes it."""
    found = feature(
        {
            "key": "BSH.Common.Setting.PowerState",
            "constraints": {
                "allowedvalues": [
                    "BSH.Common.EnumType.PowerState.On",
                    "BSH.Common.EnumType.PowerState.Standby",
                ],
                "access": "readWrite",
            },
        },
        SETTING,
    )
    assert found is not None
    assert found.switchable
    assert platform_for(found) is SWITCH
    assert found.on_value() == "BSH.Common.EnumType.PowerState.On"
    assert found.off_value() == "BSH.Common.EnumType.PowerState.Standby"


def test_standby_as_well_as_off_is_a_choice_of_three() -> None:
    found = feature(
        {
            "key": "BSH.Common.Setting.PowerState",
            "constraints": {
                "allowedvalues": [
                    "BSH.Common.EnumType.PowerState.On",
                    "BSH.Common.EnumType.PowerState.Off",
                    "BSH.Common.EnumType.PowerState.Standby",
                ],
                "access": "readWrite",
            },
        },
        SETTING,
    )
    assert found is not None
    assert not found.switchable
    assert platform_for(found) is SELECT


def test_a_range_is_a_number() -> None:
    found = feature(
        {
            "key": "K",
            "unit": "°C",
            "constraints": {
                "min": 30,
                "max": 90,
                "stepsize": 10,
                "access": "readWrite",
            },
        },
        SETTING,
    )
    assert found is not None
    assert platform_for(found) is NUMBER
    assert (found.minimum, found.maximum, found.step) == (30.0, 90.0, 10.0)


def test_something_writable_and_undescribed_is_only_a_reading() -> None:
    """An entity that cannot know what it may send only ever earns a refusal."""
    found = feature({"key": "K", "constraints": {"access": "readWrite"}}, SETTING)
    assert found is not None
    assert platform_for(found) is SENSOR


def test_a_status_is_never_writable_even_unasked() -> None:
    found = feature({"key": "K", "value": "x"}, STATUS)
    assert found is not None
    assert not found.writable


def test_values_the_cloud_named_are_matched_up_by_position() -> None:
    found = feature(
        {
            "key": "K",
            "constraints": {
                "allowedvalues": ["A.B.C.GC40", "A.B.C.GC60"],
                "displayvalues": ["40 °C", "60 °C"],
                "access": "readWrite",
            },
        },
        OPTION,
    )
    assert found is not None
    assert found.shown == {"A.B.C.GC40": "40 °C", "A.B.C.GC60": "60 °C"}


def test_names_of_the_wrong_length_are_left_alone() -> None:
    """Nothing can be matched against a list that does not line up."""
    found = feature(
        {
            "key": "K",
            "constraints": {
                "allowedvalues": ["A.B.C.One", "A.B.C.Two"],
                "displayvalues": ["One"],
                "access": "readWrite",
            },
        },
        OPTION,
    )
    assert found is not None
    assert found.shown is None


def test_an_option_that_only_goes_in_at_the_start_says_so() -> None:
    found = feature(
        {
            "key": "BSH.Common.Option.StartInRelative",
            "constraints": {"min": 0, "max": 86400, "execution": "startonly"},
        },
        OPTION,
    )
    assert found is not None
    assert found.start_only


def test_a_reading_carries_what_the_cloud_calls_it() -> None:
    found = reading(
        {"key": "K", "value": "A.B.C.Run", "displayvalue": "Running", "unit": "seconds"}
    )
    assert (found.value, found.shown, found.unit) == ("A.B.C.Run", "Running", "seconds")


def test_running_is_read_off_the_end_of_the_state() -> None:
    assert is_running("BSH.Common.EnumType.OperationState.Run")
    assert not is_running("BSH.Common.EnumType.OperationState.Ready")
    assert not is_running(None)
