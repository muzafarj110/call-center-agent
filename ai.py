"""
ai.py
=====
Claude API layer: the main conversation call + the structured extraction call.

Architecture rules honored here:
  - The conversation model NEVER finalizes an order/booking itself. When it has
    shown the final summary and is asking the customer to confirm, it appends a
    hidden control token. Python (app.py) sees the token, sets a pending state,
    and only saves to the Sheet after the customer affirms (the YES/NO flow is
    owned by Python, not the AI).
  - A SECOND Claude call extracts structured fields for the Sheet.

Env:
  ANTHROPIC_API_KEY   (required)
  CLAUDE_MODEL        (default: claude-opus-4-5)
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

from anthropic import Anthropic

from business_config import ClientConfig, generate_system_prompt, get_extraction_fields

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-5")
MAX_TOKENS = int(os.environ.get("CLAUDE_MAX_TOKENS", "800"))

# Hidden control token the model appends when the final summary is ready and it
# is asking the customer to confirm. Stripped before sending to WhatsApp.
READY_TOKEN = "[[READY]]"

_client: Optional[Anthropic] = None


def _anthropic() -> Anthropic:
    global _client
    if _client is None:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _client = Anthropic(api_key=key)
    return _client


# Control suffix appended to every system prompt to drive the Python-owned
# confirmation handshake.
_CONTROL_SUFFIX = f"""

CONFIRMATION HANDSHAKE (critical):
When — and only when — you have shown the customer the COMPLETE final summary
(all items/details + the final total or full booking details) and you are
asking them to confirm, end your message with the exact token {READY_TOKEN}
on its own at the very end. Do not explain the token. Do not use it at any
other time. After the customer confirms, the system saves the record and gives
you the ID to share — you do not need to save anything yourself."""


def build_system_prompt(cfg: ClientConfig, items_text: str = "",
                        slots_text: str = "") -> str:
    """Generate the full system prompt, injecting live Sheet data.

    items_text overrides cfg.products with freshly-fetched catalog/menu text.
    """
    if items_text:
        cfg.products = items_text
    base = generate_system_prompt(cfg, available_slots=slots_text)
    return base + _CONTROL_SUFFIX


def reply(cfg: ClientConfig, history: list[dict], system_prompt: str) -> tuple[str, bool]:
    """Generate the assistant reply.

    history: list of {"role": "user"|"assistant", "content": str}
    Returns (clean_text_for_whatsapp, ready_to_confirm).
    """
    resp = _anthropic().messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=history,
    )
    text = "".join(
        block.text for block in resp.content if getattr(block, "type", "") == "text"
    ).strip()

    ready = READY_TOKEN in text
    if ready:
        text = text.replace(READY_TOKEN, "").strip()
    return text, ready


_EXTRACT_INSTRUCTION = (
    "You are a data extraction tool. From the conversation, extract the "
    "confirmed order/booking/lead as STRICT JSON with exactly these keys: "
    "{fields}. Use empty string for anything not present. For 'items', return a "
    "JSON array of objects with name, qty, unit_price, line_total. Numbers must "
    "be plain numbers (no currency text). Respond with JSON ONLY — no prose, no "
    "markdown fences."
)


def extract_record(cfg: ClientConfig, history: list[dict]) -> dict:
    """Second Claude call: pull structured fields for the Sheet."""
    fields = get_extraction_fields(cfg)
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history
    )
    system = _EXTRACT_INSTRUCTION.format(fields=", ".join(fields))
    resp = _anthropic().messages.create(
        model=MODEL,
        max_tokens=600,
        system=system,
        messages=[{"role": "user", "content": transcript}],
    )
    raw = "".join(
        b.text for b in resp.content if getattr(b, "type", "") == "text"
    ).strip()
    data = _parse_json(raw)
    # Guarantee every expected field exists.
    return {f: data.get(f, "") for f in fields}


def _parse_json(raw: str) -> dict:
    """Tolerant JSON parse (handles stray fences / text around the object)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    print(f"[ai] extraction JSON parse failed: {raw[:200]}")
    return {}
