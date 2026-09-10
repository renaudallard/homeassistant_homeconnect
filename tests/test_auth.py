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

"""Signing in, and the pieces the sign in is made of."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from collections.abc import AsyncGenerator
from urllib.parse import parse_qs, urlparse

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import auth
from custom_components.homeconnect.const import (
    API_HOST,
    CLIENT_ID,
    REDIRECT_URI,
    SCOPES,
    TOKEN_PATH,
)
from custom_components.homeconnect.errors import (
    HomeConnectAuthError,
    HomeConnectTooManyRequests,
)

TOKEN_URL = f"{API_HOST}{TOKEN_PATH}"


@pytest.fixture
async def session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[aiohttp.ClientSession]:
    """A session that answers out of the mock and is shut afterwards."""
    made = aioclient_mock.create_session(hass.loop)
    yield made
    await made.close()


def test_the_sign_in_ends_where_no_page_can_swallow_the_code() -> None:
    """The https address the app also registers loads a page that hands the
    session to a phone, and is free to tidy the code away while it does."""
    assert REDIRECT_URI.startswith("hcauth://")


def test_the_address_carries_what_the_app_carries() -> None:
    verifier = auth.verifier()
    query = parse_qs(urlparse(auth.authorize_url(verifier, "a-state")).query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["response_type"] == ["code"]
    assert query["scope"] == [" ".join(SCOPES)]
    assert query["prompt"] == ["login"]
    assert query["state"] == ["a-state"]
    assert query["code_challenge_method"] == ["S256"]


def test_the_secret_is_published_only_as_its_digest() -> None:
    verifier = auth.verifier()
    query = parse_qs(urlparse(auth.authorize_url(verifier, "s")).query)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert query["code_challenge"] == [expected]
    assert verifier not in auth.authorize_url(verifier, "s")


def test_two_sign_ins_do_not_share_a_secret() -> None:
    assert auth.verifier() != auth.verifier()


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        # What the browser refuses to open, which is what the flow asks for.
        ("hcauth://auth/prod?code=abc&state=s", "abc"),
        ("  hcauth://auth/prod?state=s&code=abc  ", "abc"),
        # The app's other registered address, in case a browser gets that far.
        ("https://qr.home-connect.com/authorize/prod/?code=abc&state=s", "abc"),
        # Somebody who has picked the code out themselves is not made to put
        # it back into an address.
        ("abc", "abc"),
    ],
)
def test_the_code_comes_out_of_whatever_was_pasted(answer: str, expected: str) -> None:
    assert auth.code_from(answer) == expected


def test_an_address_that_says_no_says_why() -> None:
    with pytest.raises(HomeConnectAuthError, match="access_denied"):
        auth.code_from("https://qr.home-connect.com/x?error=access_denied")


def test_an_address_with_no_code_is_refused() -> None:
    with pytest.raises(HomeConnectAuthError):
        auth.code_from("hcauth://auth/prod")


def test_nothing_pasted_is_refused() -> None:
    with pytest.raises(HomeConnectAuthError):
        auth.code_from("   ")


def _identity(subject: str) -> str:
    claims = base64.urlsafe_b64encode(json.dumps({"sub": subject}).encode())
    return f"header.{claims.decode().rstrip('=')}.signature"


async def test_the_exchange_sends_the_secret_and_reads_the_pair(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.post(
        TOKEN_URL,
        json={
            "access_token": "an-access-token",
            "refresh_token": "a-refresh-token",
            "expires_in": 3600,
            "token_type": "Bearer",
            "id_token": _identity("who-this-is"),
        },
    )
    tokens = await auth.exchange(session, "the-code", "the-verifier")
    sent = aioclient_mock.mock_calls[0][2]
    assert sent["grant_type"] == "authorization_code"
    assert sent["code"] == "the-code"
    assert sent["code_verifier"] == "the-verifier"
    assert sent["client_id"] == CLIENT_ID
    assert tokens.access_token == "an-access-token"
    assert tokens.account == "who-this-is"
    assert tokens.expires_at > time.time() + 3500


async def test_a_lifetime_that_does_not_read_means_renew_at_once(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """Better due immediately than sent somewhere on a guess."""
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "a", "refresh_token": "b", "expires_in": "soon"},
    )
    tokens = await auth.exchange(session, "c", "v")
    assert tokens.expired


async def test_a_refused_code_asks_for_a_fresh_sign_in(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.post(
        TOKEN_URL,
        status=400,
        json={"error": "invalid_grant", "error_description": "code expired"},
    )
    with pytest.raises(HomeConnectAuthError, match="code expired"):
        await auth.exchange(session, "stale", "v")


async def test_being_asked_to_slow_down_says_for_how_long(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.post(TOKEN_URL, status=429, headers={"Retry-After": "12"}, json={})
    with pytest.raises(HomeConnectTooManyRequests) as refused:
        await auth.renew(session, auth.Tokens("a", "b", 0.0))
    assert refused.value.retry_after == 12


async def test_a_renewal_keeps_the_account_it_did_not_mention(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """A pair renewed without an identity token still belongs to the account."""
    aioclient_mock.post(
        TOKEN_URL,
        json={"access_token": "a2", "refresh_token": "b2", "expires_in": 3600},
    )
    renewed = await auth.renew(session, auth.Tokens("a", "b", 0.0, account="who"))
    assert renewed.account == "who"
    assert renewed.refresh_token == "b2"


async def test_an_answer_with_no_pair_in_it_is_not_a_sign_in(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.post(TOKEN_URL, json={"access_token": "a"})
    with pytest.raises(HomeConnectAuthError):
        await auth.exchange(session, "c", "v")
