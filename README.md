<p align="center">
  <img src="custom_components/homeconnect/brand/icon.png" alt="Home Connect" width="128" height="128"/>
</p>

<p align="center">
  <a href="https://github.com/renaudallard/homeassistant_homeconnect/releases/latest">
    <img src="https://img.shields.io/github/v/release/renaudallard/homeassistant_homeconnect?label=version&style=flat-square&sort=semver" alt="Latest release"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_homeconnect/releases">
    <img src="https://img.shields.io/github/downloads/renaudallard/homeassistant_homeconnect/total?style=flat-square&label=downloads" alt="Downloads"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_homeconnect/actions/workflows/validate.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/renaudallard/homeassistant_homeconnect/validate.yml?style=flat-square&label=hacs%20%2F%20hassfest" alt="Validate"/>
  </a>
  <a href="https://github.com/renaudallard/homeassistant_homeconnect/actions/workflows/test.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/renaudallard/homeassistant_homeconnect/test.yml?style=flat-square&label=tests" alt="Tests"/>
  </a>
  <a href="https://www.home-assistant.io/">
    <img src="https://img.shields.io/badge/Home%20Assistant-2026.9%2B-41BDF5?logo=home-assistant&logoColor=white&style=flat-square" alt="Home Assistant"/>
  </a>
  <a href="https://hacs.xyz">
    <img src="https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square" alt="HACS"/>
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/github/license/renaudallard/homeassistant_homeconnect?style=flat-square" alt="License"/>
  </a>
</p>

---

Home Assistant integration for **Bosch, Siemens, Neff, Gaggenau, Thermador
and Balay appliances**, speaking both of the languages the Home Connect app
speaks: the Home Connect cloud, or the appliance itself over your own network
with no cloud in the loop. Pair the appliance with the app once, then drive it
from here.

**No developer account.** It signs in as the app itself, with the app's own
credentials, so an ordinary Home Connect login is the whole of the setup.
Nothing has to be registered anywhere and there is no client of your own to
create or keep.

**Nothing in it knows what a washing machine is.** Every appliance describes
itself, key by key, and the entities are built from that description, so a
model nobody has tried works the same way as the one this was written against.

> Unofficial. Not affiliated with, endorsed by, or supported by BSH Hausgeräte
> or any of its brands. Targets Home Assistant **2026.9 or newer**. The domain
> is `homeconnect`, which is not the `home_connect` of the integration that
> ships with Home Assistant: the two can be installed side by side, and this
> one asks for no developer registration.

## Highlights

- **Built from what the appliance says** — a command becomes a button, a
  settable flag a switch, a choice a select, a bounded number a number. No
  per-model tables, and no list of appliance types to keep up to date.
- **Only what it will accept** — an appliance also says what it will take
  right now. A washing machine offers the programmes it will run in the state
  it is in, and nothing at all while its door is open or remote control has
  not been armed at the machine itself.
- **Cloud or local** — reach the appliances through the Home Connect cloud,
  or straight over your own network with no cloud in the loop at all. Chosen
  when the account is set up and changed afterwards by reconfiguring it, with
  the same entities either way.
- **Live, not polled** — through the cloud, one Server-Sent Events connection
  carries the whole account, so a cycle finishing shows up when it happens.
  Polling carries on behind it at half-hourly intervals to catch whatever a
  dropped connection missed, and drops back to every minute the moment the
  stream goes down. Straight to the appliance there is no stream to drop: each
  one holds its own connection and says what changed as it changes.
- **Careful with the quota** — the API counts every call. What a model can do
  is read once and kept between restarts, the stream carries the changes, and
  a fresh look is only arranged when something happened that the stream cannot
  describe. Reached directly, an appliance costs nothing after the first look
  but the account listing, read every half hour to catch one being paired or
  renamed, since the appliance's own state comes over its own connection.
- **The words the appliance uses** — the cloud names each programme and each
  value it offers, in whatever language Home Assistant is set to, and that is
  what gets shown. Where it has not, the key says plainly enough what it is.
  An appliance talked to directly has no translations to give, so its values
  read as their keys.
- **Units from the description** — an appliance gives each thing it describes
  a number saying what it is, against a table published at the address every
  description names. That is what tells a length of time from a plain figure,
  and a name whose bounds are its length from a number whose bounds are its
  range.
- **Delayed start** — the option that sets one can only be given as a
  programme starts, so it is held here until it does and sent along with the
  start. Set it, press start, and the machine waits.
