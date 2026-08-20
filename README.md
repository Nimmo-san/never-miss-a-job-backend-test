# Never Miss a Job — Backend (Week 1 MVP)

A dedicated, tracked WhatsApp/SMS/call channel for a solo UK plumbing &
heating tradesperson. Week 1's only job is proving the pipe works end to
end: inbound calls get dialled through to the tradesperson with a whisper
message, missed calls are detected and logged, and inbound texts/WhatsApp
messages get logged and a placeholder reply. **There is no AI qualification
logic yet** — every point where that plugs in later is marked with a
`TODO` in the code (see [Week 2 hand-off points](#week-2-hand-off-points)
below).

## What this is (and isn't)

- **Is:** a working FastAPI + Twilio + SQLite skeleton you can point a real
  Twilio number at today and watch calls/messages flow through it.
- **Isn't:** an AI agent. No qualification questions get asked, no jobs get
  booked, no SMS fallback is actually sent when a call is missed — those are
  Week 2. Week 1 stops at "detected and logged."

## Deliberate v1 simplifications

These are conscious choices for a solo, part-time, near-zero-budget build —
not oversights:

- **Single tradesperson, single number.** `TRADESPERSON_NUMBER` is one
  global env var. Before onboarding a second client, this needs to become
  per-client config (e.g. a `clients` table keyed by the dedicated Twilio
  number Twilio reports in the webhook's `To` field), so different dedicated
  numbers route to different tradespeople. See the `TODO` in `app/config.py`.
- **SQLite, not Postgres.** Fine for one client at low volume. Revisit once
  running multiple clients concurrently with real traffic — SQLite's
  single-writer lock will start to hurt at that point.
- **No AI yet.** Calls and messages are logged and given a placeholder
  response only. The qualification/booking agent is Week 2 work.
- **No Twilio request signature validation.** Anyone who finds these
  webhook URLs could POST fake Twilio-shaped requests to them today. Fine
  for a Week 1 skeleton being tested by one person; before real customer
  traffic, add [Twilio request validation](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
  using `TWILIO_AUTH_TOKEN`.
- **Ring timeout, whisper wording, and fallback/reply copy are tunable
  defaults**, not fixed requirements — all overridable via `.env` (see
  `.env.example`). Change the wording to suit the business.

## Project layout

```
app/
  main.py        FastAPI app, startup (DB init), health check
  webhooks.py     Twilio webhook endpoints (voice + messaging)
  database.py     SQLite data layer (calls, conversations, messages)
  config.py       Environment variable loading (python-dotenv)
requirements.txt
.env.example
```

## Data model

Three tables, created automatically on startup (`app/database.py`):

- **`calls`** — one row per inbound call (`call_sid` unique), tracks the
  initial call status and the eventual `<Dial>` outcome
  (`completed` / `no-answer` / `busy` / `failed` / `canceled`).
- **`conversations`** — one row per open enquiry thread, keyed loosely by
  customer number. A missed call and a follow-up text from the same number
  share a conversation rather than creating duplicate rows.
- **`messages`** — inbound and outbound SMS/WhatsApp messages, linked to a
  conversation.

## Local setup

Requires Python 3.11+.

```bash
git clone <this repo>
cd never-miss-a-job-backend-test

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env and set TRADESPERSON_NUMBER and TWILIO_NUMBER at minimum
```

## Running with uvicorn

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

- `GET http://localhost:8000/health` should return `{"status": "ok"}`.
- The SQLite file is created automatically at `DATABASE_PATH` (default
  `./data/app.db`) on first startup.

## Exposing it locally via ngrok (for real Twilio testing)

Twilio needs a public HTTPS URL to send webhooks to. With the app running
locally on port 8000 in one terminal, in another terminal:

```bash
ngrok http 8000
```

Copy the `https://xxxxxxxx.ngrok-free.app` forwarding URL ngrok prints —
you'll use it below. Note it changes every time you restart ngrok on the
free tier, so you'll need to re-paste it into the Twilio console each
session unless you have a reserved domain.

## Twilio console webhook configuration

In the [Twilio Console](https://console.twilio.com), under
**Phone Numbers → Manage → Active Numbers**, click your dedicated number,
then:

### Voice

Under **Voice Configuration → A call comes in**:

- Set to **Webhook**
- URL: `https://<your-ngrok-domain>/webhooks/voice/incoming`
- HTTP method: **POST**

(You do **not** need to separately configure the whisper or dial-status
URLs in the console — they're returned dynamically as TwiML by the
`/webhooks/voice/incoming` response itself, as relative paths that Twilio
resolves against the same host.)

### SMS

Under **Messaging Configuration → A message comes in**:

- Set to **Webhook**
- URL: `https://<your-ngrok-domain>/webhooks/messages/incoming`
- HTTP method: **POST**

### WhatsApp (Twilio Sandbox)

If you're using the Twilio WhatsApp Sandbox (**Messaging → Try it out →
Send a WhatsApp message**), under **Sandbox settings**:

- **When a message comes in**: `https://<your-ngrok-domain>/webhooks/messages/incoming`
- HTTP method: **POST**

Both SMS and WhatsApp point at the same endpoint — it tells them apart by
the `whatsapp:` prefix Twilio puts on the `From`/`To` numbers.

## Inspecting the SQLite data directly

With the app stopped (to avoid reading mid-write), or freely while it's
running (SQLite handles concurrent readers fine):

```bash
sqlite3 data/app.db

sqlite> .tables
sqlite> .schema calls
sqlite> SELECT * FROM calls;
sqlite> SELECT * FROM conversations;
sqlite> SELECT * FROM messages ORDER BY id;
sqlite> .quit
```

No `sqlite3` CLI installed? A GUI like [DB Browser for SQLite](https://sqlitebrowser.org/)
works too — just point it at `data/app.db`.

## Manual test sequence

Once the app is running and exposed via ngrok, with the Twilio console
configured as above:

1. **Missed call:** Call your dedicated Twilio number from your own phone,
   and *don't* answer the tradesperson's phone (or use a
   `TRADESPERSON_NUMBER` you know won't pick up). After ~20s (or your
   configured `RING_TIMEOUT_SECONDS`) you should hear the
   `MISSED_CALL_CALLER_MESSAGE`. Check `calls` — a row with
   `dial_call_status = 'no-answer'`, and `conversations` — a new row with
   `source_event` like `missed_call:no-answer`.
2. **Answered call:** Call again, this time answer the tradesperson's
   phone. You should hear the whisper message on the tradesperson's end
   only, then the call bridges to the customer. Check `calls` — the row's
   `dial_call_status` should be `completed`, and no new `conversations` row
   should be created for it.
3. **Inbound text:** Text your dedicated number. You should get the
   `SMS_PLACEHOLDER_REPLY` back within a few seconds. Check `messages` —
   both the inbound and the outbound acknowledgement should be logged
   against a `conversations` row.
4. **Inbound WhatsApp:** Same as above via the WhatsApp sandbox — check the
   `channel` column reads `whatsapp` and numbers carry the `whatsapp:`
   prefix.
5. **Same customer, two channels:** Do a missed call from a number, then
   text from the same number. Confirm in `conversations` that the text
   reuses the same open conversation row from the missed call rather than
   creating a second one.

## Week 2 hand-off points

Grep the codebase for `TODO (Week 2` to find all of them. Summary:

- `app/webhooks.py`, `voice_dial_status()` — on a missed/busy/failed call,
  Week 1 only logs it and opens a conversation. Week 2 should send the real
  SMS fallback to the customer and hand the thread to the AI agent.
- `app/webhooks.py`, `messages_incoming()` — Week 1 sends a fixed
  placeholder reply to every inbound text/WhatsApp message. Week 2 should
  replace this with the AI qualification agent reading
  `database.list_messages()` and responding contextually.
- `app/config.py` — single-tradesperson config. Needs to become per-client
  before a second client is onboarded (see simplifications above).

## What was actually tested vs. not

See the delivery summary in the conversation this was built in for the full
breakdown of what was run and verified (database layer, full request/response
cycle via `TestClient`, and a real `uvicorn` process hit with `curl`) versus
what needs verifying against a live Twilio account (actual phone call audio,
whisper-only audibility, ngrok tunnelling, and the Twilio console
configuration steps) since this build environment has no telephony access.
