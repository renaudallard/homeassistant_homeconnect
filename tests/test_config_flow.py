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
from homeassistant.const import CONF_CODE
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.const import (
    API_HOST,
    CONF_ACCESS_TOKEN,
    CONF_REFRESH_TOKEN,
    CONF_TRANSPORT,
    DOMAIN,
    TOKEN_PATH,
)

from .common import API, entry, fixture, serve, set_up

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
    """Start a flow, which asks for the pasted address straight away."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


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
    shown = await made.start_reauth_flow(hass)
    assert shown["step_id"] == "reauth_confirm"

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
    assert shown["type"] is FlowResultType.FORM
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


async def test_a_kitchen_of_appliances_puts_up_one_card(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """One sign in covers the account, so the second appliance to shout has
    nothing to add to the card already waiting to be clicked."""
    oven = replace(
        HOB,
        name="Oven SIEMENS HB678GBS6B._homeconnect._tcp.local.",
        properties={**HOB.properties, "type": "Oven", "vib": "HB678GBS6B"},
    )
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=HOB
    )
    assert first["type"] is FlowResultType.FORM

    second = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=oven
    )
    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_in_progress"
    assert len(hass.config_entries.flow.async_progress()) == 1


async def test_which_way_to_reach_them_is_asked_at_setup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    shown = await browser_step(hass)
    assert CONF_TRANSPORT in str(shown["data_schema"].schema)

    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    made = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown), CONF_TRANSPORT: "cloud"}
    )
    assert made["data"][CONF_TRANSPORT] == "cloud"


async def test_the_cloud_is_what_it_falls_back_to(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """It is the way that works without the appliances being reachable."""
    shown = await browser_step(hass)
    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    made = await hass.config_entries.flow.async_configure(
        shown["flow_id"], {CONF_CODE: answer(shown)}
    )
    assert made["data"][CONF_TRANSPORT] == "cloud"


async def test_reconfiguring_moves_an_entry_between_the_two(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The account is the same and its tokens still work, so nothing has to
    be signed in to again."""
    made = await set_up(hass, aioclient_mock, "washer")
    shown = await made.start_reconfigure_flow(hass)
    assert shown["step_id"] == "reconfigure"

    with patch("custom_components.homeconnect.LocalControl"):
        again = await hass.config_entries.flow.async_configure(
            shown["flow_id"], {CONF_TRANSPORT: "local"}
        )
        await hass.async_block_till_done()
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "reconfigure_successful"
    assert made.data[CONF_TRANSPORT] == "local"
    # The sign in is untouched by it.
    assert made.data[CONF_ACCESS_TOKEN] == "an-access-token"


async def test_signing_in_again_leaves_the_way_in_alone(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A reauth is about the tokens. Asking about anything else there would
    quietly move an entry somebody had deliberately set the other way."""
    made = entry(hass)
    hass.config_entries.async_update_entry(
        made, data={**made.data, CONF_TRANSPORT: "local"}
    )
    shown = await made.start_reauth_flow(hass)
    assert CONF_TRANSPORT not in str(shown["data_schema"].schema)

    pair(aioclient_mock)
    serve(aioclient_mock, [fixture("washer")])
    with patch("custom_components.homeconnect.LocalControl"):
        await hass.config_entries.flow.async_configure(
            shown["flow_id"], {CONF_CODE: answer(shown)}
        )
        await hass.async_block_till_done()
    assert made.data[CONF_TRANSPORT] == "local"
