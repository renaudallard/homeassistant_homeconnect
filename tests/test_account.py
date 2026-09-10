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

"""The account's own service, which is where the keys for local control are.

It is a different host from the appliance API, in a different shape, and it
is asked once per appliance and then left alone.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.api import HomeConnectAccount, HomeConnectApi
from custom_components.homeconnect.auth import Tokens
from custom_components.homeconnect.errors import HomeConnectAuthError

EU = "https://eu.services.home-connect.com"
NA = "https://na.services.home-connect.com"
WHOSE = "an-account-id"
PAIRED = f"/api/account/v2/accounts/{WHOSE}/paired-appliances"

APPLIANCES = {
    "data": {
        "pairedAppliances": [
            {
                "haId": "SIEMENS-EX651HEC1E-ABC",
                "type": "Hob",
                "tls": {"key": "a-shared-key"},
            },
            {
                "haId": "BOSCH-OLD-DEF",
                "type": "Dishwasher",
                "aes": {"key": "another-key", "iv": "a-vector"},
            },
        ]
    }
}


@pytest.fixture
async def session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[aiohttp.ClientSession]:
    made = aioclient_mock.create_session(hass.loop)
    yield made
    await made.close()


def api_for(session: aiohttp.ClientSession) -> HomeConnectApi:
    return HomeConnectApi(session, Tokens("a-token", "b", 9e9), "en-GB")


async def test_the_keys_hang_off_the_account_that_owns_them(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(f"{EU}{PAIRED}", json=APPLIANCES)
    account = HomeConnectAccount(api_for(session), WHOSE)
    assert await account.keys() == {
        "SIEMENS-EX651HEC1E-ABC": {"key": "a-shared-key"},
        "BOSCH-OLD-DEF": {"key": "another-key", "iv": "a-vector"},
    }


async def test_an_appliance_with_no_key_is_simply_absent(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(
        f"{EU}{PAIRED}",
        json={"data": {"pairedAppliances": [{"haId": "X", "type": "Y"}]}},
    )
    account = HomeConnectAccount(api_for(session), WHOSE)
    assert await account.keys() == {}


async def test_the_account_is_asked_for_when_it_is_not_already_known(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """Signing in usually says which account this is. Where it has not, the
    service is asked, and the answer is kept rather than asked for twice."""
    aioclient_mock.get(f"{EU}/api/account/v1/accounts", json={"data": {"hcId": WHOSE}})
    aioclient_mock.get(f"{EU}{PAIRED}", json=APPLIANCES)
    account = HomeConnectAccount(api_for(session))
    assert len(await account.keys()) == 2
    assert len(await account.keys()) == 2
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert asked.count(f"{EU}/api/account/v1/accounts") == 1


async def test_the_other_region_is_tried_when_the_first_will_not_answer(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """An account belongs to one of two and the other has never heard of it."""
    aioclient_mock.get(f"{EU}{PAIRED}", status=404, json={})
    aioclient_mock.get(f"{NA}{PAIRED}", json=APPLIANCES)
    account = HomeConnectAccount(api_for(session), WHOSE)
    assert len(await account.keys()) == 2
    # And the one that answered is the one asked next time.
    await account.keys()
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert asked.count(f"{EU}{PAIRED}") == 1


async def test_the_region_the_cloud_stamped_is_tried_first(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """Every answer says which environment it came from, which beats guessing."""
    api = api_for(session)
    aioclient_mock.get(
        "https://api.home-connect.com/api/homeappliances",
        json={"data": {"homeappliances": []}},
        headers={"hc-env": "NA-PRD"},
    )
    await api.appliances()
    assert api.region == "na"

    aioclient_mock.get(f"{NA}{PAIRED}", json=APPLIANCES)
    assert len(await HomeConnectAccount(api, WHOSE).keys()) == 2
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert not any(one.startswith(EU) for one in asked)


async def test_being_refused_by_the_account_service_is_said_as_such(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """It is not the token being spent: the appliance API took the same one."""
    aioclient_mock.get(f"{EU}{PAIRED}", status=403, json={})
    aioclient_mock.get(f"{NA}{PAIRED}", status=403, json={})
    with pytest.raises(HomeConnectAuthError):
        await HomeConnectAccount(api_for(session), WHOSE).keys()


async def test_a_description_comes_back_as_it_was_sent(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(
        f"{EU}/api/iddf/v1/iddf/SIEMENS-X-1", content=b"PK\x03\x04 a zip"
    )
    account = HomeConnectAccount(api_for(session), WHOSE)
    assert await account.description("SIEMENS-X-1") == b"PK\x03\x04 a zip"


def test_the_listing_is_walked_for_keys_rather_than_read_by_a_path() -> None:
    """The answer has been reshaped before now, so what is looked for is the
    shape of an appliance with a key rather than a path through the answer."""
    from custom_components.homeconnect.api import _keys_in

    for shape in (
        {"data": {"pairedAppliances": [{"haId": "A-B-C", "tls": {"key": "k"}}]}},
        {"appliances": [{"identifier": "A-B-C", "tls": {"key": "k"}}]},
        [{"id": "A-B-C", "tls": {"key": "k"}}],
    ):
        assert _keys_in(shape) == {"A-B-C": {"key": "k"}}


def test_the_account_id_is_found_wherever_it_sits() -> None:
    from custom_components.homeconnect.api import _account_in

    assert _account_in({"data": {"hcId": "X"}}) == "X"
    assert _account_in({"accounts": [{"accountId": "Y"}]}) == "Y"
    assert _account_in({"nothing": "useful"}) is None
