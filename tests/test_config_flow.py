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

"""Signing in through the flow."""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Mapping
from dataclasses import replace
from ipaddress import ip_address
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from homeassistant import config_entries
from homeassistant.const import CONF_CODE, CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.const import (
    API_HOST,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    TOKEN_PATH,
)
from custom_components.homeconnect.errors import HomeConnectAuthError

from .common import API, entry, fixture, serve

TOKEN_URL = f"{API_HOST}{TOKEN_PATH}"


def answer(shown: Mapping[str, Any]) -> str:
    """The address a browser would come back on, for the sign in just shown."""
    placeholders = shown["description_placeholders"]
    assert placeholders is not None
    state = parse_qs(urlparse(placeholders["url"]).query)["state"]
    return f"https://qr.home-connect.com/authorize/prod/?code=a-code&state={state[0]}"


def pair(mock: AiohttpClientMocker, **extra: Any) -> None:
    mock.post(
        TOKEN_URL,
        json={
            "access_token": "an-access-token",
            "refresh_token": "a-refresh-token",
            "expires_in": 3600,
            **extra,
        },
    )


async def browser_step(hass: HomeAssistant) -> Any:
    """Start a flow and take the browser branch off the menu."""
    menu = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert menu["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "browser"}
    )


async def test_the_flow_offers_both_ways_in(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One account has a password, another has a passkey, and nothing says
    which in advance."""
    menu = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert menu["type"] is FlowResultType.MENU
    assert "password" in menu["menu_options"]
    assert "browser" in menu["menu_options"]


async def test_signing_in_makes_an_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await browser_step(hass)
    assert shown["type"] is FlowResultType.FORM
    placeholders = shown["description_placeholders"]
    assert placeholders is not None
    assert placeholders["url"].startswith(API_HOST)

    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    made = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert made["type"] is FlowResultType.CREATE_ENTRY
    assert made["title"] == "Home Connect"
    assert made["data"][CONF_ACCESS_TOKEN] == "an-access-token"
    assert made["data"][CONF_REFRESH_TOKEN] == "a-refresh-token"


async def test_an_address_from_a_different_sign_in_is_refused(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The state goes out with the request and comes back untouched."""
    shown = await browser_step(hass)
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"],
        {CONF_CODE: "https://qr.home-connect.com/x?code=a-code&state=somebody-else"},
    )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "invalid_auth"}


async def test_a_stale_code_says_to_sign_in_again(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await browser_step(hass)
    aioclient_mock.post(TOKEN_URL, status=400, json={"error": "invalid_grant"})
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "invalid_auth"}


