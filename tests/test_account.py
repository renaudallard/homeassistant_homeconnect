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
from typing import Any

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect.api import HomeConnectAccount, HomeConnectApi
from custom_components.homeconnect.auth import Tokens
from custom_components.homeconnect.errors import HomeConnectAuthError

EU = "https://eu.services.home-connect.com"
NA = "https://na.services.home-connect.com"
HOB = "SIEMENS-EX651HEC1E-ABC"
WASHER = "BOSCH-OLD-DEF"


def key_of(haid: str) -> str:
    """Where one appliance's key is kept."""
    return f"/api/appliance/v2/appliances/{haid}/encryption-information"


# The connection is secured for one of these and the messages for the other.
SECURED = {"aes": None, "tls": {"key": "a-shared-key"}}
SEALED = {"aes": {"key": "another-key", "iv": "a-vector"}, "tls": None}


@pytest.fixture
async def session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[aiohttp.ClientSession]:
    made = aioclient_mock.create_session(hass.loop)
    yield made
    await made.close()


def api_for(session: aiohttp.ClientSession) -> HomeConnectApi:
    return HomeConnectApi(session, Tokens("a-token", "b", 9e9), "en-GB")


async def test_each_appliance_is_asked_for_its_own_key(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """The key stands under the appliance. The account's list of what is
    paired with it says a great deal and never says this."""
    aioclient_mock.get(f"{EU}{key_of(HOB)}", json=SECURED)
    aioclient_mock.get(f"{EU}{key_of(WASHER)}", json=SEALED)
    account = HomeConnectAccount(api_for(session))
    assert await account.keys([HOB, WASHER]) == {
        HOB: {"key": "a-shared-key"},
        WASHER: {"key": "another-key", "iv": "a-vector"},
    }


async def test_the_other_region_is_tried_when_the_first_will_not_answer(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """An account belongs to one of two and the other has never heard of it."""
    aioclient_mock.get(f"{EU}{key_of(HOB)}", status=404, json={})
    aioclient_mock.get(f"{NA}{key_of(HOB)}", json=SECURED)
    account = HomeConnectAccount(api_for(session))
    assert await account.keys([HOB]) == {HOB: {"key": "a-shared-key"}}
    # And the one that answered is the one asked next time.
    await account.keys([HOB])
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert asked.count(f"{EU}{key_of(HOB)}") == 1


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

    aioclient_mock.get(f"{NA}{key_of(HOB)}", json=SECURED)
    assert len(await HomeConnectAccount(api).keys([HOB])) == 1
    asked = [str(url) for _, url, _, _ in aioclient_mock.mock_calls]
    assert not any(one.startswith(EU) for one in asked)


async def test_being_refused_by_the_account_service_is_said_as_such(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """It is not the token being spent: the appliance API took the same one.

    Being refused is not one appliance having nothing kept for it. The token
    is the account's, so it stops the lot rather than being passed over the
    way a missing key is.
    """
    aioclient_mock.get(f"{EU}{key_of(HOB)}", status=403, json={})
    aioclient_mock.get(f"{EU}{key_of(WASHER)}", json=SEALED)
    with pytest.raises(HomeConnectAuthError):
        await HomeConnectAccount(api_for(session)).keys([HOB, WASHER])


async def test_a_description_comes_back_as_it_was_sent(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(
        f"{EU}/api/iddf/v1/iddf/SIEMENS-X-1", content=b"PK\x03\x04 a zip"
    )
    account = HomeConnectAccount(api_for(session))
    assert await account.description("SIEMENS-X-1") == b"PK\x03\x04 a zip"


async def test_an_appliance_with_no_key_is_left_out_rather_than_stopping_the_rest(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """One appliance without a key says nothing about the next one."""
    aioclient_mock.get(f"{EU}{key_of(HOB)}", json={"aes": None, "tls": None})
    aioclient_mock.get(f"{EU}{key_of(WASHER)}", json=SEALED)
    account = HomeConnectAccount(api_for(session))
    assert await account.keys([HOB, WASHER]) == {
        WASHER: {"key": "another-key", "iv": "a-vector"}
    }


async def test_nothing_kept_for_an_appliance_is_not_a_failure(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """Not every appliance has anything there. Not finding it only means the
    key is not there either, which the caller works out from what is missing."""
    aioclient_mock.get(f"{EU}{key_of(HOB)}", status=404, json={})
    aioclient_mock.get(f"{NA}{key_of(HOB)}", status=404, json={})
    account = HomeConnectAccount(api_for(session))
    assert await account.keys([HOB]) == {}


def test_either_way_of_securing_an_appliance_is_read_the_same() -> None:
    """The key on its own means the connection is secured. A starting vector
    beside it means the messages are."""
    from custom_components.homeconnect.api import _key_in

    assert _key_in(SECURED) == {"key": "a-shared-key"}
    assert _key_in(SEALED) == {"key": "another-key", "iv": "a-vector"}
    assert _key_in({"aes": None, "tls": None}) is None
    assert _key_in({"tls": {}}) is None
    assert _key_in("not an answer at all") is None


def test_an_answer_can_be_described_without_saying_what_it_holds() -> None:
    """A shape nobody here has seen is the one thing a report cannot do
    without, and none of it is anybody's business but theirs."""
    from custom_components.homeconnect.api import shape

    described = shape(
        {
            "haId": "SIEMENS-EX651HEC1E-335030393548000200",
            "aes": None,
            "tls": {"key": "a-real-secret"},
            "users": [{"name": "Table de cuisson"}],
        }
    )
    assert described == (
        "{haId: str, aes: null, tls: {key: str}, users: [{name: str}] x1}"
    )
    for secret in ("335030393548000200", "Table de cuisson", "a-real-secret"):
        assert secret not in described


def test_describing_something_deep_or_wide_stops_rather_than_running_on() -> None:
    from custom_components.homeconnect.api import shape

    deep: Any = "bottom"
    for _ in range(20):
        deep = {"down": deep}
    assert "..." in shape(deep)
    assert shape([]) == "[]"
    assert shape(None) == "null"
