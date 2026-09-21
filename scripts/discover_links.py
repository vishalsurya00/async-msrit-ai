"""
Step 2 - discover_links.py
Scrapes ritnotebook.pages.dev/notes/<year>.html and writes every
Stream -> Cycle -> Subject -> Google Drive folder link to JSON.

Usage (from project root, venv active):
    python scripts/discover_links.py                 # first year, live fetch
    python scripts/discover_links.py --year second   # other years (Step 6)
    python scripts/discover_links.py --file page.html   # parse a saved HTML file (offline test)
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ritnotebook.pages.dev/notes/{year}.html"
OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "structured"
FOLDER_RE = re.compile(r"drive\.google\.com/drive/folders/([\w-]+)")

# What we counted on first.html (Step 1). Scraper output must match these.
EXPECTED_FIRST = {
    ("Computer Science & Engineering Stream", "Physics Cycle"): 8,
    ("Computer Science & Engineering Stream", "Chemistry Cycle"): 8,
    ("Electrical & Electronics Engineering Stream", "Chemistry Cycle"): 8,
    ("Electrical & Electronics Engineering Stream", "Physics Cycle"): 9,
    ("Civil Engineering Stream", "Physics Cycle"): 8,
    ("Civil Engineering Stream", "Chemistry Cycle"): 8,
    ("Mechanical Engineering Stream", "Chemistry Cycle"): 8,
    ("Mechanical Engineering Stream", "Physics Cycle"): 8,
}


def clean(text: str) -> str:
    """Remove the dropdown arrow and collapse whitespace."""
    return re.sub(r"\s+", " ", text.replace("\u25be", "").replace("▾", "")).strip()


def load_html(year: str, file: str | None) -> tuple[str, str]:
    if file:
        return Path(file).read_text(encoding="utf-8"), f"file:{file}"
    url = BASE_URL.format(year=year)
    resp = requests.get(url, timeout=30, headers={"User-Agent": "msrit-ai-hackathon/0.1"})
    resp.raise_for_status()
    return resp.text, url


def parse(html: str, year: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    stream = branches = cycle = None

    # Walk headings and links in document order.
    for el in soup.find_all(["h2", "h3", "a"]):
        if el.name == "h2":
            text = clean(el.get_text())
            if "stream" in text.lower():
                stream, cycle = text, None
                # the line right under the stream heading lists the branches
                nxt = el.find_next_sibling()
                branches = clean(nxt.get_text()) if nxt and nxt.name not in ("h2", "h3", "ul") else ""
        elif el.name == "h3":
            text = clean(el.get_text())
            if "cycle" in text.lower():
                cycle = text
        elif el.name == "a":
            href = el.get("href", "")
            m = FOLDER_RE.search(href)
            if not m or not stream or not cycle:
                continue  # skip nav links, mailto, links outside a cycle
            records.append({
                "year": year,
                "stream": stream,
                "stream_branches": branches,
                "cycle": cycle,
                "subject": clean(el.get_text()),
                "folder_id": m.group(1),
                "folder_url": href,
            })
    return records


def report(records: list[dict], year: str) -> bool:
    ok = True
    print(f"\nTotal subject entries : {len(records)}")

    counts = Counter((r["stream"], r["cycle"]) for r in records)
    print("\nBy stream / cycle:")
    for (s, c), n in counts.items():
        print(f"  {s} / {c}: {n}")

    unique = {r["folder_id"] for r in records}
    print(f"\nUnique Drive folders  : {len(unique)}  (many subjects share one folder)")

    shared = defaultdict(set)
    for r in records:
        shared[r["folder_id"]].add(r["subject"])

    # duplicate subject inside the same stream+cycle = suspicious
    seen = Counter((r["stream"], r["cycle"], r["subject"]) for r in records)
    dups = [k for k, v in seen.items() if v > 1]
    if dups:
        ok = False
        print("\n!! Duplicate subject in same stream/cycle:", dups)

    if year == "first":
        print("\nCheck against Step 1 counts:")
        for key, want in EXPECTED_FIRST.items():
            got = counts.get(key, 0)
            flag = "OK " if got == want else "MISMATCH"
            if got != want:
                ok = False
            print(f"  [{flag}] {key[0]} / {key[1]}: expected {want}, got {got}")
        extra = set(counts) - set(EXPECTED_FIRST)
        if extra:
            ok = False
            print("  !! unexpected stream/cycle groups:", extra)
    else:
        print(f"\n(No expected counts stored for '{year}' yet - count by hand and compare, then add them.)")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="first", choices=["first", "second", "third", "fourth"])
    ap.add_argument("--file", help="parse a saved HTML file instead of fetching")
    args = ap.parse_args()

    html, source = load_html(args.year, args.file)
    records = parse(html, args.year)
    if not records:
        print("No links found. The page layout may differ - save the HTML and inspect it.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{args.year}_year_links.json"
    payload = {
        "source": source,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
        "unique_folders": {r["folder_id"]: r["folder_url"] for r in records},
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(records)} records -> {out}")

    ok = report(records, args.year)
    print("\nRESULT:", "PASS - matches Step 1 counts" if ok else "CHECK ABOVE - counts don't match")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
