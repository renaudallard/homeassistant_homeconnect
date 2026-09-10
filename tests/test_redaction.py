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

"""What goes in a log, and what does not."""

from __future__ import annotations

from custom_components.homeconnect.http import failure, redact, redact_url


def test_a_token_is_replaced_by_a_note_of_its_length() -> None:
    hidden = redact({"access_token": "abcdefgh", "expires_in": 3600})
    assert hidden == {"access_token": "<8 chars hidden>", "expires_in": 3600}


def test_secrets_are_hidden_however_deep_they_are() -> None:
    hidden = redact({"a": [{"refresh_token": "xy"}], "b": {"code": "zz"}})
    assert hidden == {
        "a": [{"refresh_token": "<2 chars hidden>"}],
        "b": {"code": "<2 chars hidden>"},
    }


def test_nothing_is_not_a_secret() -> None:
    """An empty field stays empty, since hiding it would say it was there."""
    assert redact({"access_token": None, "code": ""}) == {
        "access_token": None,
        "code": "",
    }


def test_a_reading_is_not_a_secret() -> None:
    assert redact({"value": "BSH.Common.EnumType.DoorState.Open"}) == {
        "value": "BSH.Common.EnumType.DoorState.Open"
    }


def test_only_the_serial_is_taken_out_of_an_address() -> None:
    """The brand and the model are what a bug report is about."""
    hidden = redact_url(
        "https://api.home-connect.com/api/homeappliances/"
        "BOSCH-HNG6764B6-0000000011FF/programs/active"
    )
    assert "BOSCH-HNG6764B6-" in hidden
    assert "0000000011FF" not in hidden


def test_an_address_with_no_appliance_in_it_is_left_alone() -> None:
    assert redact_url(f"{'https://api.home-connect.com'}/api/homeappliances") == (
        "https://api.home-connect.com/api/homeappliances"
    )


def test_a_refusal_is_read_for_its_key_and_its_reason() -> None:
    assert failure(
        {"error": {"key": "SDK.Error.WrongOperationState", "description": "not now"}}
    ) == ("SDK.Error.WrongOperationState", "not now")


def test_a_refusal_shaped_some_other_way_still_says_something() -> None:
    key, described = failure({"oops": True})
    assert key is None
    assert "oops" in described
    assert failure(None) == (None, "no body")