- **Lamps as lamps** — an appliance keeps a light as two or three separate
  settings. They are gathered into one light entity with brightness and, for
  the decorative sort, colour.

## Installing

Add this repository to [HACS](https://hacs.xyz) as a custom repository of
category **Integration** and install it from there, or copy
`custom_components/homeconnect` into the `custom_components` directory of your
Home Assistant configuration by hand. Either way, restart, then add **Home
Connect** from *Settings → Devices & services*.

An appliance announces itself on the local network as `_homeconnect._tcp`, so
Home Assistant will usually offer the integration on its own, naming whichever
appliance it heard. That only shortens the walk to the form: what an appliance
shouts says it is there and what sort it is, and nothing that would let anyone
talk to it. The account is what authorises that.

The flow shows an address. Open it, sign in with the account the app uses, and
the browser ends on a Home Connect page built to hand a phone the session,
which may show a QR code. Ignore what it shows and take the address out of the
address bar. It carries a one time code, worth nothing to anybody without the
secret this generated before it handed out the first address.

That page can be handed the answer in either of two shapes, as a plain
parameter or with the whole hand-off encoded into one argument, and both are
read. So is a bare code, for anybody who has picked it out themselves.

There is no way to skip the browser. The sign in page is behind a captcha and
says so in as many words to anything that tries without one: *please activate
JavaScript in order to progress*.

That is the only time you sign in. The tokens go into the config entry and are
renewed in the background from then on.

Tokens are written into the config entry and renewed in the background. If they
stop working, Home Assistant asks you to sign in again rather than failing
quietly. It has to be the same account: signing in as somebody else is refused
rather than quietly pointing the entry at another household's appliances.

An appliance unpaired in the app stops being listed, and its device is taken
away on the next look.

## What you get

| The appliance says | You get |
| --- | --- |
| a flag it will let you set | a switch |
| a choice between on and off | a switch, whichever two words it uses |
| a choice, and the values it takes | a select |
| a number with a range | a number |
| words, and how long they may be | a text box |
| a flag it only reports | a binary sensor |
| the door | a door binary sensor, with locked told from merely shut |
| whatever it is complaining about | a binary sensor each |
| the commands it takes | a button each |
| the programmes it will run | a **Programme** select, with **Start programme** and **Stop programme** |
| how long is left | a duration sensor, and a **Finish at** timestamp |
| anything else it reports | a sensor |

A handful of commands are built like the rest but left switched off until you ask for them: a factory reset, a firmware download or update, and the lines that open a channel to the manufacturer's support. They are one press and hard to take back, so none sits there pressable out of the box; enable the one you want from the appliance's page. An account set up before this keeps whatever it had, except that these are switched off once on the upgrade.

An appliance that the account lists but that has never once answered raises a
repair notice saying so, because otherwise it arrives as a single Disconnected
sensor and no explanation, which reads like this failing when it is the
appliance not talking to the cloud. The commonest reason is simply that the
appliance is switched off: several kinds, hobs above all, only hold a cloud
connection while they are in use, and one sitting switched off keeps just
enough of its network module awake to answer the app over the local network.
It looks perfectly healthy there while the cloud has never heard from it. The
notice goes away by itself once the appliance answers, and a machine that used
to work and is switched off today raises nothing at all: that is not something
to repair.

Every appliance also gets a **Connection** binary sensor, which is where a
machine going quiet shows up. When the cloud stops calling an appliance
reachable, what it last said stays readable, so a wash can be looked at
afterwards; `binary_sensor.<appliance>_connection` is what says the machine has
gone, rather than every other entity saying it at once. Controls do go
unavailable, since there is nothing to set on an appliance that cannot be
reached.

Beside it is a **Transport** sensor, reading `cloud` or `local`, which says
which way the entry reaches that appliance. It answers a different question
from the one beside it: the transport is how the appliance would be reached,
the connection is whether it is answering.

The device is named for what the account calls it, with the type code from its
rating plate as the model and the full number with the customer index beside
it.

Reading a description better sometimes moves a key from one kind of entity to
another, and the entity it used to be is taken away when that happens. It
would otherwise sit in the registry for good, unavailable and beyond reach,
beside the one that replaced it.

Four details worth knowing, because they look like faults and are not:

- **The controls are unavailable until remote control is armed** at the
  machine. An appliance whose panel has not been told to accept instructions
  refuses everything, and the app greys the same controls out. Starting needs
  a second permission on top of that, which is why **Start** can be
  unavailable while the rest of the appliance is not.
- **The programme list shrinks and grows.** An appliance that is off, or whose
  door is open, offers nothing; one mid-cycle offers only what it is doing.
  That is the appliance's own rule, and offering anything else earns a
  refusal.
- **The programme decides what can be adjusted.** A cotton wash takes a
  temperature and a spin speed that a wool wash will not, so the options that
  belong to another programme go unavailable rather than disappearing. They
  come back when that programme is chosen again.
- **A refusal says why.** An appliance that will not do as it is told names the
  reason, and that reason is what appears in Home Assistant rather than a bare
  failure, because it is the only thing that says what to go and do about it.

The **Finish at** timestamp is held still while the estimate is. An appliance
counts down in whole minutes and repeats itself in between, so working the
finishing time out afresh every time it says anything would move it about by a
minute in each direction for the whole of a cycle. It is only moved when the
appliance has changed its mind by more than the counting down explains.

Entity names come from the key rather than from the cloud, because a key is
stable and says what a thing is: `BSH.Common.Status.OperationState` reads as
**Operation state** wherever it turns up. The values are the other way round,
because a key is a poor name for a value and the cloud has a good one:
`LaundryCare.Washer.EnumType.Temperature.GC40` is **40 °C** to the appliance
and would be **GC 40** to anything working it out for itself. Every reading of
an enumerated value also carries the appliance's own word for it as a `value`
attribute, which is what an automation should read: that one does not change
with the language Home Assistant is set to.

## The hob card

A cooking table is worth seeing rather than reading down a list, so the
integration ships a dashboard card that draws one the way the app does: the
dark glass surface with each zone painted on it, showing its power level,
whether it is heating, its temperature and any countdown. The card comes with
the integration and is loaded onto the frontend for you, so there is no
resource to add by hand.

    type: custom:homeconnect-hob-card

Add it from the dashboard's card picker and a small form lets you choose the
hob and give it a heading; with only one hob on the system it is chosen for
you and even that is not needed. Where there is more than one, set which:

    type: custom:homeconnect-hob-card
    device: <the hob's device id>
    name: Kitchen hob

Two honest limits. The picture is drawn, not photographed: there is no cooktop
image to be had, from the app or anywhere, so this is a rendering rather than a
likeness of your exact model. And no appliance says where its zones physically
sit, so they are laid out in a tidy grid rather than in the arrangement of one
particular table. It reads the same zone sensors any hob exposes, so it works
without knowing which model it is looking at.

## Cloud or local

An appliance answers on the network it is already on, and will do it with no
cloud involved. **Reconfigure** the entry to move it between the two; nothing
else changes and there is no need to sign in again.

Signing in is needed either way, and once either way. The account is the only
place two things are kept, and neither is on the network: the key an appliance
is reached with, and the appliance's own description of itself. Both are
fetched once and kept between restarts, so nothing about what an appliance is
doing is asked of the cloud again. The account listing is still read every
half hour, to notice an appliance being paired, renamed or unpaired; that is
the whole of what the cloud is asked once an appliance is reached directly.

|  | Through the cloud | Straight to the appliance |
| --- | --- | --- |
| works away from home | yes | no |
| works with the internet down | no | yes |
| counts against the API quota | yes | no, after the first look |
| how changes arrive | one stream for the account | each appliance's own connection |
| finds the appliance by | the account | its own announcement on the network |
| needs a key from the account | no | yes, one per appliance |

Local control needs each appliance to be on the same network as Home
Assistant and announcing itself on it, which is what the discovery card is
built on. An appliance that cannot be found that way stays unavailable until
it turns up.

It also needs the account to publish a key for that appliance. Each key
stands under the appliance it belongs to rather than in the account's list of
what is paired with it, and it is asked for one appliance at a time. An
appliance the account has no key for is left out and said so in the log; an
account with no key for anything at all cannot be reached this way, and
setting an entry to local says that plainly rather than failing obscurely.

The entities are the same either way, and so are their names and their unique
ids, because both sides are turned into the same shapes before anything above
them sees them. Moving an entry between the two keeps every entity and all of
its history.

Two differences worth knowing. Talked to directly, an appliance says
everything in numbers, and the words come from its description file rather
than from the cloud, so a value reads as its key rather than in the language
Home Assistant is set to. The units are the same either way, because a
description says what each thing is as well as how large it may be. And
stopping a programme is the appliance's own stop command rather than emptying
the programme slot, which comes to the same thing but is only offered by an
appliance that describes that command.

## Reporting a problem

The device page offers to download diagnostics, and that is the one to send:
it carries the whole of what that appliance said about itself, what it can do,
what it is doing, how often the account is being asked, and the appliance's
own description file as the cloud sent it. That last one matters more than it
sounds: what the rest of the report shows is what this integration made of
the description, and only the description itself says whether something
missing was never there or was dropped on the way in. The integration
entry offers the same thing for every appliance on the account at once, which
is worth having only when the trouble is with the account rather than with a
machine.

Both are redacted the same way the logs are, so tokens and the serial number
that names one particular machine are replaced by a note of their length. The
brand, the model and everything the appliance said about itself stay readable.

For a model this has never seen, that download is the one thing a report cannot
do without.

## When the controls go unavailable

An appliance that is not being heard from cannot be set to anything, so every
control on it goes unavailable. Readings stay, holding whatever it last said.
The **Connection** binary sensor says which it is, and the **Transport** sensor
beside it says which way it was being reached.

Through the cloud, an appliance talks to Home Connect itself rather than
through Home Assistant, so one that has dropped off its own network looks
exactly like this while the integration carries on talking to the cloud quite
happily. Check the connection sensor first, and the appliance's own network
settings after that.

Reached directly, the appliance has to be on the same network and to have
announced itself on it at some point, since that is how its address is
learnt. Being switched off does not stop it answering: a hob that is off
still holds a connection and reports everything, and says the moment it is
switched on.

**An appliance allows one direct connection per identity.** A client says who
it is when it connects, and a second client saying the same thing is let in
while the first is closed, so the two take the appliance off each other every
few seconds for as long as both keep trying. Different identities sit side by
side without trouble. This integration says `homeassistant` followed by a few
bytes of this install's own id, so the Home Connect app (which says its own
thing) and even a second Home Assistant on the same network each reach the
appliance without disturbing the others. The only way to collide is to make
something announce the same name on purpose.

