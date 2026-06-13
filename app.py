"""
app.py
======
Flask integration layer for the AIShop multi-business WhatsApp platform.

Ties together:
  clients.py        -> which business owns the incoming WhatsApp number
  sheets.py         -> products/menu (cached), customer memory, save record
  ai.py             -> Claude reply + structured extraction
  conversation.py   -> session state + Python-owned YES/NO + escalation

Flow for each inbound message:
  1. Identify the client by phone_number_id. Unknown -> ignore.
  2. Load/250 the customer session.
  3. If customer wants a human / complains -> escalate + notify manager.
  4. If a confirmation is pending and the customer affirms -> extract + save to
     Sheet + return the record ID. If they decline -> clear pending, continue.
  5. Otherwise: fetch live products/slots (cached), build the system prompt,
     call Claude, send the reply. If Claude signals READY, mark pending.

Endpoints:
  GET  /webhook         Meta verification
  POST /webhook         Inbound messages (rate-limited)
  POST /reload-clients  Dashboard hook to reload clients.json
  GET  /health          Health check
"""

from __future__ import annotations

import os
import time
import threading

import requests
from flask import Flask, request, jsonify, abort
from flask_cors import CORS

import clients
import sheets
import ai
import conversation as conv
from business_config import (
    FLOW_ORDER, FLOW_RESTAURANT, FLOW_APPOINTMENT, FLOW_LEAD,
    get_extraction_fields,
)

app = Flask(__name__)
CORS(app)

VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN", "aishop_verify")
GRAPH_URL = "https://graph.facebook.com/v20.0"

# ID prefix per flow family for generated record IDs.
_ID_PREFIX = {
    FLOW_ORDER: "ORD",
    FLOW_RESTAURANT: "ORD",
    FLOW_APPOINTMENT: "APT",
    FLOW_LEAD: "LEAD",
}

# ---------------------------------------------------------------------------
# Tiny in-memory rate limiter (per WhatsApp sender)
# ---------------------------------------------------------------------------
_RL_LOCK = threading.Lock()
_RL_HITS: dict[str, list[float]] = {}
RL_MAX = int(os.environ.get("RATE_LIMIT_MAX", "20"))     # messages
RL_WINDOW = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))  # seconds


def _rate_limited(key: str) -> bool:
    now = time.time()
    with _RL_LOCK:
        hits = [t for t in _RL_HITS.get(key, []) if now - t < RL_WINDOW]
        if len(hits) >= RL_MAX:
            _RL_HITS[key] = hits
            return True
        hits.append(now)
        _RL_HITS[key] = hits
        return False


