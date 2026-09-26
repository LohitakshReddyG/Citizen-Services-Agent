# Seva Mitra — Citizen Services Agent Prototype (v1.0)

A WhatsApp-style citizen services assistant for **Andhra Pradesh & Telangana**, implementing the design in *Citizen Services Agent — Build Blueprint v1.0*. It answers questions about **pensions, certificates and basic taxes**, guides citizens through pension applications step by step, collects documents, issues a case reference number, and tracks application status — in **Telugu (script), romanised Telugu (Tenglish) and English**.

No API keys, installs or database needed. Pure Python 3 standard library.

---

## Run it

```bash
python3 seva_mitra_prototype.py demo    # scripted walkthrough: 4 scenarios, all 3 languages
python3 seva_mitra_prototype.py chat    # talk to it yourself in the terminal
python3 seva_mitra_prototype.py serve   # WhatsApp-style webhook server on port 8787
```

In `chat` mode: type `menu` anytime to return to the main menu, `restart` to reset, `quit` to exit.
To switch language mid-conversation, type `english`, `telugu` or `roman`.
During document collection, send a filename like `aadhaar.jpg` (simulating a photo) or the word `blur` to see the rejected-photo path; type `done` to finish early.

## What it demonstrates

| Blueprint feature | In the prototype |
|---|---|
| Language & script matching | Telugu script / romanised Telugu / English, per user |
| One-question-at-a-time application | Pension flows for old-age, widow, disability, chronic disease (AP & TS) |
| Eligibility check | Age, ration card, category document, bank account — with kind refusal and reasons |
| Scheme knowledge base | NTR Bharosa (AP) and Cheyutha (TS) amounts, offices and portals |
| Document collection | Checklist per category, per-document acknowledgement, blur-rejection path |
| Case tracking | Reference numbers (SM-1001…) saved to `cases.json`; status by milestone |
| Certificates & taxes | Income/caste/birth/residence checklists; income-tax slabs; GST thresholds |
| Guardrails | OTP/PIN warning, out-of-scope handling, human escalation, distress -> Tele-MANAS 14416 |
| Multi-user | Webhook server keeps a separate session per phone number |

## Connecting the real WhatsApp channel (later)

1. Create a WhatsApp Business Account (Meta business verification) — or take a BSP like **Gupshup** / **Twilio**, which simplifies this.
2. Get a number + display name approved, and create a sandbox/test app.
3. Expose this server publicly (e.g. `ngrok http 8787`) and set the provider's webhook URL to `https://.../webhook`.
4. The server already accepts both a simple `{"from": "+91...", "text": "..."}` payload and the full Meta Cloud API `entry[].changes[].value.messages[]` shape — adapt the reply loop to call your provider's send-message API with the returned `replies`.
5. When you get there, credentials belong in **environment variables** on your server (e.g. `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`) — never in the code or in chat.

**No keys are needed for anything in this file.** Keys only become relevant when you connect a real provider, and at that point they live in your own server's environment, not here.

## Known v1 limitations (by design)

- Rule-based understanding: numbered menu options instead of free-form NLU (add an LLM behind `handle()` in v2 — the function boundary is deliberate).
- Document "photos" are simulated with text; add a vision model check in v2.
- Status tracking is time-based simulation; integrate MeeSeva / Cheyutha / AP Seva APIs or an operator console in v2.
- Pension facts are the September-2026 snapshot from the blueprint — **re-verify against sspensions.ap.gov.in and cheyutha.telangana.gov.in before any real use**.
- Proactive notification templates (Section 7 of the blueprint) require Meta template approval — out of scope for this local prototype.

## Files

- `seva_mitra_prototype.py` — the whole agent: catalogs, knowledge base, engine, CLI, demo, webhook server
- `cases.json` — created at runtime where you run it; safe to delete
