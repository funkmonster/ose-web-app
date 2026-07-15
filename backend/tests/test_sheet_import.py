"""
Tests for utils/sheet_import.py — parsing a code-generated OSE character
sheet PDF's AcroForm fields into a character-create prefill.

`_fields_to_prefill` is tested directly against a field dict shaped like
the real Necrotic Gnome fillable sheet (values taken from an actual filled
sheet), since building a synthetic fillable PDF isn't worth the trouble —
`parse_ose_sheet`'s own PDF-reading step is covered separately with real
PDF bytes.
"""

import pytest
from pypdf import PdfWriter

from utils.sheet_import import _fields_to_prefill, parse_ose_sheet

THIEF_FIELDS = {
    "Name 2": "Trillby Calaver",
    "Character Class 2": "Thief",
    "Alignment 2": "Neutral",
    "STR 2": "7", "INT 2": "10", "WIS 2": "9",
    "DEX 2": "12", "CON 2": "15", "CHA 2": "12",
    "Max HP 2": "2", "HP 2": "2",
    "AC 2": "12",
    "GP": "13", "PP": "1", "SP": "2", "EP": "", "CP": "",
    "Equipment": (
        "\n    Backpack, Torches (6), Rations (standard, 7 days), Rope (50'), "
        "Waterskin, Tinder box (flint & steel), Iron spikes (12)\n    "
    ),
    "Weapons and Armour": "\n    Weapons: Dagger, Crossbow, Crossbow Bolts (30)\n    Armour: Leather\n    ",
    "Notes": "",
}


def test_maps_identity_and_class():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert result["name"] == "Trillby Calaver"
    assert result["char_class"] == "Thief"


def test_maps_ability_scores():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert result["str_score"] == 7
    assert result["dex_score"] == 12
    assert result["con_score"] == 15
    assert result["int_score"] == 10
    assert result["wis_score"] == 9
    assert result["cha_score"] == 12


def test_maps_hp_and_ac():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert result["hp_max"] == 2
    assert result["ac"] == 12


def test_falls_back_to_hp_field_when_max_hp_missing():
    fields = dict(THIEF_FIELDS)
    del fields["Max HP 2"]
    result = _fields_to_prefill(fields)
    assert result["hp_max"] == 2


def test_converts_coins_to_gold_equivalent():
    result = _fields_to_prefill(THIEF_FIELDS)
    # 1 pp = 5gp, 13 gp, 2 sp = 0.2gp
    assert result["gold"] == pytest.approx(18.2)


def test_omits_gold_when_no_coin_fields_present():
    fields = dict(THIEF_FIELDS)
    for coin in ("GP", "PP", "SP", "EP", "CP"):
        fields[coin] = ""
    result = _fields_to_prefill(fields)
    assert "gold" not in result


def test_splits_inventory_respecting_parens():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert result["inventory"] == [
        "Backpack", "Torches (6)", "Rations (standard, 7 days)", "Rope (50')",
        "Waterskin", "Tinder box (flint & steel)", "Iron spikes (12)",
    ]


def test_weapons_and_armour_map_to_their_own_section():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert result["weapons_armor"] == [
        "Dagger", "Crossbow", "Crossbow Bolts (30)", "Leather",
    ]


def test_does_not_invent_spells():
    result = _fields_to_prefill(THIEF_FIELDS)
    assert "spells" not in result


def test_missing_fields_are_simply_omitted():
    result = _fields_to_prefill({"Name 2": "Solo"})
    assert result == {"name": "Solo"}


def test_parse_ose_sheet_rejects_non_pdf_bytes():
    with pytest.raises(ValueError, match="Could not read"):
        parse_ose_sheet(b"not a pdf at all")


def test_parse_ose_sheet_rejects_pdf_without_form_fields():
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    from io import BytesIO
    buf = BytesIO()
    writer.write(buf)

    with pytest.raises(ValueError, match="No fillable form fields"):
        parse_ose_sheet(buf.getvalue())
