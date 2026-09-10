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

"""Reading what the cloud pushes."""

from __future__ import annotations

from custom_components.homeconnect.events import (
    RECONNECT_DELAY_UNEXPECTED,
    Event,
    _wait_from,
    parse,
)


def test_an_event_is_its_name_its_appliance_and_its_body() -> None:
    found = parse(
        [
            "event: STATUS",
            'data: {"items":[{"key":"BSH.Common.Status.DoorState",'
            '"value":"BSH.Common.EnumType.DoorState.Open"}]}',
            "id: BOSCH-HNG-1234",
        ]
    )
    assert found == Event(
        name="STATUS",
        haid="BOSCH-HNG-1234",
        data={
            "items": [
                {
                    "key": "BSH.Common.Status.DoorState",
                    "value": "BSH.Common.EnumType.DoorState.Open",
                }
            ]
        },
    )
    assert found.items[0]["key"] == "BSH.Common.Status.DoorState"


def test_a_body_given_over_several_lines_is_put_back_together() -> None:
    found = parse(["event: NOTIFY", "data: {", 'data: "items": []', "data: }"])
    assert found is not None
    assert found.data == {"items": []}


def test_the_one_optional_space_after_the_colon_is_not_part_of_the_value() -> None:
    assert parse(["event:STATUS", "id:X"]) == Event("STATUS", "X", {})


def test_an_event_with_no_name_is_not_one() -> None:
    assert parse(["data: {}"]) is None


def test_a_comment_is_not_a_field() -> None:
    """A line with nothing before the colon is the server saying hello."""
    assert parse([": ping", "event: KEEP-ALIVE"]) == Event("KEEP-ALIVE", "", {})


def test_a_body_that_is_not_json_is_dropped_rather_than_guessed_at() -> None:
    assert parse(["event: NOTIFY", "data: not json at all"]) is None


def test_an_event_with_no_body_still_happened() -> None:
    """Connected and disconnected carry nothing and mean a great deal."""
    found = parse(["event: DISCONNECTED", "id: BOSCH-X-1"])
    assert found == Event("DISCONNECTED", "BOSCH-X-1", {})
    assert found.items == []


def test_a_body_that_is_not_an_object_carries_nothing() -> None:
    found = parse(["event: NOTIFY", "data: [1, 2, 3]"])
    assert found is not None
    assert found.data == {}


def test_how_long_to_wait_when_asked() -> None:
    assert _wait_from("120") == 120.0
    # Never sooner than we would have waited anyway.
    assert _wait_from("1") == RECONNECT_DELAY_UNEXPECTED
    # Never longer than we are prepared to go without updates.
    assert _wait_from("99999") == 300.0
    # Anything unreadable, and anything not said at all.
    assert _wait_from("Wed, 21 Oct 2015 07:28:00 GMT") == RECONNECT_DELAY_UNEXPECTED
    assert _wait_from(None) == RECONNECT_DELAY_UNEXPECTED
