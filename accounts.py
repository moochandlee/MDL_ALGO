"""
accounts.py — Unified account registry.

Single source of truth for account metadata (type, display order, CC dates).
Auto-discovers new accounts from Teller sync; all pages read from here.
"""

import json
from pathlib import Path
from config import settings

REGISTRY_FILE = settings.data_dir / "account_registry.json"
_LEGACY_CC_FILE = settings.data_dir / "credit_card_config.json"


def load_registry() -> dict:
    """Load the account registry. Returns {} if missing or corrupt."""
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text())
        except Exception:
            pass
    return {}


def save_registry(registry: dict):
    """Write the account registry atomically."""
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(registry, indent=2))


def _migrate_cc_config(registry: dict) -> dict:
    """One-shot: copy statement/payment dates from legacy credit_card_config.json."""
    if not _LEGACY_CC_FILE.exists():
        return registry
    try:
        old = json.loads(_LEGACY_CC_FILE.read_text())
    except Exception:
        return registry
    changed = False
    for aid, cfg in old.items():
        if aid in registry:
            sd = cfg.get("statement_day")
            pd = cfg.get("payment_due_day")
            if sd is not None:
                registry[aid]["statement_day"] = int(sd) if sd else None
                registry[aid]["payment_due_day"] = int(pd) if pd else None
                changed = True
            else:
                # Account not yet in registry — create a minimal entry
                registry[aid] = {
                    "id": aid,
                    "institution": "",
                    "name": "",
                    "type": "credit",
                    "subtype": "credit_card",
                    "display_order": _compute_next_order(registry),
                    "statement_day": int(sd) if sd else None,
                    "payment_due_day": int(pd) if pd else None,
                }
                changed = True
    if changed:
        save_registry(registry)
    return registry


def _compute_next_order(registry: dict) -> int:
    """Return the next available display_order value."""
    orders = [e.get("display_order", 0) for e in registry.values()]
    return (max(orders) + 1) if orders else 0


def sync_from_teller(teller_accounts: list[dict]) -> dict:
    """Discover new accounts from Teller API data and update names/types.

    Called by ``sync_teller()`` after fetching accounts. Idempotent.
    Returns the updated registry.
    """
    if not teller_accounts:
        return load_registry()

    registry = load_registry()
    if not registry:
        registry = _migrate_cc_config(registry)

    changed = False
    for acct in teller_accounts:
        aid = acct.get("id", "")
        if not aid:
            continue

        inst = acct.get("institution", {}).get("name", "")
        name = acct.get("name", "")
        atype = acct.get("type", "")
        subtype = acct.get("subtype", "")

        if aid not in registry:
            registry[aid] = {
                "id": aid,
                "institution": inst,
                "name": name,
                "type": atype,
                "subtype": subtype,
                "display_order": _compute_next_order(registry),
                "statement_day": None,
                "payment_due_day": None,
            }
            changed = True
        else:
            entry = registry[aid]
            if (entry.get("institution") != inst or
                entry.get("name") != name or
                entry.get("type") != atype or
                entry.get("subtype") != subtype):
                entry["institution"] = inst
                entry["name"] = name
                entry["type"] = atype
                entry["subtype"] = subtype
                changed = True

    if changed:
        save_registry(registry)

    return registry


def ensure_registry_from_balances() -> dict:
    """Backfill the registry from latest Teller balances if it's empty.

    Used by pages that need account data before the first sync has run.
    """
    registry = load_registry()
    if registry:
        return registry

    # Try migration from legacy CC config first
    registry = _migrate_cc_config({})
    if registry:
        return registry

    # Fall back to balance CSV data
    from teller_client import get_latest_balances
    bals = get_latest_balances()
    if not bals:
        return {}

    for b in bals:
        aid = b.get("account_id", "")
        if not aid or aid in registry:
            continue
        registry[aid] = {
            "id": aid,
            "institution": b.get("institution", ""),
            "name": b.get("account_name", ""),
            "type": b.get("account_type", ""),
            "subtype": b.get("subtype", ""),
            "display_order": len(registry),
            "statement_day": None,
            "payment_due_day": None,
        }

    save_registry(registry)
    return registry


def get_sorted_accounts(registry: dict = None) -> list[dict]:
    """Return all registry entries sorted by display_order."""
    if registry is None:
        registry = load_registry()
    return sorted(registry.values(), key=lambda e: e.get("display_order", 999))


# ── Manual item helpers ──────────────────────────────────────────────────────

TELLER_ID_PREFIX = "acc_"
MANUAL_TYPES = ("manual_asset", "manual_liability")


def _is_manual(key: str) -> bool:
    """Return True if this registry key is a manual item (not a Teller account)."""
    return not key.startswith(TELLER_ID_PREFIX)


def is_manual_entry(entry: dict) -> bool:
    """Return True if the registry entry is a manual item."""
    return entry.get("type", "") in MANUAL_TYPES


def get_manual_items(registry: dict = None, item_type: str = None) -> list[dict]:
    """Return manual registry entries, optionally filtered by type."""
    if registry is None:
        registry = load_registry()
    entries = [e for e in registry.values() if is_manual_entry(e)]
    if item_type:
        entries = [e for e in entries if e.get("type") == item_type]
    return sorted(entries, key=lambda e: e.get("display_order", 999))


def add_manual_item(registry: dict, item_type: str, subtype: str, name: str,
                    institution: str = "", display_order: int = None) -> dict:
    """Add a manual item to the registry and save.

    Parameters
    ----------
    registry : dict
        Current registry (modified in-place and saved).
    item_type : str
        ``"manual_asset"`` or ``"manual_liability"``.
    subtype : str
        E.g. ``"aspp"``, ``"loan"``.
    name : str
        Display name.
    institution : str
        Optional institution/label.
    display_order : int, optional
        If omitted, appended after the last entry.

    Returns
    -------
    dict
        The new entry that was added.
    """
    from uuid import uuid4
    key = subtype if subtype == "aspp" else f"{subtype}_{uuid4().hex[:8]}"
    if display_order is None:
        display_order = _compute_next_order(registry)
    entry = {
        "id": key,
        "type": item_type,
        "subtype": subtype,
        "name": name,
        "institution": institution,
        "display_order": display_order,
    }
    registry[key] = entry
    save_registry(registry)
    return entry


def remove_manual_item(registry: dict, item_id: str) -> bool:
    """Remove a manual item from the registry and save.

    Returns True if the item was found and removed.
    """
    if item_id in registry and is_manual_entry(registry[item_id]):
        del registry[item_id]
        save_registry(registry)
        return True
    return False
