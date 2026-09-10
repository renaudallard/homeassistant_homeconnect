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

"""Reading a Home Connect key out loud."""

from __future__ import annotations

import pytest

from custom_components.homeconnect import names


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("BSH.Common.Setting.PowerState", "Power state"),
        ("BSH.Common.Status.OperationState", "Operation state"),
        ("Dishcare.Dishwasher.Option.SilenceOnDemand", "Silence on demand"),
        # A run of capitals is an abbreviation and survives whole.
        ("Cooking.Hood.Setting.HHCStartupSetting", "HHC startup setting"),
        (
            "BSH.Common.Status.SoftwareUpdateTransactionID",
            "Software update transaction ID",
        ),
        # An index tells one of several apart and reads better unpadded.
        ("BSH.Common.Setting.Camera.001.Enabled", "Camera 1 enabled"),
        ("Cooking.Hood.Setting.LiftCustomerHeight01", "Lift customer height 1"),
        # Written in American English, read in British.
        ("BSH.Common.Option.RemainingProgramTime", "Remaining programme time"),
        ("BSH.Common.Setting.AmbientLightColor", "Ambient light colour"),
        # The handful that would otherwise read as nonsense.
        ("BSH.Common.Status.WiFiSignalStrength", "Wi-Fi signal strength"),
        ("LaundryCare.Washer.Option.IDos1Active", "i-Dos 1"),
    ],
)
def test_readable(key: str, expected: str) -> None:
    assert names.readable(key) == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("Cooking.Oven.Program.HeatingMode.HotAir", "Hot air"),
        ("BSH.Common.EnumType.OperationState.Run", "Run"),
        ("Cooking.Oven.Program.Dish.Automatic.Conv.ClayPot", "Clay pot"),
    ],
)
def test_label(key: str, expected: str) -> None:
    """A value only has to name itself among its siblings."""
    assert names.label(key) == expected


def test_a_key_with_nothing_in_it_reads_as_itself() -> None:
    """Nothing here throws away the one thing it was given."""
    assert names.readable("Nonsense") == "Nonsense"


def test_clashing_labels_are_told_apart() -> None:
    """Two values reading the same are a list one of them cannot be picked from."""
    keys = [
        "Cooking.Oven.Program.Dish.Conv.GrillBread",
        "Cooking.Oven.Program.Dish.Steam.GrillBread",
        "Cooking.Oven.Program.Dish.Conv.Pizza",
    ]
    labelled = {key: names.label(key) for key in keys}
    settled = names.distinct(keys, labelled)
    assert len(set(settled.values())) == len(keys)
    assert settled["Cooking.Oven.Program.Dish.Conv.Pizza"] == "Pizza"
    assert "Conv" in settled["Cooking.Oven.Program.Dish.Conv.GrillBread"]
