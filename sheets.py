"""
sheets.py
=========
Google Sheets data layer (per client).

Each client has their own Google Sheet (cfg.sheet_id) with these tabs:
  - Products    : item catalog / menu / services / available slots
  - Orders      : confirmed orders / bookings / leads (one row each)
  - Customers   : remembered customers + saved delivery addresses

Key behaviors (per our architecture):
  - Product/menu reads are CACHED for 5 minutes per sheet to avoid Google
    Sheet timeouts and rate limits.
  - Customer delivery addresses are remembered and reused.
  - Orders/bookings/leads are appended with a generated ID.

Auth: a Google service account. Provide the JSON either as:
  - GOOGLE_CREDENTIALS_JSON  (the raw JSON string, recommended on Railway), or
  - GOOGLE_APPLICATION_CREDENTIALS (path to a json file)
The service account email must be shared (Editor) on each client's Sheet.
"""

from __future__ import annotations

import json
import os
import time
import threading
from datetime import datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]

PRODUCTS_TAB = "Products"
ORDERS_TAB = "Orders"
CUSTOMERS_TAB = "Customers"
SLOTS_TAB = "Slots"  # optional, for appointment businesses

PRODUCT_CACHE_TTL = 300  # 5 minutes

_lock = threading.Lock()
_gc: Optional[gspread.Client] = None
_product_cache: dict[str, tuple[float, list[dict]]] = {}  # sheet_id -> (ts, rows)


# ---------------------------------------------------------------------------
# Auth / client
# ---------------------------------------------------------------------------
def _get_gspread() -> gspread.Client:
    global _gc
    with _lock:
        if _gc is not None:
            return _gc
        raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        if raw:
            info = json.loads(raw)
            creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        else:
            path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
            if not path:
                raise RuntimeError(
                    "No Google credentials. Set GOOGLE_CREDENTIALS_JSON or "
                    "GOOGLE_APPLICATION_CREDENTIALS."
                )
            creds = Credentials.from_service_account_file(path, scopes=_SCOPES)
        _gc = gspread.authorize(creds)
        return _gc


def _open(sheet_id: str):
    return _get_gspread().open_by_key(sheet_id)


def _worksheet(sheet_id: str, title: str):
    """Get a worksheet, creating it with no rows if it does not exist."""
    sh = _open(sheet_id)
    try:
        return sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=1000, cols=26)


# ---------------------------------------------------------------------------
# Products / menu / services (cached)
# ---------------------------------------------------------------------------
def get_products(sheet_id: str, force: bool = False) -> list[dict]:
    """Return product rows as list of dicts (header row drives keys).

    Cached for PRODUCT_CACHE_TTL seconds per sheet.
    """
    now = time.time()
    if not force:
        cached = _product_cache.get(sheet_id)
        if cached and (now - cached[0]) < PRODUCT_CACHE_TTL:
            return cached[1]
    try:
        rows = _worksheet(sheet_id, PRODUCTS_TAB).get_all_records()
    except Exception as exc:  # network/timeout -> serve stale cache if any
        print(f"[sheets] product fetch failed for {sheet_id}: {exc}")
        cached = _product_cache.get(sheet_id)
        return cached[1] if cached else []
    _product_cache[sheet_id] = (now, rows)
    return rows


def products_as_text(sheet_id: str, force: bool = False) -> str:
    """Format the product/menu rows as readable lines for the system prompt.

    Tries common column names; falls back to dumping all columns.
    """
    rows = get_products(sheet_id, force=force)
    if not rows:
        return ""
    lines = []
    for r in rows:
        lc = {str(k).strip().lower(): v for k, v in r.items()}
        name = lc.get("name") or lc.get("item") or lc.get("product") or lc.get("service")
        price = lc.get("price") or lc.get("rate") or lc.get("cost")
        unit = lc.get("unit") or lc.get("uom") or ""
        stock = lc.get("stock") or lc.get("qty") or lc.get("availability")
        if name is None:
            # Unknown schema: dump the row
            lines.append(", ".join(f"{k}: {v}" for k, v in r.items() if str(v).strip()))
            continue
        parts = [str(name).strip()]
        if price not in (None, ""):
            parts.append(f"- {price}{('/' + str(unit)) if unit else ''}")
        if stock not in (None, ""):
            parts.append(f"({stock})")
        lines.append(" ".join(parts))
    return "\n".join(lines)