If every control is unavailable and the connection sensor says the appliance is
there, remote control has not been armed at the machine.

## How the login works

The app is an ordinary OAuth 2 public client with PKCE, and this is the same
exchange with one manual step in the middle of it.

1. `GET /security/oauth/authorize` on `api.home-connect.com`, with the app's
   client id, one of its two registered redirect addresses, its scopes,
   `prompt=login` and the digest of a secret generated a moment earlier. The
   cloud sends whoever is walking it on to SingleKey ID, which is where the
   account is actually signed in to.
2. SingleKey ID takes the address and then the password, each on its own page,
   and hands the account back through `api.home-connect.com` to the registered
   address, with a one time code on it.
3. `POST /security/oauth/token` trades the code, the secret and the client id
   for an access token and a refresh token. There is no client secret: a
   public client has none, which is the whole reason PKCE exists.

The app registers two addresses to be sent back to and only one is any use
here. The other, `hcauth://auth/prod`, is a private scheme only a phone can
open: a browser will not, and the hop that fails leaves the address bar on the
last page that did load, with the code nowhere. Nor can the sign in be walked
without a browser to get round that, which is what the captcha in step 2 is
there to stop.

The refresh token rotates on every renewal, so whatever holds it has to write
the new one back; the client reports each new pair through a listener for that
reason. Renewing a token that was issued moments earlier is refused with a 429,
which is not a failure while the token in hand still works, so it is kept.

