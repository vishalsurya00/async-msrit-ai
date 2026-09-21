"""
Step 5 - add_metadata.py
Builds data/structured/<year>_year_metadata.json: one entry per usable document with
  stream(s), cycle(s), subject(s), doc_type, unit, exam_year, CIE number, source URL.

Reads: <year>_year_clean_files.json (Step 4), <year>_year_download_manifest.json (Step 3),
       <year>_year_links.json (Step 2).
Optional: data/structured/metadata_overrides.json to fix wrong guesses, like
       {"Cprog.pdf": {"doc_type": "notes"}}

    python scripts/add_metadata.py [--year first]
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6}


def classify(file_name: str) -> dict:
    """Guess doc type / unit / year / CIE number from the file name only."""
    stem = re.sub(r"\.pdf$", "", file_name, flags=re.I)
    n = stem.lower()

    if re.search(r"viva", n):
        dtype = "viva_questions"
    elif re.search(r"syllabus", n):
        dtype = "syllabus"
    elif re.search(r"\blab\b|lab manual", n):
        dtype = "lab_manual"
    elif re.search(r"\bcie\b|\bcie\s*\d|\bcie[-_ ]?\d|internal", n):
        dtype = "cie_paper"
    elif (re.search(r"\bsee\b|\bqp\b|question paper|makeup|model paper|previous|pyq", n)
          or re.match(r"^\W*20\d\d", n)):
        dtype = "question_paper"
    elif re.search(r"concise|summary|formula|short notes|one shot|cheat", n):
        dtype = "quick_revision"
    elif re.search(r"numerical|problems|question bank|\bqb\b|assignment", n):
        dtype = "practice_problems"
    elif re.search(r"unit|module|chapter|\bch\s*\d|notes|lecture", n):
        dtype = "notes"
    else:
        dtype = "other"

    unit = None
    m = re.search(r"unit[\s_\-]*([ivx]+|\d+)(?![a-z0-9])", n)
    if m:
        unit = ROMAN.get(m.group(1)) if not m.group(1).isdigit() else int(m.group(1))

    year = None
    if dtype in ("question_paper", "cie_paper"):
        y = re.search(r"(20\d\d)", n)
        year = int(y.group(1)) if y else None

    cie_no = None
    if dtype == "cie_paper":
        c = re.search(r"cie[\s_\-]*(\d)", n)
        cie_no = int(c.group(1)) if c else None

    return {"doc_type": dtype, "unit": unit, "exam_year": year, "cie_number": cie_no}


def apply_overrides(file_name: str, meta: dict, overrides: dict) -> dict:
    """Keys starting with ~ match any file name CONTAINING that text; other keys must match exactly."""
    low = file_name.lower()
    for key, val in overrides.items():
        if key.startswith("~") and key[1:].lower() in low:
            meta.update(val)
    if file_name in overrides:
        meta.update(overrides[file_name])
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="first")
    args = ap.parse_args(argv)

    def load(name):
        p = STRUCT / f"{args.year}_year_{name}.json"
        if not p.exists():
            sys.exit(f"Missing {p.name}. Run the earlier steps first.")
        return json.loads(p.read_text(encoding="utf-8"))

    clean, manifest, links = load("clean_files"), load("download_manifest"), load("links")
    overrides = {}
    op = STRUCT / "metadata_overrides.json"
    if op.exists():
        overrides = json.loads(op.read_text(encoding="utf-8"))

    branches = {r["stream"]: r["stream_branches"] for r in links["records"]}
    folder_info = {Path(v["dir"]).name: v for v in manifest["folders"].values()}

    def subjects_for(folder_dir):
        info = folder_info.get(folder_dir)
        return (info["subjects"], info["folder_url"]) if info else ([], None)

    files = clean["files"]
    by_path = {f["path"]: f for f in files}
    # subjects/folders contributed by duplicates, attached to the surviving copy
    extra_folders = defaultdict(list)
    for f in files:
        if f["status"] == "duplicate":
            extra_folders[f["duplicate_of"]].append(f["folder_dir"])

    docs = []
    for f in files:
        if f["status"] not in ("ok", "scanned_needs_ocr"):
            continue
        folder_dirs = [f["folder_dir"]] + [d for d in extra_folders.get(f["path"], []) if d != f["folder_dir"]]
        subjects, urls = [], []
        for d in folder_dirs:
            s, u = subjects_for(d)
            subjects += s
            if u:
                urls.append(u)
        seen, uniq = set(), []
        for s in subjects:
            k = (s["stream"], s["cycle"], s["subject"])
            if k not in seen:
                seen.add(k)
                uniq.append(s)

        meta = classify(f["file_name"])
        meta = apply_overrides(f["file_name"], meta, overrides)
        docs.append({
            "doc_id": f["sha256"][:12],
            "file_name": f["file_name"],
            "path": f["path"],
            "pages": f["pages"],
            "needs_ocr": f["status"] == "scanned_needs_ocr",
            "exclude_from_index": meta["doc_type"] == "textbook",  # full textbooks are not indexed
            "sha256": f["sha256"],
            **meta,
            "streams": sorted({s["stream"] for s in uniq}),
            "cycles": sorted({s["cycle"] for s in uniq}),
            "subjects": uniq,
            "source_folder_urls": sorted(set(urls)),
            "also_in_folders": folder_dirs[1:],
        })

    out = STRUCT / f"{args.year}_year_metadata.json"
    out.write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(),
        "stream_branches": branches,
        "documents": docs,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    types = Counter(d["doc_type"] for d in docs)
    print(f"Documents with metadata: {len(docs)}  ->  {out.relative_to(ROOT)}")
    print("\nBy type:", dict(types.most_common()))
    print("By stream:", dict(Counter(s for d in docs for s in d["streams"]).most_common()))
    print("Scanned (needs OCR):", sum(d["needs_ocr"] for d in docs))
    ex = [d for d in docs if d["exclude_from_index"]]
    print(f"Textbooks excluded from index: {len(ex)} files, {sum(d['pages'] for d in ex)} pages"
          f"  |  pages to index: {sum(d['pages'] for d in docs if not d['exclude_from_index'])}")
    nosub = [d for d in docs if not d["subjects"]]
    if nosub:
        print(f"\n!! {len(nosub)} docs with NO subject mapping:", [d["file_name"] for d in nosub][:10])
    other = [d for d in docs if d["doc_type"] == "other"]
    if other:
        print(f"\nType not guessed ({len(other)}) - check these, fix with metadata_overrides.json if wrong:")
        for d in other:
            print("  -", d["file_name"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
