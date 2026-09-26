# Deploying Seva Mitra on WhatsApp via Twilio

This guide takes you from zero to a live WhatsApp bot using the Twilio files:

- `seva_mitra_twilio.py` - the Twilio webhook server (new)
- `seva_mitra_prototype.py` - the conversation engine (keep it in the same folder)

You can test everything in about 15 minutes with the **Twilio WhatsApp Sandbox** - no Meta business verification, and **no API key needed for replying** (replies ride the 24-hour customer service window as TwiML webhook responses).

---

## Step 1 - Run the server

On any machine with Python 3 (laptop, VM, or cloud host):

```bash
python3 seva_mitra_twilio.py          # serves on port 8787 by default
PORT=8080 python3 seva_mitra_twilio.py   # or choose a port
```

You should see:

```
Seva Mitra (Twilio WhatsApp) webhook server
  listening on :8787 (override with PORT env var)
  webhook URL for Twilio:  https://<your-public-host>:8787/webhook
```

Quick local test (in a second terminal):

```bash
curl -X POST http://localhost:8787/webhook \
     -d 'From=whatsapp:+919999000011' -d 'Body=hi'
```

You should get TwiML back starting with `<Response><Message>Namaskaram!...`

## Step 2 - Make it publicly reachable

Twilio must be able to reach your webhook over HTTPS.

**For testing (fastest):** install [ngrok](https://ngrok.com) and run:

```bash
ngrok http 8787
```

It prints a URL like `https://a1b2c3d4.ngrok-free.app` - use that as your public host.

**For a permanent deployment:** use any small host:

| Host | How |
|---|---|
| Render (free tier) | New Web Service, upload the two .py files, start command `python seva_mitra_twilio.py`, it injects `PORT` |
| Railway / Fly.io | Same idea; set start command and let `PORT` env var drive the listen port |
| Your own VM (AWS/DO/GCP) | Run the server, put nginx or Caddy in front for HTTPS, keep it alive with systemd |

## Step 3 - Connect the Twilio WhatsApp Sandbox (10 minutes)

1. Log in to the [Twilio Console](https://console.twilio.com).
2. Go to **Messaging -> Try it out -> Send a WhatsApp message**.
3. Join the sandbox from your own WhatsApp: send the shown code (`join xxxx-xxxx`) to the sandbox number **+1 415 523 8886**.
4. Still on that page, find **Sandbox settings**:
   - **When a message comes in**: `https://<your-public-host>/webhook`
   - **Method**: `HTTP POST`
5. Save. Now message the sandbox number on WhatsApp - Seva Mitra replies.

**Sandbox limits:** it is for testing only; every tester must join the sandbox first; the 24-hour rule applies (the bot can only reply within 24 hours of your last message, which is exactly how our bot works).

## Step 4 - Production: your own WhatsApp number (when ready)

For a real public deployment you need your own sender:

1. Twilio Console -> **Messaging -> Senders -> WhatsApp senders -> Create new**.
2. This requires **Meta Business verification** and a **display name approval** (Twilio walks you through it; approval usually takes 1-3 days).
3. Once approved, Twilio gives you a WhatsApp number. Point its inbound webhook at the same `/webhook` URL.
4. Set the environment variable `TWILIO_WHATSAPP_FROM=whatsapp:+<your number>`.
5. Pricing: Twilio charges per conversation depending on category; user-initiated (service) conversations are the relevant category for this bot - check Twilio's current WhatsApp pricing page before going live.

## Where your API key goes (important)

Set credentials as **environment variables on your server - never in code, never in chat, never committed to git**:

```bash
export TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxx      # from Twilio Console dashboard
export TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxx         # from Twilio Console dashboard
python3 seva_mitra_twilio.py
```

On Render/Railway: paste them in the service's **Environment** settings.

What each one does in this server:

| Variable | Used for | Needed for sandbox testing? |
|---|---|---|
| `TWILIO_AUTH_TOKEN` | Validates the `X-Twilio-Signature` header so only Twilio can call your webhook | Recommended (security), not required |
| `TWILIO_ACCOUNT_SID` | Outbound REST sends (`send_whatsapp()`) for future proactive updates | No |
| `TWILIO_WHATSAPP_FROM` | Your production sender number | No (sandbox default built in) |
| `PORT` | Listen port | Host-dependent |

Note: with signature validation ON behind a proxy (ngrok, Render), if you get `403 invalid signature`, the proxy rewrites the Host header - keep the Host header intact or run validation off during testing.

## Security and data checklist before real citizens use it

- Signature validation ON (`TWILIO_AUTH_TOKEN` set).
- HTTPS everywhere (ngrok / hosts provide this).
- `cases.json` stores names, districts and case data - restrict access, back it up, delete old cases; align retention with the blueprint's privacy section (DPDP Act).
- Re-verify all scheme amounts against sspensions.ap.gov.in and cheyutha.telangana.gov.in before public launch.
- Add the human-escalation path (the console from the blueprint) before promising 10 AM - 6 PM agent support.

## What is not in this version (by design)

- Free-form understanding - the bot uses numbered menus (an LLM can be added behind `handle()` later).
- Real document photo inspection - a photo message is accepted as the expected document without checking legibility.
- Proactive outbound updates - `send_whatsapp()` is included and ready, but the notification scheduler and approved templates come later.
- Voice notes arrive as media and are treated as a photo of the current document.