The credentials in `const.py` are the production values shipped in the Home
Connect Android package. They identify the app rather than the user, are the
same for every installation, and are not secrets: an appliance answers only to
a client its account has been paired with, and the app's client is the one
every account already trusts. That is what makes an ordinary login enough.

## What it talks to

Signing in and reading the account happen on `https://api.home-connect.com`.
Both the OAuth endpoints and the appliance API live there, and both regions
the app knows about share the one host, so there is nothing to ask about.

Set to reach the appliances through the cloud, that host is the whole of it:

| | |
| --- | --- |
| `GET /api/homeappliances` | what is on the account |
| `GET /api/homeappliances/{id}/status` | what it reports about itself |
| `GET /api/homeappliances/{id}/settings` | what it has, then one call each for what they take |
| `GET /api/homeappliances/{id}/commands` | what it can be told to do |
| `GET /api/homeappliances/{id}/events` | what it is complaining about now |
| `GET /api/homeappliances/{id}/programs/available` | what it will run, and one call for what each takes |
| `GET/PUT /api/homeappliances/{id}/programs/{active,selected}` | what it is doing, and what it is set to |
| `PUT /api/homeappliances/{id}/settings/{key}` | change a setting |
| `PUT /api/homeappliances/{id}/programs/{slot}/options/{key}` | change an option |
| `PUT /api/homeappliances/{id}/commands/{key}` | send a command |
| `GET /api/homeappliances/events` | the stream, carrying the whole account |

