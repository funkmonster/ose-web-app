"""
Crawl the Old School Essentials SRD (a public MediaWiki instance) into a local
SQLite cache used for grounding the GM's rule adjudications.

This is a one-time (or occasional-refresh) snapshot, not a live lookup — the
ruleset isn't expected to change. Re-running this script refreshes the cache
in place (INSERT OR REPLACE).

Usage:
    python backend/scripts/build_srd_cache.py [path/to/srd_cache.db]

Path resolution: CLI arg > SRD_DB_PATH env var > data/srd_cache.db.
"""

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from config import Config
import aiosqlite

SRD_BASE = "https://oldschoolessentials.necroticgnome.com/srd"
API_URL = f"{SRD_BASE}/api.php"
USER_AGENT = "ose-app-srd-cache/1.0 (local rules-grounding cache; one-time crawl)"
REQUEST_DELAY_SECONDS = 0.3


def _api_get(params: dict, retries: int = 3) -> dict:
    query = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{API_URL}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)


def list_all_titles() -> list[str]:
    """Enumerate every main-namespace, non-redirect article title."""
    titles = []
    apcontinue = None
    while True:
        params = {
            "action": "query", "list": "allpages", "apnamespace": 0,
            "aplimit": 50, "apfilterredir": "nonredirects", "format": "json",
        }
        if apcontinue:
            params["apcontinue"] = apcontinue
        data = _api_get(params)
        titles.extend(p["title"] for p in data.get("query", {}).get("allpages", []))
        cont = data.get("continue", {}).get("apcontinue")
        if not cont:
            break
        apcontinue = cont
        time.sleep(REQUEST_DELAY_SECONDS)
    return titles


def fetch_page_html(title: str) -> str | None:
    """
    Fetch the fully-rendered HTML body for a page (prop=text), rather than raw
    wikitext. MediaWiki expands templates itself this way — important here since
    monster/spell stat blocks (AC, HD, saves, etc.) live inside {{template|...}}
    parameters that a hand-rolled wikitext stripper would otherwise delete.
    """
    data = _api_get({
        "action": "parse", "page": title, "prop": "text",
        "redirects": 1, "format": "json",
    })
    parse = data.get("parse")
    if not parse:
        return None
    return parse.get("text", {}).get("*", "")


_BLOCK_TAGS = {"p", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
_SKIP_TAGS = {"script", "style"}


class _WikiHTMLTextExtractor(HTMLParser):
    """
    Converts rendered MediaWiki article HTML to plain text. Table rows shaped
    like <tr><th>Label</th><td>Value</td></tr> (OSE's monster/spell stat-block
    convention) become "Label: Value" lines; other rows join cells with " | ".
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._buf: list[str] = []
        self._cells: list[str] | None = None
        self._cell_buf: list[str] = []
        self._in_cell = False
        self._skip_depth = 0
        self._editsection_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "span" and (
            self._editsection_depth
            or dict(attrs).get("class", "").find("mw-editsection") != -1
        ):
            self._editsection_depth += 1
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "tr":
            self._cells = []
        elif tag in ("th", "td"):
            self._in_cell = True
            self._cell_buf = []
        elif tag in _BLOCK_TAGS or tag == "br":
            self._flush_buf()

    def handle_endtag(self, tag):
        if tag == "span" and self._editsection_depth:
            self._editsection_depth -= 1
        elif tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in ("th", "td"):
            self._in_cell = False
            if self._cells is not None:
                self._cells.append(" ".join(self._cell_buf).split())
                self._cells[-1] = " ".join(self._cells[-1])
            self._cell_buf = []
        elif tag == "tr":
            if self._cells:
                cells = [c for c in self._cells if c]
                if len(cells) == 2:
                    self.lines.append(f"{cells[0]}: {cells[1]}")
                elif cells:
                    self.lines.append(" | ".join(cells))
            self._cells = None
        elif tag in _BLOCK_TAGS:
            self._flush_buf()

    def handle_data(self, data):
        if self._skip_depth or self._editsection_depth:
            return
        if self._in_cell:
            self._cell_buf.append(data)
        else:
            self._buf.append(data)

    def _flush_buf(self):
        text = "".join(self._buf).strip()
        if text:
            self.lines.append(text)
        self._buf = []

    def get_text(self) -> str:
        self._flush_buf()
        return "\n".join(line for line in self.lines if line.strip())


def html_to_plaintext(html: str) -> str:
    extractor = _WikiHTMLTextExtractor()
    extractor.feed(html)
    return extractor.get_text().strip()


def page_url(title: str) -> str:
    return f"{SRD_BASE}/index.php/{title.replace(' ', '_')}"


async def build_cache(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(db_path)) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS srd_sections (
                title TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                url TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)
        await db.commit()

        print("Fetching page list from SRD...")
        titles = list_all_titles()
        print(f"Found {len(titles)} articles. Crawling...")

        stored = 0
        for i, title in enumerate(titles, 1):
            page_html = fetch_page_html(title)
            time.sleep(REQUEST_DELAY_SECONDS)
            if not page_html:
                continue
            plaintext = html_to_plaintext(page_html)
            if not plaintext:
                continue
            await db.execute(
                "INSERT OR REPLACE INTO srd_sections (title, content, url, fetched_at) "
                "VALUES (?, ?, ?, ?)",
                (title, plaintext, page_url(title),
                 datetime.now(timezone.utc).isoformat()),
            )
            stored += 1
            if i % 25 == 0 or i == len(titles):
                await db.commit()
                print(f"  {i}/{len(titles)} pages processed ({stored} stored)")

        await db.commit()
        print(f"Done. {stored} sections stored in {db_path}")


def main():
    if len(sys.argv) > 1:
        target = Path(sys.argv[1])
    else:
        target = Path(os.getenv("SRD_DB_PATH", str(Config.BASE_DIR / "data" / "srd_cache.db")))

    asyncio.run(build_cache(target.resolve()))


if __name__ == "__main__":
    main()
