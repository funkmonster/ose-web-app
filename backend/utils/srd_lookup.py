"""
In-memory keyword search over the locally-cached OSE SRD snapshot
(see backend/scripts/build_srd_cache.py), used to ground the GM's rule
adjudications instead of letting the LLM guess rules from memory.
"""

import math
import re
from dataclasses import dataclass

import aiosqlite

_TOKEN_RE = re.compile(r"[a-z0-9']+")

_STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "is",
    "are", "was", "were", "be", "been", "it", "its", "you", "your", "i", "my",
    "me", "do", "does", "with", "as", "by", "this", "that", "into", "from",
}

# Below this score, a query is treated as having no relevant SRD match —
# keeps generic actions ("I look around") from dragging in noise.
_MIN_SCORE = 5.5


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


@dataclass
class SrdSection:
    title: str
    content: str
    url: str


class SrdIndex:
    def __init__(self, sections: list[SrdSection]):
        self.sections = sections
        self._doc_terms: list[dict[str, int]] = []
        self._title_terms: list[set[str]] = []
        doc_freq: dict[str, int] = {}

        self._doc_lengths: list[int] = []
        for section in sections:
            terms = _tokenize(f"{section.title} {section.content}")
            counts: dict[str, int] = {}
            for term in terms:
                counts[term] = counts.get(term, 0) + 1
            self._doc_terms.append(counts)
            self._title_terms.append(set(_tokenize(section.title)))
            self._doc_lengths.append(len(terms))
            for term in counts:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        n_docs = max(len(sections), 1)
        self._idf = {
            term: math.log(1 + n_docs / df) for term, df in doc_freq.items()
        }

    def search(self, query: str, top_k: int = 3) -> list[SrdSection]:
        query_terms = _tokenize(query)
        if not query_terms:
            return []

        scores = []
        for i, section in enumerate(self.sections):
            doc_terms = self._doc_terms[i]
            raw_score = sum(
                self._idf.get(term, 0) * math.log1p(doc_terms.get(term, 0))
                for term in set(query_terms)
            )
            if raw_score <= 0:
                continue
            # Penalize long/verbose pages so broad vocabulary overlap on a big
            # page (e.g. an equipment list) doesn't outrank a short, focused,
            # genuinely on-topic one.
            length_penalty = 1 + math.log1p(self._doc_lengths[i] / 100)
            score = raw_score / length_penalty

            # A query naming the section outright (a spell/monster/class name)
            # is a strong, unambiguous relevance signal — boost regardless of
            # how the rest of the page's prose happens to overlap.
            title_hits = self._title_terms[i] & set(query_terms)
            if title_hits:
                score += sum(self._idf.get(t, 0) for t in title_hits) * 2

            if score >= _MIN_SCORE:
                scores.append((score, section))

        scores.sort(key=lambda pair: pair[0], reverse=True)
        return [section for _, section in scores[:top_k]]


async def load_srd_index(path: str) -> SrdIndex:
    """Load the cached SRD snapshot from disk into memory. Empty/missing DB → empty index."""
    sections: list[SrdSection] = []
    try:
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT title, content, url FROM srd_sections"
            ) as cursor:
                async for row in cursor:
                    sections.append(
                        SrdSection(title=row["title"], content=row["content"], url=row["url"])
                    )
    except aiosqlite.OperationalError:
        pass  # cache not built yet — run backend/scripts/build_srd_cache.py
    return SrdIndex(sections)


_MAX_EXCERPT_CHARS = 800


def format_srd_context(sections: list[SrdSection]) -> str:
    if not sections:
        return ""
    lines = [
        "[SRD REFERENCE — Old School Essentials SRD. Use ONLY these excerpts when "
        "adjudicating rules; never invent or guess a rule beyond what's shown here.]"
    ]
    for section in sections:
        excerpt = section.content[:_MAX_EXCERPT_CHARS]
        lines.append(f"\n### {section.title} (source: {section.url})")
        lines.append(excerpt)
    return "\n".join(lines)
