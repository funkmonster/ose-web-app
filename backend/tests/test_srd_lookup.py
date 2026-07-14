"""Tests for utils/srd_lookup.py — the in-memory SRD keyword search index."""

from utils.srd_lookup import SrdIndex, SrdSection, format_srd_context


def make_index():
    sections = [
        SrdSection(
            title="Turn Undead",
            content="A Cleric may attempt to turn undead creatures, causing them to flee.",
            url="https://example.test/srd/Turn_Undead",
        ),
        SrdSection(
            title="Saving Throws",
            content="Roll a d20 equal to or greater than the target save to avoid the effect.",
            url="https://example.test/srd/Saving_Throws",
        ),
        SrdSection(
            title="Encumbrance",
            content="Track the gear a character carries; heavy loads reduce movement rate.",
            url="https://example.test/srd/Encumbrance",
        ),
    ]
    return SrdIndex(sections)


def test_search_returns_best_matching_section():
    index = make_index()
    results = index.search("I try to turn the undead skeletons with my holy symbol")
    assert results
    assert results[0].title == "Turn Undead"


def test_search_returns_nothing_for_unrelated_query():
    index = make_index()
    results = index.search("I look around the room")
    assert results == []


def test_search_respects_top_k():
    index = make_index()
    results = index.search("undead save throw movement gear", top_k=1)
    assert len(results) <= 1


def test_format_srd_context_empty():
    assert format_srd_context([]) == ""


def test_format_srd_context_includes_title_and_url():
    index = make_index()
    section = index.sections[0]
    text = format_srd_context([section])
    assert "Turn Undead" in text
    assert section.url in text
    assert "SRD REFERENCE" in text
