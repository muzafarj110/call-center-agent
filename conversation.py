"""
conversation.py
===============
Per-customer session state + the keyword logic Python owns (not the AI):
  - conversation history (capped)
  - pending-confirmation flag (set when the AI emits the READY token)
  - affirmative / negative detection (EN + AR) for the YES/NO flow
  - complaint / human-handoff detection for escalation
  - simple delivery-address detection (keyword matching)

State is in-memory and keyed by (phone_number_id, customer_wa_id). For a
single Railway instance this is fine. If you scale to multiple workers, back
this with Redis — the interface stays the same.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

HISTORY_LIMIT = 20          # keep last N turns
SESSION_TTL = 60 * 60 * 6   # 6h idle expiry


@dataclass
class Session:
    history: list[dict] = field(default_factory=list)
    pending_confirmation: bool = False
    customer_name: str = ""
    saved_address: str = ""
    last_active: float = field(default_factory=time.time)

    def add(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        if len(self.history) > HISTORY_LIMIT:
            self.history = self.history[-HISTORY_LIMIT:]
        self.last_active = time.time()


_sessions: dict[str, Session] = {}


def get_session(phone_number_id: str, wa_id: str) -> Session:
    _expire()
    key = f"{phone_number_id}:{wa_id}"
    sess = _sessions.get(key)
    if sess is None:
        sess = Session()
        _sessions[key] = sess
    return sess


def reset_session(phone_number_id: str, wa_id: str) -> None:
    _sessions.pop(f"{phone_number_id}:{wa_id}", None)


def _expire() -> None:
    now = time.time()
    stale = [k for k, s in _sessions.items() if now - s.last_active > SESSION_TTL]
    for k in stale:
        _sessions.pop(k, None)


# ---------------------------------------------------------------------------
# Intent detection (Python-owned)
# ---------------------------------------------------------------------------
_AFFIRM = {
    # English
    "yes", "yep", "yeah", "yup", "ok", "okay", "okey", "confirm", "confirmed",
    "sure", "correct", "right", "go ahead", "proceed", "done", "agree",
    # Arabic
    "نعم", "ايوه", "أيوه", "اي", "أي", "تمام", "تمم", "موافق", "اوكي", "أوكي",
    "اكد", "أكد", "اكيد", "أكيد", "ماشي", "زين", "صح", "تأكيد",
}
_NEGATE = {
    "no", "nope", "nah", "cancel", "stop", "wrong", "change", "edit", "wait",
    "not yet", "لا", "لأ", "كنسل", "الغاء", "إلغاء", "غلط", "خطأ", "عدل",
    "تعديل", "مو", "مش", "بدل",
}

_ESCALATE = {
    "manager", "human", "agent", "complaint", "complain", "refund", "angry",
    "terrible", "worst", "sue", "lawyer", "speak to someone", "real person",
    "مدير", "موظف", "انسان", "إنسان", "شكوى", "أشكو", "اشتكي", "استرجاع",
    "ارجاع", "مسترجع", "زعلان", "غاضب", "سيء", "سيئ", "بكلم حد", "محامي",
}

# Words that suggest a message contains a delivery address.
_ADDRESS_HINTS = {
    "street", "st.", "road", "rd", "building", "bldg", "villa", "flat", "apt",
    "apartment", "floor", "block", "area", "near", "behind", "opposite",
    "tower", "house", "office",
    "شارع", "طريق", "بناية", "عمارة", "فيلا", "شقة", "طابق", "بلوك", "منطقة",
    "بجانب", "خلف", "مقابل", "برج", "بيت", "منزل", "حي",
}


def _norm(text: str) -> str:
    # Strip Arabic diacritics + lowercase + collapse spaces
    text = re.sub(r"[ً-ٰٟ]", "", text or "")
    return re.sub(r"\s+", " ", text.strip().lower())


def is_affirmative(text: str) -> bool:
    n = _norm(text)
    if not n:
        return False
    if n in _AFFIRM:
        return True
    # short messages that start with an affirmation word
    first = n.split()[0]
    return first in _AFFIRM and len(n.split()) <= 4


def is_negative(text: str) -> bool:
    n = _norm(text)
    return any(w in n.split() for w in _NEGATE) or n in _NEGATE


def wants_human(text: str) -> bool:
    n = _norm(text)
    return any(k in n for k in _ESCALATE)


def looks_like_address(text: str) -> bool:
    n = _norm(text)
    if any(h in n for h in _ADDRESS_HINTS):
        return True
    # Has digits and is reasonably long -> probably an address
    return len(n) >= 12 and bool(re.search(r"\d", n))