Set to reach the appliances directly, it asks the account's own service two
things about each appliance once, and after that the only thing it reads from
the cloud is the appliance listing above, every half hour, to catch a pairing
or a rename:

| | |
| --- | --- |
| `GET /api/appliance/v2/appliances/{id}/encryption-information` | the key that appliance is reached with |
| `GET /api/iddf/v1/iddf/{id}` | that appliance's own description of itself |

Those live on `eu.services.home-connect.com` or `na.services.home-connect.com`
depending on the account, which nothing says in advance, so each is tried
until one answers and the one that did is remembered.

A description also names a third address, the table saying what the number on
each described thing means. That one is not fetched: it has sat unchanged
since 2014 and is generated into `content.py` by `tools/make_content_types.py`,
because naming a unit should not need a schema host to be reachable.

The appliance itself answers on a websocket at `/homeconnect`. Newer ones
secure the connection with that shared key instead of a certificate, on port
443; older ones speak plain websocket on port 80 and encrypt each message
themselves, chaining the cipher and a running digest so that a replayed or
reordered message is refused. Both are spoken here, and neither needs a
dependency: shared key TLS has been in the Python standard library since 3.13
and Home Assistant already ships the rest.

Reading one appliance in full costs a call for every setting it has, which is
the most expensive thing here and the reason the answers are kept between
restarts. They describe the model rather than what it is doing, so two
appliances of the same model ask once between them, and a restart asks not at
all.

## Branding

`custom_components/homeconnect/brand/` holds the two PNGs Home Assistant looks
for when an integration is not listed in home-assistant/brands. Both are the
Home Connect application icon scaled, and `tools/make_icons.py` regenerates
them from it; it needs Pillow, which Home Assistant already ships. There is no
logo pair, a logo being a wordmark and the application icon being a square
mark.

The Home Connect name and mark belong to BSH Hausgeräte. They are here to
identify the appliances this integration talks to, the same way every other
manufacturer logo appears in home-assistant/brands.

## Development

    ruff check .
    ruff format --check .
    mypy custom_components/ tests/ tools/
    pytest tests/

`aiohttp` is the only runtime dependency, and Home Assistant ships it. The
checks need `homeassistant` and `pytest-homeassistant-custom-component`.
Neither is needed to run the integration. The decompiled app and the scratch
work live in `tmp/`, which is not tracked, as is the app package itself.

`tools/check_login.py` walks the whole sign in against a real account outside
Home Assistant, says which step fails, and logs every request and answer
redacted. `--dump DIR` writes what every appliance said into that directory
with the serial numbers taken out, which is what a fixture is made from.

`tools/talk_to.py` holds a conversation with one appliance over the local
network, using the integration's own link, and prints every frame, every
value and every change of connection as they happen. It only listens: nothing
in it writes to the appliance. The shared key is read from a file so that it
lands in neither the shell history nor the process list, and that file belongs
under `tmp/`, which is not tracked. It announces a different identity from the
integration, so the two listen to one appliance at once without taking it off
each other; `--device-id homeassistant` makes it stand in the integration's
place instead, for seeing what a collision looks like.

The tests load a washing machine and an oven and check what comes out of them.
The config flow tests drive the real Home Assistant flow machinery, so they
cover which step follows which, what lands in the config entry, and which
message a failure puts on the form. Nothing in them touches the network.

**Validate** runs HACS validation and hassfest on every push, on any branch.
**Tests** runs the lint, the type check and the suite, but only on `main` and
on pull requests, so a push to a branch with no pull request open runs
Validate alone and a green tick there is not the whole set of checks.

Neither HACS validation nor hassfest runs locally. hassfest reads a good deal
more than the manifest: the strings and the translations are held to rules of
its own, so that workflow is the first sign of anything it covers.

A third, **Autorelease**, runs only when the version in the manifest changes.
It holds the release back on the same three checks, then tags the commit,
writes the release with the notes running from the tag before it, and puts a
zip of `custom_components/homeconnect` on it. Releasing is therefore a matter
of bumping the version and pushing. A release written by hand before the
workflow gets there keeps its own notes and is only given the zip, which is
how a release worth writing up properly still gets one.
