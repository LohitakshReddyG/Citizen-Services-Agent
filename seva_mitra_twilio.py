#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Seva Mitra - Twilio WhatsApp deployment server (v1.0)
=====================================================

Wraps the conversation engine from seva_mitra_prototype.py in a Twilio-native
webhook server, so you can connect it to a real WhatsApp number:

  - Accepts Twilio's form-encoded webhook POSTs (From / Body / NumMedia)
  - Replies with TwiML, so answering an inbound message needs NO API key
    (the reply rides the 24-hour customer service window)
  - Treats inbound photos (NumMedia > 0) as the document the bot is
    currently waiting for, during document collection
  - Validates X-Twilio-Signature when TWILIO_AUTH_TOKEN is set
  - Includes send_whatsapp() for future proactive updates via the Twilio
    REST API (that path DOES need TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN)

Deploy: keep seva_mitra_prototype.py next to this file, then:

    python3 seva_mitra_twilio.py            # serves on PORT (default 8787)

Environment variables (all optional for sandbox testing):

    TWILIO_AUTH_TOKEN     - if set, webhook signature validation is enforced
    TWILIO_ACCOUNT_SID    - needed only for outbound send_whatsapp() calls
    TWILIO_WHATSAPP_FROM  - your Twilio WhatsApp sender, e.g.
                            'whatsapp:+14155238886' (sandbox default)
    PORT                  - server port (default 8787)

NEVER put these values in code or in chat - only in environment variables.
"""

import base64
import hashlib
import hmac
import os
import sys
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from seva_mitra_prototype import Session, handle  # the conversation engine

TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
PORT = int(os.environ.get("PORT", "8787"))

SESSIONS = {}  # "whatsapp:+91..." -> Session


# ---------------------------------------------------------------------------
# TwiML response building
# ---------------------------------------------------------------------------
def xml_escape(text):
    A = chr(38)
    return (text.replace(A, A + 'amp;')
                .replace(chr(60), A + 'lt;')
                .replace(chr(62), A + 'gt;')
                .replace(chr(34), A + 'quot;')
                .replace(chr(39), A + 'apos;'))


def twiml(replies):
    parts = ['<?xml version="1.0" encoding="UTF-8"?><Response>']
    for r in replies:
        parts.append("<Message>{}</Message>".format(xml_escape(r)))
    parts.append("</Response>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Twilio signature validation (https://www.twilio.com/docs/usage/security)
# ---------------------------------------------------------------------------
def validate_twilio_signature(url, post_vars, signature):
    if not TWILIO_AUTH_TOKEN:
        return True  # token not configured: skip validation (testing only)
    payload = url + "".join(k + v for k, v in sorted(post_vars))
    expected = base64.b64encode(
        hmac.new(TWILIO_AUTH_TOKEN.encode(), payload.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature or "")


# ---------------------------------------------------------------------------
# Outbound sending (for future proactive updates; NOT needed for replies)
# ---------------------------------------------------------------------------
def send_whatsapp(to, text):
    """Send a message via the Twilio REST API.
    'to' must be the full 'whatsapp:+91...' address.
    Requires TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN in the environment.
    Can only be used inside the 24h window or with an approved template."""
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN):
        raise RuntimeError("Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to send outbound messages")
    data = urllib.parse.urlencode({"From": TWILIO_WHATSAPP_FROM, "To": to, "Body": text}).encode()
    req = urllib.request.Request(
        "https://api.twilio.com/2010-04-01/Accounts/{}/Messages.json".format(TWILIO_ACCOUNT_SID),
        data=data)
    cred = base64.b64encode("{}:{}".format(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN).encode()).decode()
    req.add_header("Authorization", "Basic " + cred)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status


# ---------------------------------------------------------------------------
# The webhook server
# ---------------------------------------------------------------------------
class TwilioWebhookHandler(BaseHTTPRequestHandler):
    server_version = "SevaMitra/1.0"

    def _respond(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._respond(200, "application/json",
                          b'{"status": "ok", "service": "seva-mitra-twilio"}')
        else:
            self._respond(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path != "/webhook":
            self._respond(404, "text/plain", b"not found")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
        except ValueError:
            self._respond(400, "text/plain", b"bad request")
            return

        # Twilio posts form-encoded fields: From, Body, NumMedia, ...
        if "application/x-www-form-urlencoded" in (self.headers.get("Content-Type") or ""):
            fields = dict(urllib.parse.parse_qsl(raw.decode("utf-8"), keep_blank_values=True))
        else:  # fallback for JSON testing
            try:
                import json
                obj = json.loads(raw or b"{}")
                fields = {"From": obj.get("from", ""), "Body": obj.get("text", ""),
                          "NumMedia": "1" if obj.get("media") else "0"}
            except ValueError:
                self._respond(400, "text/plain", b"bad request")
                return

        # Security: validate that the request really came from Twilio
        if TWILIO_AUTH_TOKEN:
            url = "https://{}{}".format(self.headers.get("Host", "localhost"), self.path)
            sig = self.headers.get("X-Twilio-Signature", "")
            if not validate_twilio_signature(url, sorted(fields.items()), sig):
                self._respond(403, "text/plain", b"invalid signature")
                print("[security] rejected request with bad X-Twilio-Signature")
                return

        sender = (fields.get("From") or "").strip()
        body_text = (fields.get("Body") or "").strip()
        num_media = int(fields.get("NumMedia") or 0)

        if not sender:
            self._respond(400, "text/plain", b"missing From")
            return

        # An inbound photo = the document the bot is currently waiting for
        if num_media > 0 and not body_text:
            body_text = "[photo]"
        if not body_text:
            body_text = "[media]"

        session = SESSIONS.setdefault(sender, Session())
        replies = handle(session, body_text)
        label = sender.replace("whatsapp:", "")
        print("[{}] in={!r} -> {} reply(ies)".format(label, body_text[:40], len(replies)))
        self._respond(200, "text/xml", twiml(replies).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass  # we print the essentials ourselves


def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), TwilioWebhookHandler)
    print("Seva Mitra (Twilio WhatsApp) webhook server")
    print("  listening on :{} (override with PORT env var)".format(PORT))
    print("  webhook URL for Twilio:  https://<your-public-host>:{}/webhook".format(PORT))
    print("  signature validation:    {}".format("ON" if TWILIO_AUTH_TOKEN else "OFF (set TWILIO_AUTH_TOKEN to enable)"))
    print("  outbound REST send:      {}".format("ready" if TWILIO_ACCOUNT_SID else "not configured (only needed for proactive messages)"))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nserver stopped")


if __name__ == "__main__":
    main()