async def test_a_cloud_that_will_not_answer_is_told_apart_from_a_refusal(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await browser_step(hass)
    aioclient_mock.post(TOKEN_URL, status=503, json={})
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert again["errors"] == {"base": "cannot_connect"}


async def test_tokens_that_will_not_read_an_account_are_not_written_down(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A pair the cloud hands out and then refuses makes an entry that fails
    on every start with nothing to say about why."""
    shown = await browser_step(hass)
    pair(aioclient_mock)
    aioclient_mock.get(f"{API}/homeappliances", status=403, json={})
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "invalid_auth"}


async def test_the_same_account_twice_is_one_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    claims = base64.urlsafe_b64encode(
        json.dumps({"sub": "account-under-test"}).encode()
    )
    entry(hass)
    shown = await browser_step(hass)
    pair(aioclient_mock, id_token=f"h.{claims.decode().rstrip('=')}.s")
    serve(aioclient_mock, [fixture("washer")])
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"


async def test_signing_in_again_hands_the_new_pair_to_the_entry_there(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    made = entry(hass)
    menu = await made.start_reauth_flow(hass)
    assert menu["type"] is FlowResultType.MENU
    assert "reauth_password" in menu["menu_options"]
    assert "reauth_browser" in menu["menu_options"]
    shown = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "reauth_browser"}
    )

    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    again = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    await hass.async_block_till_done()
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "reauth_successful"
    assert made.data[CONF_ACCESS_TOKEN] == "an-access-token"
    assert made.data["expires_at"] > time.time()


HOB = ZeroconfServiceInfo(
    ip_address=ip_address("172.20.0.209"),
    ip_addresses=[ip_address("172.20.0.209")],
    port=80,
    hostname="Hob-SIEMENS-EX651HEC1E.local.",
    type="_homeconnect._tcp.local.",
    name="Hob SIEMENS EX651HEC1E._homeconnect._tcp.local.",
    properties={
        "txtvers": "1",
        "type": "Hob",
        "brand": "SIEMENS",
        "vib": "EX651HEC1E",
        "mac": "94277084 7DCD",
    },
)


async def test_an_appliance_on_the_network_offers_the_sign_in(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Discovery says an appliance is there. The account is still what
    authorises talking to it, so it leads to the same sign in."""
    shown = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=HOB
    )
    assert shown["type"] is FlowResultType.MENU
    assert shown["step_id"] == "user"


async def test_the_discovery_card_names_the_appliance(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=HOB
    )
    (flow,) = hass.config_entries.flow.async_progress()
    assert flow["context"]["title_placeholders"] == {"name": "SIEMENS Hob EX651HEC1E"}


async def test_a_second_appliance_has_nothing_to_add(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One entry covers every appliance on the account."""
    entry(hass)
    again = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=HOB
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"


async def test_an_appliance_that_says_little_is_still_named(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Nothing is invented for a record that leaves the details out."""
    quiet = replace(HOB, properties={"txtvers": "1"})
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=quiet
    )
    (flow,) = hass.config_entries.flow.async_progress()
    assert flow["context"]["title_placeholders"] == {"name": "Hob SIEMENS EX651HEC1E"}


async def password_step(hass: HomeAssistant) -> Any:
    """Start a flow and take the password branch off the menu."""
    menu = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "password"}
    )


async def test_signing_in_with_a_password_needs_no_browser(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await password_step(hass)
    assert shown["type"] is FlowResultType.FORM
    assert shown["step_id"] == "password"
    # Nothing to open, so nothing to show an address for.
    assert not (shown["description_placeholders"] or {})

    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    with patch(
        "custom_components.homeconnect.config_flow.singlekey.sign_in",
        return_value="a-code",
    ) as walked:
        made = await hass.config_entries.flow.async_configure(
            shown["flow_id"],
            {CONF_EMAIL: "someone@example.invalid", CONF_PASSWORD: "hunter2"},
        )
    assert made["type"] is FlowResultType.CREATE_ENTRY
    assert made["data"][CONF_ACCESS_TOKEN] == "an-access-token"
    # The address is kept so that signing in again knows whose account it is.
    assert made["data"][CONF_EMAIL] == "someone@example.invalid"
    # The password is not.
    assert CONF_PASSWORD not in made["data"]
    assert walked.call_args.args[1:3] == ("someone@example.invalid", "hunter2")


async def test_a_password_the_account_refuses_stays_on_the_form(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await password_step(hass)
    with patch(
        "custom_components.homeconnect.config_flow.singlekey.sign_in",
        side_effect=HomeConnectAuthError("the account would not accept that password"),
    ):
        again = await hass.config_entries.flow.async_configure(
            shown["flow_id"],
            {CONF_EMAIL: "someone@example.invalid", CONF_PASSWORD: "wrong"},
        )
    assert again["type"] is FlowResultType.FORM
    assert again["errors"] == {"base": "invalid_auth"}


async def test_signing_in_again_with_a_password_offers_the_same_address(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The entry remembers whose account it is, so nobody retypes it."""
    made = entry(hass, email="someone@example.invalid")
    menu = await made.start_reauth_flow(hass)
    shown = await hass.config_entries.flow.async_configure(
        menu["flow_id"], {"next_step_id": "reauth_password"}
    )
    assert shown["step_id"] == "reauth_password"
    schema = shown["data_schema"]
    assert schema is not None
    suggested = {
        str(key): (key.description or {}).get("suggested_value")
        for key in schema.schema
    }
    assert suggested[CONF_EMAIL] == "someone@example.invalid"
    # Nothing is suggested for the password, which is not ours to remember.
    assert suggested[CONF_PASSWORD] is None
