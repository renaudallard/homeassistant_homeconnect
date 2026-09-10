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

"""Walking the sign in without a browser.

The pages here are cut down from the real ones, keeping the parts the walk
actually reads: the form the fields go in, the token in it, and the redirects
that carry the account back.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aiohttp
import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.homeconnect import singlekey
from custom_components.homeconnect.const import API_HOST, AUTHORIZE_PATH
from custom_components.homeconnect.errors import HomeConnectAuthError

SINGLEKEY = "https://singlekey-id.com"
LOGIN = f"{SINGLEKEY}/en-gb/login"
PASSWORD = f"{SINGLEKEY}/en-gb/password"
HANDBACK = f"{API_HOST}/security/oauth/redirect_target"

# The real page carries three of these, one per form. Only the one in the form
# holding the fields is the right one to send back.
EMAIL_PAGE = """
<html><body>
<form class="form" method="post">
  <input name="UserIdentifierInput.EmailInput.StringValue" type="text" value="">
  <input name="__RequestVerificationToken" type="hidden" value="the-right-token">
</form>
<form class="passkey-authentication__form" method="post">
  <input name="__RequestVerificationToken" type="hidden" value="passkey-token">
</form>
<form class="language-switch footer__link" method="post">
  <input name="__RequestVerificationToken" type="hidden" value="language-token">
</form>
</body></html>
"""

PASSWORD_PAGE = """
<html><body>
<form class="form" method="post">
  <input name="Password" type="password" value="">
  <input name="__RequestVerificationToken" type="hidden" value="password-token">
</form>
</body></html>
"""


@pytest.fixture
async def session(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> AsyncGenerator[aiohttp.ClientSession]:
    made = aioclient_mock.create_session(hass.loop)
    yield made
    await made.close()


def walk(mock: AiohttpClientMocker, **changes: object) -> None:
    """Register the hops a real sign in makes, with one of them replaced."""
    mock.get(
        f"{API_HOST}{AUTHORIZE_PATH}",
        status=302,
        headers={"Location": f"{LOGIN}?f=a-session"},
    )
    mock.get(LOGIN, text=str(changes.get("login_page", EMAIL_PAGE)))
    mock.post(
        LOGIN,
        status=int(changes.get("after_email", 302)),  # type: ignore[call-overload]
        headers={"Location": f"{PASSWORD}?f=a-session"},
        text=str(changes.get("email_answer", "")),
    )
    mock.get(PASSWORD, text=str(changes.get("password_page", PASSWORD_PAGE)))
    mock.post(
        PASSWORD,
        status=int(changes.get("after_password", 302)),  # type: ignore[call-overload]
        headers={"Location": str(changes.get("finally", f"{HANDBACK}?code=x"))},
        text=str(changes.get("password_answer", "")),
    )
    mock.get(
        HANDBACK,
        status=302,
        headers={"Location": "hcauth://auth/prod?code=the-one-time-code&state=s"},
    )


async def test_the_walk_ends_with_the_code(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    walk(aioclient_mock)
    code = await singlekey.sign_in(
        session, "someone@example.invalid", "a-password", "a-verifier", "s"
    )
    assert code == "the-one-time-code"


async def test_the_fields_go_where_the_page_said(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """And the token comes from the form holding them, not the passkey one."""
    walk(aioclient_mock)
    await singlekey.sign_in(session, "someone@example.invalid", "hunter2", "v", "s")
    posted = [
        body for method, _, body, _ in aioclient_mock.mock_calls if method == "POST"
    ]
    assert posted[0] == {
        "UserIdentifierInput.EmailInput.StringValue": "someone@example.invalid",
        "__RequestVerificationToken": "the-right-token",
    }
    assert posted[1] == {
        "Password": "hunter2",
        "RememberMe": "false",
        "__RequestVerificationToken": "password-token",
    }


async def test_an_address_the_account_does_not_know_is_said_plainly(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """The page comes back as it went, with no password asked for."""
    walk(aioclient_mock, after_email=200, email_answer=EMAIL_PAGE)
    with pytest.raises(HomeConnectAuthError, match="address was not accepted"):
        await singlekey.sign_in(session, "nobody@example.invalid", "p", "v", "s")


async def test_a_password_that_is_refused_is_said_plainly(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """Still on a page of SingleKey's rather than handed back."""
    walk(aioclient_mock, after_password=200, password_answer=PASSWORD_PAGE)
    with pytest.raises(HomeConnectAuthError, match="would not accept that password"):
        await singlekey.sign_in(session, "someone@example.invalid", "wrong", "v", "s")


async def test_an_account_wanting_a_second_factor_says_so(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    """It cannot be walked from here, and saying why is what sends the user
    to the way in that can."""
    asks = '<html><body><div class="two-factor">Enter your code</div></body></html>'
    walk(aioclient_mock, after_password=200, password_answer=asks)
    with pytest.raises(HomeConnectAuthError, match="second factor"):
        await singlekey.sign_in(session, "someone@example.invalid", "p", "v", "s")


async def test_a_page_with_no_token_is_not_walked_blindly(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    walk(aioclient_mock, login_page="<html><body>nothing here</body></html>")
    with pytest.raises(HomeConnectAuthError, match="no verification token"):
        await singlekey.sign_in(session, "someone@example.invalid", "p", "v", "s")


async def test_going_round_in_circles_gives_up(
    aioclient_mock: AiohttpClientMocker, session: aiohttp.ClientSession
) -> None:
    aioclient_mock.get(
        f"{API_HOST}{AUTHORIZE_PATH}",
        status=302,
        headers={"Location": f"{API_HOST}{AUTHORIZE_PATH}"},
    )
    with pytest.raises(HomeConnectAuthError, match="round in circles"):
        await singlekey.sign_in(session, "someone@example.invalid", "p", "v", "s")
