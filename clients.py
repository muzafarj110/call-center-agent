"""
clients.py
==========
Per-client config registry for the multi-business platform.

Each WhatsApp number you connect (Meta "phone_number_id") belongs to ONE
client. This module maps an incoming phone_number_id -> that client's
ClientConfig (the 8 onboarding fields), so the same Flask app can serve many
businesses at once.

Registry source: a JSON file (clients.json) that your dashboard writes to.
Format:

{
  "<phone_number_id>": {
    "business_type": "baqala",
    "business_name": "Daily Fresh Vegetables & Fruits",
    "products": "",                 // optional; usually loaded live from Sheet
    "working_hours": "8:00 AM - 11:00 PM",
    "delivery_charge": 5,
    "escalation_number": "+971500000000",
    "language": "both",
    "sheet_id": "1AbC...",
    "currency": "AED"
  },
  "<another_phone_number_id>": { ... }
}

The file is cached in memory and reloaded automatically when it changes on
disk, so the dashboard can onboard a new client with no redeploy.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from business_config import ClientConfig

CLIENTS_FILE = os.environ.get("CLIENTS_FILE", "clients.json")

_lock = threading.Lock()
_cache: dict[str, ClientConfig] = {}
_raw_cache: dict[str, dict] = {}   # phone_number_id -> raw onboarding dict
_cache_mtime: float = 0.0


def _build(raw: dict) -> None:
    """Parse a raw registry dict into the caches."""
    global _cache, _raw_cache
    registry: dict[str, ClientConfig] = {}
    raw_registry: dict[str, dict] = {}
    for phone_number_id, data in raw.items():
        try:
            registry[str(phone_number_id)] = ClientConfig.from_dict(data)
            raw_registry[str(phone_number_id)] = data
        except ValueError as exc:
            # Skip malformed client rows but keep the platform running.
            print(f"[clients] skipping {phone_number_id}: {exc}")
    _cache = registry
    _raw_cache = raw_registry


def _load_registry() -> dict[str, ClientConfig]:
    """Load the client registry, cached.

    Source priority:
      1. clients.json file (hot-reloaded on change via mtime) — best for local
         dev and when the dashboard writes the file.
      2. CLIENTS_JSON env var (raw JSON string) — best for Railway, keeps the
         WhatsApp tokens out of git. Parsed once and cached.
    """
    global _cache_mtime
    with _lock:
        # 1) File source (preferred when present).
        try:
            mtime = os.path.getmtime(CLIENTS_FILE)
            if mtime != _cache_mtime or not _cache:
                with open(CLIENTS_FILE, "r", encoding="utf-8") as fh:
                    _build(json.load(fh))
                _cache_mtime = mtime
            return _cache
        except OSError:
            pass  # no file -> try env

        # 2) Env source.
        if not _cache:
            raw_env = os.environ.get("CLIENTS_JSON")
            if raw_env:
                try:
                    _build(json.loads(raw_env))
                except json.JSONDecodeError as exc:
                    print(f"[clients] CLIENTS_JSON parse error: {exc}")
        return _cache


def get_client(phone_number_id: str) -> Optional[ClientConfig]:
    """Return the ClientConfig for an incoming WhatsApp phone_number_id."""
    registry = _load_registry()
    return registry.get(str(phone_number_id))


def all_phone_number_ids() -> list[str]:
    return list(_load_registry().keys())


def get_whatsapp_token(phone_number_id: str) -> str:
    """Per-client WhatsApp token, falling back to the global env token."""
    _load_registry()
    raw = _raw_cache.get(str(phone_number_id), {})
    return raw.get("whatsapp_token") or os.environ.get("WHATSAPP_TOKEN", "")


def get_raw(phone_number_id: str) -> dict:
    _load_registry()
    return _raw_cache.get(str(phone_number_id), {})


def reload_clients() -> int:
    """Force a reload (e.g. after the dashboard onboards a client)."""
    global _cache_mtime, _cache, _raw_cache
    _cache_mtime = 0.0
    _cache = {}
    _raw_cache = {}
    return len(_load_registry())