def slots_as_text(sheet_id: str) -> str:
    """Available appointment slots for hospital/clinic businesses."""
    try:
        rows = _worksheet(sheet_id, SLOTS_TAB).get_all_records()
    except Exception:
        return ""
    out = []
    for r in rows:
        lc = {str(k).strip().lower(): v for k, v in r.items()}
        # Only offer slots explicitly marked available
        status = str(lc.get("status", "available")).strip().lower()
        if status not in ("", "available", "open", "free"):
            continue
        out.append(", ".join(f"{k}: {v}" for k, v in r.items() if str(v).strip()))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Customer memory (addresses)
# ---------------------------------------------------------------------------
def get_customer(sheet_id: str, phone: str) -> Optional[dict]:
    try:
        rows = _worksheet(sheet_id, CUSTOMERS_TAB).get_all_records()
    except Exception as exc:
        print(f"[sheets] customer fetch failed: {exc}")
        return None
    phone = _norm_phone(phone)
    for r in rows:
        lc = {str(k).strip().lower(): v for k, v in r.items()}
        if _norm_phone(str(lc.get("phone", ""))) == phone:
            return lc
    return None


def upsert_customer(sheet_id: str, phone: str, name: str = "",
                    address: str = "") -> None:
    """Create or update a customer's saved name/address."""
    try:
        ws = _worksheet(sheet_id, CUSTOMERS_TAB)
        records = ws.get_all_records()
    except Exception as exc:
        print(f"[sheets] customer upsert failed: {exc}")
        return
    phone_n = _norm_phone(phone)
    headers = ws.row_values(1) if records or ws.row_count else []
    if not headers:
        headers = ["Phone", "Name", "Address", "UpdatedAt"]
        ws.update("A1:D1", [headers])

    # Find existing row
    for idx, r in enumerate(records, start=2):  # +2: header + 1-based
        lc = {str(k).strip().lower(): v for k, v in r.items()}
        if _norm_phone(str(lc.get("phone", ""))) == phone_n:
            new_name = name or lc.get("name", "")
            new_addr = address or lc.get("address", "")
            ws.update(f"A{idx}:D{idx}",
                      [[phone, new_name, new_addr, _now()]])
            return
    # Append new
    ws.append_row([phone, name, address, _now()],
                  value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Save order / booking / lead
# ---------------------------------------------------------------------------
def save_record(sheet_id: str, fields: list[str], data: dict,
                id_prefix: str = "ORD") -> str:
    """Append a confirmed order/booking/lead to the Orders tab.

    `fields` is the per-flow column order (from get_extraction_fields).
    Returns the generated record ID.
    """
    record_id = _gen_id(id_prefix)
    ws = _worksheet(sheet_id, ORDERS_TAB)

    header = ["ID", "Timestamp"] + fields + ["Status"]
    existing_header = ws.row_values(1)
    if existing_header != header:
        # Write/repair header (only touches row 1)
        ws.update("A1", [header])

    row = [record_id, _now()]
    for f in fields:
        val = data.get(f, "")
        if isinstance(val, (list, dict)):
            val = json.dumps(val, ensure_ascii=False)
        row.append(val)
    row.append("NEW")
    ws.append_row(row, value_input_option="USER_ENTERED")
    return record_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%y%m%d')}-{int(time.time()) % 100000}"


def _norm_phone(phone: str) -> str:
    return "".join(ch for ch in str(phone) if ch.isdigit())[-12:]
