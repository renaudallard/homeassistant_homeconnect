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

"""Constants for the Home Connect integration.

The credentials below are the production values shipped in the Home Connect
Android package, version 12.20.0. They identify the app to the Home Connect
cloud, are the same for every installation, and are not user secrets. Using
them is what lets an ordinary account sign in here: the developer portal hands
out a client of your own, but an appliance only answers to a client the account
has actually been paired with, and the app's client is the one every account
already trusts.

The app talks to three hosts. Only the first is of any use here: the other two
carry recipes, media and the appliance's own onboarding, none of which this
does. Both regions share the one API host, so there is nothing to ask the user.
"""

from __future__ import annotations

DOMAIN = "homeconnect"

# Where the OAuth endpoints and the appliance API both live.
API_HOST = "https://api.home-connect.com"

AUTHORIZE_PATH = "/security/oauth/authorize"
TOKEN_PATH = "/security/oauth/token"
API_PATH = "/api"

# The Home Connect app, as it identifies itself to its own cloud.
CLIENT_ID = "9B75AC9EC512F36C84256AC47D813E2C1DD0D6520DF774B020E1E6E2EB29B1F3"

# Where the sign in comes back to. The app registers two of these and only one
# of them is any use from here.
#
# The other is a private scheme, hcauth://auth/prod, which only a phone can
# open. A browser will not, and the hop that fails leaves the address bar
# showing the last page that did load, with the code nowhere at all. Nor can
# the sign in be walked without a browser to get round that: the page it goes
# through is behind a captcha, and says so to anything that tries.
#
# So the sign in comes back to an address a browser can actually reach. The
# page there is built to hand a phone the session, which is not what happens
# next here, but it does end up holding the answer.
REDIRECT_URI = "https://qr.home-connect.com/authorize/prod/"

# What the app asks for. Control, Settings and Monitor are what drive an
# appliance; ReadOrigApi and WriteOrigApi are what open the REST API this
# talks. The rest are asked for together with them because a scope left out of
# the request is a scope the token does not carry, and an account that granted
# the app everything should not have to grant it again for a smaller set.
SCOPES = (
    "Control",
    "DeleteAppliance",
    "IdentifyAppliance",
    "Images",
    "Monitor",
    "ReadAccount",
    "ReadOrigApi",
    "Settings",
    "WriteAppliance",
    "WriteOrigApi",
)

# The API answers in a media type of its own and refuses a request that does
# not ask for it.
MEDIA_TYPE = "application/vnd.bsh.sdk.v1+json"

# Where the account's own service lives, which is not where the appliance API
# lives. Two of these serve two halves of the world and an account belongs to
# one of them, which nothing says in advance, so each is tried until one
# answers and the one that did is remembered.
SERVICES_HOSTS = (
    "https://eu.services.home-connect.com",
    "https://na.services.home-connect.com",
)

# The account itself, and the appliances paired with it. The second is where
# the key that lets this talk to an appliance directly is kept, and it hangs
# off the account's own identifier rather than standing on its own.
ACCOUNTS_PATH = "/api/account/v1/accounts"
PAIRED_PATH = "/api/account/v2/accounts/{}/paired-appliances"

# An appliance's own description of itself, as a zip of two XML files. It is
# the only thing that turns the numbers an appliance speaks in back into keys.
DESCRIPTION_PATH = "/api/iddf/v1/iddf/{}"

# Config entry keys of our own. The tokens live in the entry because the
# refresh token rotates on every renewal and has to survive a restart.
# Which way the appliances are reached. The account is what says they exist
# either way; this decides only where their state is read from and where a
# change is sent.
CONF_TRANSPORT = "transport"
CLOUD = "cloud"
LOCAL = "local"

CONF_ACCESS_TOKEN = "access_token"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_EXPIRES_AT = "expires_at"

# Renew this long before the access token actually expires, so a call that
# starts just under the wire does not race the expiry.
TOKEN_EXPIRY_MARGIN = 60.0

REQUEST_TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0

# The event stream is meant to stay open for hours, so it is only ever timed
# out on silence. The cloud sends a keep-alive well inside this.
STREAM_READ_TIMEOUT = 120.0
