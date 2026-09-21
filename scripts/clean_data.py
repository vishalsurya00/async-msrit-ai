"""
Step 4 - clean_data.py
Looks at every downloaded file and builds a clean catalog of what we can use.
NOTHING IS DELETED OR MOVED - the catalog decides what later steps read.

For each PDF it checks: valid header, opens, page count, encrypted?, has real text
(or is a scan that will need OCR), and exact duplicates (same SHA-256 hash).
Non-PDF files are simply listed as ignored.

    python scripts/clean_data.py [--year first]

Output: data/structured/<year>_year_clean_files.json  +  docs/cleaning-report.md
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import pymupdf as fitz  # PyMuPDF (new name)
except ImportError:
    import fitz  # PyMuPDF (old name)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
fitz.TOOLS.mupdf_display_errors(False)

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
DOCS = ROOT / "docs"
RAW = ROOT / "data" / "raw"

SAMPLE_PAGES = 5      # pages checked for text
MIN_TEXT_CHARS = 100  # fewer characters than this in the sample = probably a scan


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_pdf(path: Path) -> dict:
    """Return {status, pages, text_chars} for one PDF."""
    if path.stat().st_size == 0:
        return {"status": "empty", "pages": 0, "text_chars": 0}
    with open(path, "rb") as f:
        if f.read(5) != b"%PDF-":
            return {"status": "corrupt", "pages": 0, "text_chars": 0, "note": "not a real PDF (bad header)"}
    try:
        doc = fitz.open(path)
    except Exception as e:
        return {"status": "corrupt", "pages": 0, "text_chars": 0, "note": str(e)[:100]}
    try:
        if doc.needs_pass:
            return {"status": "encrypted", "pages": 0, "text_chars": 0}
        pages = doc.page_count
        if pages == 0:
            return {"status": "corrupt", "pages": 0, "text_chars": 0, "note": "0 pages"}
        chars = 0
        for i in range(min(pages, SAMPLE_PAGES)):
            chars += len(doc[i].get_text().strip())
        status = "ok" if chars >= MIN_TEXT_CHARS else "scanned_needs_ocr"
        return {"status": status, "pages": pages, "text_chars": chars}
    except Exception as e:
        return {"status": "corrupt", "pages": 0, "text_chars": 0, "note": str(e)[:100]}
    finally:
        doc.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="first")
    args = ap.parse_args(argv)

    base = RAW / f"{args.year}_year" / "by_folder"
    if not base.exists():
        sys.exit(f"Nothing to clean: {base} does not exist. Run download_folder.py first.")

    all_files = sorted(p for p in base.rglob("*") if p.is_file())
    ignored = Counter(p.suffix.lower() or "(none)" for p in all_files if p.suffix.lower() != ".pdf")
    pdfs = [p for p in all_files if p.suffix.lower() == ".pdf"]
    print(f"Found {len(all_files)} files: {len(pdfs)} PDFs, {sum(ignored.values())} other (ignored: {dict(ignored)})")

    records, first_seen = [], {}
    for i, p in enumerate(pdfs, 1):
        info = inspect_pdf(p)
        digest = sha256(p)
        rel = p.relative_to(ROOT).as_posix()
        rec = {
            "path": rel,
            "folder_dir": p.relative_to(base).parts[0],
            "file_name": p.name,
            "size_bytes": p.stat().st_size,
            "sha256": digest,
            **info,
            "duplicate_of": None,
        }
        # exact duplicate of an earlier readable file -> mark it, keep the first one
        if info["status"] in ("ok", "scanned_needs_ocr"):
            if digest in first_seen:
                rec["duplicate_of"] = first_seen[digest]
                rec["status"] = "duplicate"
            else:
                first_seen[digest] = rel
        records.append(rec)
        if i % 25 == 0:
            print(f"  checked {i}/{len(pdfs)} ...")

    status = Counter(r["status"] for r in records)
    usable = [r for r in records if r["status"] in ("ok", "scanned_needs_ocr")]
    total_pages = sum(r["pages"] for r in usable)

    STRUCT.mkdir(parents=True, exist_ok=True)
    out = STRUCT / f"{args.year}_year_clean_files.json"
    out.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ignored_non_pdf": dict(ignored),
        "summary": dict(status),
        "files": records,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---- report ----
    per_folder = defaultdict(Counter)
    for r in records:
        per_folder[r["folder_dir"]][r["status"]] += 1
    lines = [
        f"# Cleaning report - {args.year} year", "",
        f"- PDFs found: {len(pdfs)}",
        f"- Usable with text (ok): {status.get('ok', 0)}",
        f"- Scanned, need OCR: {status.get('scanned_needs_ocr', 0)}",
        f"- Exact duplicates (skipped): {status.get('duplicate', 0)}",
        f"- Corrupt / empty / encrypted: {status.get('corrupt', 0)} / {status.get('empty', 0)} / {status.get('encrypted', 0)}",
        f"- Total pages in usable files: {total_pages}",
        f"- Non-PDF files ignored: {dict(ignored)}", "",
        "## Per folder", "", "| Folder | ok | scanned | duplicate | bad |", "|---|---|---|---|---|",
    ]
    for d, c in sorted(per_folder.items()):
        bad = c.get("corrupt", 0) + c.get("empty", 0) + c.get("encrypted", 0)
        lines.append(f"| {d} | {c.get('ok', 0)} | {c.get('scanned_needs_ocr', 0)} | {c.get('duplicate', 0)} | {bad} |")
    dups = [r for r in records if r["status"] == "duplicate"]
    if dups:
        lines += ["", "## Duplicates", ""] + [f"- `{r['path']}` = `{r['duplicate_of']}`" for r in dups]
    bad = [r for r in records if r["status"] in ("corrupt", "empty", "encrypted")]
    if bad:
        lines += ["", "## Bad files (skipped)", ""] + [f"- `{r['path']}` ({r['status']}) {r.get('note', '')}" for r in bad]
    scans = [r for r in records if r["status"] == "scanned_needs_ocr"]
    if scans:
        lines += ["", "## Scanned PDFs (OCR needed in Step 8)", ""] + [f"- `{r['path']}` ({r['pages']} pages)" for r in scans]
    DOCS.mkdir(exist_ok=True)
    (DOCS / "cleaning-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n" + "\n".join(lines[:11]))
    print(f"\nCatalog: {out.relative_to(ROOT)}")
    print("Full report: docs/cleaning-report.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