# ---------------------------------------------------------------------------
# WhatsApp Cloud API send
# ---------------------------------------------------------------------------
def send_whatsapp(phone_number_id: str, to: str, text: str) -> None:
    token = clients.get_whatsapp_token(phone_number_id)
    if not token:
        print(f"[wa] no token for {phone_number_id}; cannot send")
        return
    url = f"{GRAPH_URL}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text[:4096]},
    }
    try:
        r = requests.post(
            url, json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        if r.status_code >= 300:
            print(f"[wa] send failed {r.status_code}: {r.text[:300]}")
    except requests.RequestException as exc:
        print(f"[wa] send error: {exc}")


# ---------------------------------------------------------------------------
# Webhook verification (GET)
# ---------------------------------------------------------------------------
@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge or "", 200
    abort(403)


# ---------------------------------------------------------------------------
# Webhook receive (POST)
# ---------------------------------------------------------------------------
@app.post("/webhook")
def receive():
    data = request.get_json(silent=True) or {}
    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                metadata = value.get("metadata", {})
                phone_number_id = metadata.get("phone_number_id", "")
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        # Politely handle non-text once.
                        _maybe_handle_non_text(phone_number_id, msg)
                        continue
                    _handle_text(phone_number_id, msg, value)
    except Exception as exc:  # never 500 back to Meta -> avoids retries storm
        print(f"[webhook] error: {exc}")
    return jsonify({"status": "ok"}), 200


def _maybe_handle_non_text(phone_number_id: str, msg: dict) -> None:
    cfg = clients.get_client(phone_number_id)
    if not cfg:
        return
    wa_id = msg.get("from", "")
    if _rate_limited(f"{phone_number_id}:{wa_id}"):
        return
    note = ("Please send your request as a text message and I'll help right away."
            if cfg.language != "arabic"
            else "الرجاء إرسال طلبك كرسالة نصية وسأساعدك فوراً.")
    send_whatsapp(phone_number_id, wa_id, note)


def _handle_text(phone_number_id: str, msg: dict, value: dict) -> None:
    cfg = clients.get_client(phone_number_id)
    if not cfg:
        print(f"[webhook] no client for phone_number_id={phone_number_id}")
        return

    wa_id = msg.get("from", "")
    body = (msg.get("text", {}) or {}).get("body", "").strip()
    if not wa_id or not body:
        return

    if _rate_limited(f"{phone_number_id}:{wa_id}"):
        send_whatsapp(phone_number_id, wa_id,
                      "You're sending messages too fast — one moment please."
                      if cfg.language != "arabic"
                      else "أنت ترسل الرسائل بسرعة كبيرة — لحظة من فضلك.")
        return

    sess = conv.get_session(phone_number_id, wa_id)

    # Pull remembered customer info once per session.
    if not sess.history:
        existing = sheets.get_customer(cfg.sheet_id, wa_id)
        if existing:
            sess.customer_name = existing.get("name", "")
            sess.saved_address = existing.get("address", "")

    sess.add("user", body)

    # 1) Escalation: complaint / human handoff -------------------------------
    if conv.wants_human(body):
        _escalate(cfg, phone_number_id, wa_id, body)
        return

    # 2) Pending confirmation -> Python owns YES/NO --------------------------
    if sess.pending_confirmation:
        if conv.is_affirmative(body):
            _finalize(cfg, phone_number_id, wa_id, sess)
            return
        if conv.is_negative(body):
            sess.pending_confirmation = False
            # fall through: let the AI help them edit
        else:
            # Ambiguous reply while pending -> ask for a clear yes/no.
            ask = ("Shall I confirm this? Please reply YES to confirm or NO to change."
                   if cfg.language != "arabic"
                   else "هل أؤكد الطلب؟ اكتب نعم للتأكيد أو لا للتعديل.")
            sess.add("assistant", ask)
            send_whatsapp(phone_number_id, wa_id, ask)
            return

    # 3) Normal turn: build prompt with live data, call Claude ---------------
    items_text = ""
    slots_text = ""
    if cfg.flow_family == FLOW_APPOINTMENT:
        items_text = sheets.products_as_text(cfg.sheet_id)  # specialties/services
        slots_text = sheets.slots_as_text(cfg.sheet_id)
    else:
        items_text = sheets.products_as_text(cfg.sheet_id)

    # Give the model the remembered address as context.
    sys_prompt = ai.build_system_prompt(cfg, items_text=items_text,
                                        slots_text=slots_text)
    if sess.saved_address:
        sys_prompt += (f"\n\nREMEMBERED for this customer — name: "
                       f"{sess.customer_name or 'unknown'}, saved delivery "
                       f"address: {sess.saved_address}. Offer to reuse it "
                       f"instead of asking again.")

    try:
        reply_text, ready = ai.reply(cfg, sess.history, sys_prompt)
    except Exception as exc:
        print(f"[ai] reply failed: {exc}")
        reply_text, ready = (
            "Sorry, I'm having a brief technical issue. Please try again in a moment."
            if cfg.language != "arabic"
            else "عذراً، هناك مشكلة تقنية بسيطة. حاول مرة أخرى بعد لحظات.",
            False,
        )

    sess.pending_confirmation = ready
    sess.add("assistant", reply_text)

    # Remember a freshly-given delivery address.
    if cfg.has_delivery and conv.looks_like_address(body):
        sess.saved_address = body
        sheets.upsert_customer(cfg.sheet_id, wa_id,
                               name=sess.customer_name, address=body)

    send_whatsapp(phone_number_id, wa_id, reply_text)


# ---------------------------------------------------------------------------
# Finalize a confirmed record (second Claude call + save)
# ---------------------------------------------------------------------------
def _finalize(cfg, phone_number_id: str, wa_id: str, sess: conv.Session) -> None:
    try:
        record = ai.extract_record(cfg, sess.history)
    except Exception as exc:
        print(f"[finalize] extraction failed: {exc}")
        record = {}

    # Ensure phone is captured.
    if "phone" in record and not record.get("phone"):
        record["phone"] = wa_id

    fields = get_extraction_fields(cfg)
    prefix = _ID_PREFIX.get(cfg.flow_family, "ORD")
    try:
        record_id = sheets.save_record(cfg.sheet_id, fields, record, id_prefix=prefix)
    except Exception as exc:
        print(f"[finalize] save failed: {exc}")
        msg = ("I couldn't save that just now — our team has been notified. "
               "Please try again shortly."
               if cfg.language != "arabic"
               else "تعذّر حفظ الطلب الآن — تم إبلاغ فريقنا. حاول مرة أخرى بعد قليل.")
        send_whatsapp(phone_number_id, wa_id, msg)
        return

    # Remember customer name/address from the record.
    name = record.get("customer_name") or record.get("patient_name") or sess.customer_name
    addr = record.get("delivery_address") or sess.saved_address
    if name or addr:
        sheets.upsert_customer(cfg.sheet_id, wa_id, name=name, address=addr)

    # Confirmation message per flow + language.
    if cfg.flow_family == FLOW_APPOINTMENT:
        msg_en = (f"✅ Your appointment is booked! Booking ID: {record_id}. "
                  f"You'll get a reminder before your appointment.")
        msg_ar = (f"✅ تم حجز موعدك! رقم الحجز: {record_id}. "
                  f"سنرسل لك تذكيراً قبل الموعد.")
    elif cfg.flow_family == FLOW_LEAD:
        msg_en = (f"✅ Got it! Your reference is {record_id}. "
                  f"Our team will contact you shortly.")
        msg_ar = (f"✅ تم! رقمك المرجعي: {record_id}. "
                  f"سيتواصل معك فريقنا قريباً.")
    else:
        msg_en = (f"✅ Order confirmed! Your Order ID is {record_id}. "
                  f"Thank you for ordering from {cfg.business_name}.")
        msg_ar = (f"✅ تم تأكيد طلبك! رقم الطلب: {record_id}. "
                  f"شكراً لطلبك من {cfg.business_name}.")

    msg = msg_ar if cfg.language == "arabic" else msg_en
    sess.add("assistant", msg)
    sess.pending_confirmation = False
    # Clear cart context so the next message starts fresh, but keep memory.
    sess.history = []
    send_whatsapp(phone_number_id, wa_id, msg)


# ---------------------------------------------------------------------------
# Escalation
# ---------------------------------------------------------------------------
def _escalate(cfg, phone_number_id: str, wa_id: str, body: str) -> None:
    customer_msg = ("I'm connecting you to our manager who'll help you shortly. "
                    "Thank you for your patience."
                    if cfg.language != "arabic"
                    else "سأقوم بتحويلك إلى المدير لمساعدتك قريباً. شكراً لصبرك.")
    send_whatsapp(phone_number_id, wa_id, customer_msg)

    if cfg.escalation_number:
        notify = (f"⚠️ Escalation for {cfg.business_name}\n"
                  f"Customer: {wa_id}\nMessage: {body}")
        send_whatsapp(phone_number_id, cfg.escalation_number, notify)


# ---------------------------------------------------------------------------
# Dashboard + health
# ---------------------------------------------------------------------------
@app.post("/reload-clients")
def reload_clients():
    # Protect with a shared secret if exposed publicly.
    secret = os.environ.get("ADMIN_SECRET")
    if secret and request.headers.get("X-Admin-Secret") != secret:
        abort(403)
    count = clients.reload_clients()
    return jsonify({"reloaded": count})


@app.get("/health")
def health():
    return jsonify({"status": "ok", "clients": len(clients.all_phone_number_ids())})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
