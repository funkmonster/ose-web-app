"""
Import a code-generated Old School Essentials character sheet PDF.

These sheets (e.g. the official Necrotic Gnome fillable PDF, or any tool
built on it) are AcroForms — the values a player typed are stored as form
field data, not as scanned/handwritten marks. So instead of OCR, we read
the form fields directly: it's exact, and there's no image recognition to
get wrong.

The result is a best-effort *prefill* for the manual character-create form,
not a finished character — the caller still reviews and edits before
submitting. There's no dedicated field for spells on this template (casters
write them into a freeform notes field), so spells are intentionally left
for the player to fill in.
"""

import re
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError

_ABILITY_FIELDS = {
    "str_score": "STR 2",
    "dex_score": "DEX 2",
    "con_score": "CON 2",
    "int_score": "INT 2",
    "wis_score": "WIS 2",
    "cha_score": "CHA 2",
}

# Coin values in gold-piece equivalents, per the classic B/X exchange rate.
_COIN_TO_GP = {"PP": 5, "GP": 1, "EP": 0.5, "SP": 0.1, "CP": 0.01}

_LABEL_RE = re.compile(r"^(Weapons|Armour|Equipment)\s*:\s*", re.I)


def _split_commas(line: str) -> list[str]:
    """Split on commas, but not commas inside parentheses — so
    "Rations (standard, 7 days)" survives as one item."""
    items, current, depth = [], "", 0
    for ch in line:
        if ch == "(":
            depth += 1
            current += ch
        elif ch == ")":
            depth = max(0, depth - 1)
            current += ch
        elif ch == "," and depth == 0:
            items.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        items.append(current.strip())
    return items


def _parse_item_list(field_text: str) -> list[str]:
    items = []
    for line in (field_text or "").split("\n"):
        line = _LABEL_RE.sub("", line.strip())
        items.extend(i for i in _split_commas(line) if i)
    return items


def _fields_to_prefill(fields: dict[str, str]) -> dict:
    """Map raw AcroForm field values (by field name) to CreateCharacterRequest-
    shaped keys. Only includes keys it actually found a value for."""

    def val(name: str) -> str:
        return (fields.get(name) or "").strip()

    result: dict = {}

    name = val("Name 2")
    if name:
        result["name"] = name

    char_class = val("Character Class 2")
    if char_class:
        result["char_class"] = char_class

    for key, field_name in _ABILITY_FIELDS.items():
        raw = val(field_name)
        if raw.lstrip("-").isdigit():
            result[key] = int(raw)

    hp = val("Max HP 2") or val("HP 2")
    if hp.lstrip("-").isdigit():
        result["hp_max"] = int(hp)

    ac = val("AC 2")
    if ac.lstrip("-").isdigit():
        result["ac"] = int(ac)

    gold, any_coin = 0.0, False
    for coin, rate in _COIN_TO_GP.items():
        raw = val(coin)
        if raw:
            try:
                gold += float(raw) * rate
                any_coin = True
            except ValueError:
                pass
    if any_coin:
        result["gold"] = round(gold, 2)

    inventory = _parse_item_list(val("Equipment"))
    if inventory:
        result["inventory"] = inventory

    weapons_armor = _parse_item_list(val("Weapons and Armour"))
    if weapons_armor:
        result["weapons_armor"] = weapons_armor

    return result


def parse_ose_sheet(pdf_bytes: bytes) -> dict:
    """Extract a character-create prefill from an OSE character sheet PDF.

    Raises ValueError if the file isn't a readable PDF, or has no AcroForm
    fields (i.e. it's not a code-generated fillable sheet).
    """
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        raw_fields = reader.get_fields()
    except PdfReadError as e:
        raise ValueError(f"Could not read this file as a PDF: {e}") from e

    if not raw_fields:
        raise ValueError(
            "No fillable form fields found in this PDF. Sheet import only "
            "works with code-generated fillable OSE sheets — enter it "
            "manually below instead."
        )

    fields = {name: (f.get("/V") or "") for name, f in raw_fields.items()}
    return _fields_to_prefill(fields)
