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

"""The text the user is shown, and whether it is all there."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

COMPONENT = Path(__file__).parent.parent / "custom_components" / "homeconnect"
STRINGS = json.loads((COMPONENT / "strings.json").read_text())
ENGLISH = json.loads((COMPONENT / "translations" / "en.json").read_text())


def test_english_is_what_the_strings_say() -> None:
    """A translation that has drifted is text nobody sees again."""
    assert ENGLISH == STRINGS


def _steps() -> set[str]:
    return set(STRINGS["config"]["step"])


def test_every_step_the_flow_shows_has_text() -> None:
    """A step with no text is a form with a blank title and no explanation.

    A step is a method on the flow, whatever it was reached by, so the methods
    are what the text is checked against rather than the places a step id
    happens to be written down.
    """
    flow = (COMPONENT / "config_flow.py").read_text()
    # Neither of these is a step anybody is shown: one is how a discovery
    # arrives and the other only ever hands over to the menu below it.
    unshown = {"zeroconf", "reauth"}
    methods = set(re.findall(r"async def async_step_([a-z_]+)\(", flow)) - unshown
    assert methods == _steps()


def test_every_error_the_flow_reports_has_text() -> None:
    flow = (COMPONENT / "config_flow.py").read_text()
    reported = set(re.findall(r'errors\["base"\] = "([a-z_]+)"', flow))
    assert reported <= set(STRINGS["config"]["error"])


def test_every_form_field_is_named_and_explained() -> None:
    for name, step in STRINGS["config"]["step"].items():
        for field in step.get("data", {}):
            assert step["data"][field], f"{name}.{field} has no name"


def test_only_the_steps_that_send_you_to_a_browser_show_an_address() -> None:
    """A step using the placeholder without being given one is a broken form,
    and one given it without using it asks the user to open nothing."""
    for name, step in STRINGS["config"]["step"].items():
        wanted = "browser" in name
        assert ("{url}" in step["description"]) is wanted, name


def _leaves(node: Any, path: str = "") -> list[tuple[str, str]]:
    if isinstance(node, dict):
        return [
            found
            for key, child in node.items()
            for found in _leaves(child, f"{path}.{key}" if path else key)
        ]
    return [(path, node)]


def test_nothing_is_written_with_an_em_dash_or_a_double_space() -> None:
    """House style, and it is easier to keep than to go back over."""
    for where, text in _leaves(STRINGS):
        assert "—" not in text, where
        assert "--" not in text, where
        assert "  " not in text, where


# What hassfest calls a URL, copied from its own translations check. Only the
# schemes it lists count, so the private scheme the sign in ends on can be
# named in the text while an https address cannot.
URL = re.compile(
    r"(((ftp|ftps|scp|http|https|mqtt|mqtts|socket|socks5):\/\/|www\.)"
    r"[a-z0-9]+([\-\.]{1}[a-z0-9]+)*\.[a-z]{2,5}(:[0-9]{1,5})?(\/.*)?)"
)


def test_no_address_is_written_into_the_text_itself() -> None:
    """hassfest refuses one, and it does not run outside CI.

    An address belongs in a placeholder, where it can be built from whatever
    the flow actually generated rather than repeated in every language it is
    translated into.
    """
    for where, text in _leaves(STRINGS):
        assert not URL.search(text), where
