"""Offline feature tests for daily_fresh.py (uses stub flask/pymongo/anthropic).

Run: python3 test_harness.py
Tests behaviour, not internal names, so it works before AND after fixes.
"""
import os
import re
import sys

# stubs first, then the project dir
STUBS = os.path.join(os.path.dirname(__file__), "_stubs")
PROJECT = os.environ.get("PROJECT_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, STUBS)
sys.path.insert(0, PROJECT)

os.environ.setdefault("MONGODB_URI", "mongodb://stub/aishop")
os.environ.setdefault("ADMIN_SECRET", "s3cret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test")
os.chdir("/tmp")  # avoid loading the project's .env

import daily_fresh as df  # noqa: E402
from flask import request, HTTPAbort  # noqa: E402

AR = re.compile(r"[؀-ۿ]")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


# ---- capture outbound ----
OUT = []
df.deliver = lambda cfg, to, text: OUT.append((to, text))
SENT = []
df.send_whatsapp = lambda pnid, to, text: SENT.append((pnid, to, text))


def mk_cfg(language="both", flow_type="grocery", delivery=10.0):
    cfg = df.ClientConfig.from_dict({
        "business_name": "Test Biz", "business_type": flow_type,
        "language": language, "delivery_charge": delivery,
        "escalation_number": "971500000000",
    })
    cfg.client_id = "t1"
    return cfg


def reset_state():
    OUT.clear(); SENT.clear()
    df._sessions.clear()
    try:
        df._get_db().customers.docs.clear()
        df._get_db().orders.docs.clear()
        df._get_db().messages.docs.clear()
    except Exception:
        pass


# ============ PURE LOGIC ============
ct, ff = df.normalize_business_type("pharmacy")
check("normalize pharmacy->order", ff == "order" and ct == "pharmacy")
ct, ff = df.normalize_business_type("عيادة")
check("normalize عيادة->appointment", ff == "appointment")
ct, ff = df.normalize_business_type("spaceship dealership")
check("normalize unknown->lead", ff == "lead")

check("lang both", df.normalize_language("Both") == "both")
check("lang arabic", df.normalize_language("arabic") == "arabic")

check("affirm yes", df.is_affirmative("yes"))
check("affirm نعم", df.is_affirmative("نعم"))
check("affirm no=false", not df.is_affirmative("no"))
check("negative غلط", df.is_negative("غلط"))

# BUG P2-4: "غلط" (wrong) should NOT trigger human escalation
check("'غلط' does NOT escalate", not df.wants_human("غلط"))
check("'manager' escalates", df.wants_human("I want a manager"))
check("'refund' escalates", df.wants_human("I need a refund"))

# BUG P1-4: a normal order line must not be mistaken for an address
check("order line not an address",
      not df.looks_like_address("I want 2 kg tomatoes and 3 onions please"))
check("real address detected",
      df.looks_like_address("Villa 12, Jumeirah Street, near the mall"))


# ============ HANDLER FLOW ============
# P1-5: 'both' client + English customer -> English-only system messages
reset_state()
cfg = mk_cfg(language="both")
df.ai_reply = lambda c, h, s: ("Here is your summary: 2kg tomatoes. Total 20 AED.", True)
df.extract_record = lambda c, h: {"items": "2kg tomatoes", "total": "20"}
df._handle_text(cfg, "chan", "971559999999", "I want 2 kg tomatoes")
df._handle_text(cfg, "chan", "971559999999", "yes")
confirm = OUT[-1][1] if OUT else ""
check("EN customer (both) -> English confirm", "Order" in confirm or "confirmed" in confirm.lower())
check("EN customer (both) -> no Arabic in confirm", not AR.search(confirm), confirm[:60])

# P1-5: 'both' client + Arabic customer -> Arabic-only
reset_state()
cfg = mk_cfg(language="both")
df._handle_text(cfg, "chan", "971558888888", "أريد طماطم")
df._handle_text(cfg, "chan", "971558888888", "نعم")
confirm = OUT[-1][1] if OUT else ""
check("AR customer (both) -> Arabic confirm", bool(AR.search(confirm)))
check("AR customer (both) -> no English 'Order confirmed'", "Order confirmed" not in confirm, confirm[:60])

# order saved (with numeric total for analytics)
saved = df._get_db().orders.docs
check("order saved to DB", len(saved) >= 1)
check("order has numeric total_value", any(isinstance(o.get("total_value"), float) for o in saved),
      str(saved[-1]) if saved else "none")

# Escalation path
reset_state()
cfg = mk_cfg(language="english")
df._handle_text(cfg, "chan", "971557777777", "this is terrible I want a refund")
# expect: customer reply + manager notify (2 deliveries)
check("escalation sends 2 messages (customer+manager)", len(OUT) == 2, str(OUT))

# Confirmation dead-loop (P1-6): ambiguous reply while pending shouldn't dead-end
reset_state()
cfg = mk_cfg(language="english")
df.ai_reply = lambda c, h, s: ("Summary ready. Total 20. Confirm?", True)
df._handle_text(cfg, "chan", "971556666666", "2 kg onions")   # -> pending
df.ai_reply = lambda c, h, s: ("Delivery is about 45 minutes.", False)  # answers a question
df._handle_text(cfg, "chan", "971556666666", "how long is delivery?")  # ambiguous
ans = OUT[-1][1]
check("ambiguous-while-pending gets a real answer (no dead-loop)",
      "Reply YES" not in ans and "نعم" not in ans, ans[:60])

# Address corruption (P1-4): order line must not be saved as the customer address
reset_state()
cfg = mk_cfg(language="english")
df.ai_reply = lambda c, h, s: ("Sure, anything else?", False)
df._handle_text(cfg, "chan", "971555555555", "I want 2 kg tomatoes and 3 onions please")
cust = df._get_db().customers.find_one({"client_id": "t1"})
check("order line NOT saved as address", not (cust and cust.get("address")), str(cust))


# ============ ENDPOINT AUTH GUARDS ============
def call(view):
    try:
        return view(), None
    except HTTPAbort as e:
        return None, e.code


# /update-order without admin secret -> must be blocked (P0-5)
request.set(method="POST", json={"order_id": "X", "status": "Done"}, headers={})
out, code = call(df.update_order)
check("/update-order blocks without admin secret", code == 403, f"code={code} out={out}")

# /escalate without secret -> blocked, and no WhatsApp sent (P0-4)
SENT.clear()
request.set(method="POST", json={"to": "9715", "message": "hi"}, headers={})
out, code = call(df.escalate)
check("/escalate blocks without admin secret", code == 403 and not SENT, f"code={code} sent={SENT}")

# /products GET without secret -> blocked (P0-6)
request.set(method="GET", args={"client_id": "t1"}, headers={})
out, code = call(df.products_api)
check("/products GET blocks without admin secret", code == 403, f"code={code}")

# with the secret, admin GET works
request.set(method="GET", args={"client_id": "t1"}, headers={"X-Admin-Secret": "s3cret"})
out, code = call(df.products_api)
check("/products GET works WITH admin secret", code is None and out is not None, f"code={code}")


# ============ ONBOARDING / AUTH / BILLING / CONTACT ============
import hmac as _hmac
import hashlib as _hashlib
import json as _json

# Onboarding via /onboard (no ONBOARD_KEY set -> open create)
os.environ.pop("ONBOARD_KEY", None)
df._get_db().clients.docs.clear()
request.set(method="POST", json={
    "business_name": "Al Noor Pharmacy", "business_type": "pharmacy",
    "language": "both", "delivery_charge": 10, "products": "Panadol - 12\nVitamin C - 25",
}, headers={})
out = df.onboard()
body = out[0] if isinstance(out, tuple) else out
check("/onboard creates a client", body.get("success") and body.get("client_id"), str(body)[:80])
check("/onboard seeds products", body.get("products_added", 0) == 2, str(body.get("products_added")))

# /setup requires auth
request.set(method="POST", json={"business_name": "X", "business_type": "clinic"}, headers={})
out = df.setup()
body = out[0] if isinstance(out, tuple) else out
check("/setup blocks anonymous", body.get("success") is False, str(body)[:80])

# OTP request+verify+me (dev mode enabled for the test)
os.environ["ALLOW_DEV_OTP"] = "1"
os.environ.pop("RESEND_API_KEY", None)
df._get_db().otps.docs.clear()
request.set(method="POST", json={"email": "owner@test.com"}, headers={})
out = df.auth_request_otp()
body = out[0] if isinstance(out, tuple) else out
code = body.get("dev_code")
check("/auth/request-otp dev code returned (ALLOW_DEV_OTP=1)", bool(code), str(body)[:80])
request.set(method="POST", json={"email": "owner@test.com", "code": code}, headers={})
out = df.auth_verify_otp()
body = out[0] if isinstance(out, tuple) else out
tok = body.get("token")
check("/auth/verify-otp returns a token", bool(tok))
request.set(method="GET", args={}, headers={"Authorization": "Bearer " + (tok or "")})
me = df.auth_me()
me = me[0] if isinstance(me, tuple) else me
check("/auth/me resolves the signed-in email", me.get("email") == "owner@test.com", str(me)[:80])

# OTP with dev disabled and no email provider -> blocked (no account takeover)
os.environ.pop("ALLOW_DEV_OTP", None)
request.set(method="POST", json={"email": "attacker@test.com"}, headers={})
out = df.auth_request_otp()
sc = out[1] if isinstance(out, tuple) else 200
body = out[0] if isinstance(out, tuple) else out
check("/auth/request-otp blocked when email unconfigured", body.get("success") is False and sc == 503,
      f"{sc} {body}")

# Billing webhook signature
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
df.STRIPE_WEBHOOK_SECRET = "whsec_test"
df._get_db().users.docs.clear()
df.ensure_user("payer@test.com")
payload = _json.dumps({"type": "checkout.session.completed",
                       "data": {"object": {"client_reference_id": "payer@test.com",
                                           "metadata": {"plan": "pro"}}}})
raw = payload.encode()
good = "t=1,v1=" + _hmac.new(b"whsec_test", b"1." + raw, _hashlib.sha256).hexdigest()
request.set(method="POST", json=_json.loads(payload), headers={"Stripe-Signature": good}, data=raw)
out = df.billing_webhook()
sc = out[1] if isinstance(out, tuple) else 200
u = df._get_db().users.find_one({"email": "payer@test.com"})
check("billing webhook valid sig -> plan active", sc == 200 and u and u.get("plan") == "pro", str(u)[:80])
request.set(method="POST", json=_json.loads(payload), headers={"Stripe-Signature": "t=1,v1=deadbeef"}, data=raw)
out = df.billing_webhook()
sc = out[1] if isinstance(out, tuple) else 200
check("billing webhook bad sig -> 400", sc == 400, str(sc))
os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
df.STRIPE_WEBHOOK_SECRET = ""

# Contact form saves
df._get_db().contacts.docs.clear()
request.set(method="POST", json={"name": "Sam", "email": "sam@test.com", "message": "hi"}, headers={})
out = df.contact()
body = out[0] if isinstance(out, tuple) else out
check("/contact saves submission", body.get("success") and df._get_db().contacts.count_documents({}) == 1)


# ============ ENQUIRY PAGE (call / whatsapp auto-respond) ============
import types as _types
df._get_db().clients.docs.clear()
df._get_db().clients.insert_one({"client_id": "t1", "business_type": "grocery",
                                 "business_name": "Test Biz", "language": "both",
                                 "transport": "meta", "phone_number_id": "123"})
df._get_db().enquiries.docs.clear()

# WhatsApp channel -> auto-reply via deliver()
OUT.clear()
request.set(method="POST", json={"name": "Sam", "phone": "971501234567",
            "message": "Do you deliver?", "channel": "whatsapp", "client_id": "t1"}, headers={})
out = df.enquiry()
body = out[0] if isinstance(out, tuple) else out
check("enquiry(whatsapp) responds via WhatsApp", body.get("responded") and OUT and OUT[-1][0] == "971501234567",
      str(body)[:80])
check("enquiry saved to DB", df._get_db().enquiries.count_documents({}) == 1)

# Call channel, Twilio NOT configured -> pending
for a in ("TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM"):
    setattr(df, a, "")
request.set(method="POST", json={"name": "Lina", "phone": "971559876543",
            "message": "اتصلوا بي", "channel": "call", "client_id": "t1"}, headers={})
out = df.enquiry()
body = out[0] if isinstance(out, tuple) else out
check("enquiry(call) without Twilio -> pending, not responded",
      body.get("success") and body.get("responded") is False and "TWILIO" in body.get("note", ""),
      str(body)[:90])

# Call channel, Twilio configured -> places the call (mock HTTP)
df.TWILIO_SID, df.TWILIO_TOKEN, df.TWILIO_FROM = "AC1", "tok", "+15550001111"
_real_requests = df.requests
df.requests = _types.SimpleNamespace(
    post=lambda *a, **k: _types.SimpleNamespace(status_code=201, text="ok"))
request.set(method="POST", json={"name": "Lina", "phone": "971559876543",
            "message": "call me", "channel": "call", "client_id": "t1"}, headers={})
out = df.enquiry()
body = out[0] if isinstance(out, tuple) else out
check("enquiry(call) with Twilio -> call placed", body.get("responded") is True, str(body)[:80])
df.requests = _real_requests
df.TWILIO_SID = df.TWILIO_TOKEN = df.TWILIO_FROM = ""


# ============ /my/use-sandbox (flip business to Zernio) ============
df._get_db().clients.docs.clear()
df.ensure_user("sb@test.com")
_act, scid = df.upsert_client_db({"business_name": "SB Biz", "business_type": "grocery", "language": "both"})
df.set_user_client("sb@test.com", scid)
sbtok = df.create_session("sb@test.com")
request.set(method="POST", args={}, headers={"Authorization": "Bearer " + sbtok})
out = df.my_use_sandbox()
body = out[0] if isinstance(out, tuple) else out
cdoc = df._get_db().clients.find_one({"client_id": scid})
check("/my/use-sandbox flips business to zernio + auto_bind",
      body.get("success") and cdoc.get("transport") == "zernio" and body.get("auto_bind") is True,
      str(body)[:90])


# ============ sandbox binds to the PENDING business (multi-Zernio) ============
import time as _time, json as _json2
df.ZERNIO_WEBHOOK_SECRET = ""
df.ai_reply = lambda c, h, s: ("hi!", False)
df.extract_record = lambda c, h: {}
df._get_db().clients.docs.clear()
# two Zernio businesses; only B opted into sandbox just now
df._get_db().clients.insert_one({"client_id": "A", "business_type": "grocery", "business_name": "A Biz",
                                 "transport": "zernio", "status": "active"})
df._get_db().clients.insert_one({"client_id": "B", "business_type": "clinic", "business_name": "B Biz",
                                 "transport": "zernio", "status": "active",
                                 "sandbox_pending_at": _time.time()})
df.reload_clients()
payload = {"event": "message.received",
           "account": {"id": "ACCT_NEW"},
           "message": {"sender": {"id": "971500000001"}, "text": "hello", "conversationId": "c1"}}
raw = _json2.dumps(payload).encode()
request.set(method="POST", json=payload, headers={}, data=raw)
df.zernio_webhook()
_time.sleep(0.2)
a = df._get_db().clients.find_one({"client_id": "A"})
b = df._get_db().clients.find_one({"client_id": "B"})
check("sandbox binds to the PENDING business (B), not A",
      b.get("zernio_account_id") == "ACCT_NEW" and not a.get("zernio_account_id"),
      f"A={a.get('zernio_account_id')} B={b.get('zernio_account_id')}")


# ============ REPORT ============
print("\n==== TEST RESULTS ====")
passed = 0
for name, ok, detail in results:
    mark = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    line = f"[{mark}] {name}"
    if not ok and detail:
        line += f"  -> {detail}"
    print(line)
print(f"\n{passed}/{len(results)} passed")
sys.exit(0 if passed == len(results) else 1)
