"""
Step 3b - validate_extraction.py
Checks what was actually downloaded and writes docs/extraction-report.md.

    python scripts/validate_extraction.py [--year first]
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
DOCS = ROOT / "docs"


def pdf_ok(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="first")
    args = ap.parse_args(argv)

    links_path = STRUCT / f"{args.year}_year_links.json"
    man_path = STRUCT / f"{args.year}_year_download_manifest.json"
    if not links_path.exists() or not man_path.exists():
        sys.exit("Need both the links JSON and the download manifest. Run discover_links.py and download_folder.py first.")

    links = json.loads(links_path.read_text(encoding="utf-8"))
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    expected = set(links["unique_folders"])
    done = manifest["folders"]

    ext_count, bad_files, zero_files = Counter(), [], []
    per_folder, total_bytes, total_files = {}, 0, 0
    for fid, info in done.items():
        d = ROOT / info["dir"]
        files = [p for p in d.rglob("*") if p.is_file()] if d.exists() else []
        per_folder[fid] = len(files)
        for p in files:
            total_files += 1
            size = p.stat().st_size
            total_bytes += size
            ext = p.suffix.lower() or "(none)"
            ext_count[ext] += 1
            rel = p.relative_to(ROOT).as_posix()
            if size == 0:
                zero_files.append(rel)
            elif ext == ".pdf" and not pdf_ok(p):
                bad_files.append(rel)

    status = Counter(v["status"] for v in done.values())
    not_tried = sorted(expected - set(done))
    failed = {fid: v for fid, v in done.items() if v["status"] != "ok"}

    # subject table: which folder each (stream, cycle, subject) points to and how many files it has
    rows, empty_subjects = [], []
    for r in links["records"]:
        n = per_folder.get(r["folder_id"], 0)
        rows.append((r["stream"], r["cycle"], r["subject"], r["folder_id"][:8], n))
        if n == 0:
            empty_subjects.append((r["stream"], r["cycle"], r["subject"]))

    lines = [
        f"# Extraction report - {args.year} year", "",
        f"- Expected folders: {len(expected)}",
        f"- Folders downloaded OK: {status.get('ok', 0)}",
        f"- Folders partial / failed / empty: {status.get('partial', 0)} / {status.get('failed', 0)} / {status.get('empty', 0)}",
        f"- Folders not attempted yet: {len(not_tried)}",
        f"- Files on disk: {total_files} ({total_bytes / 1_048_576:.1f} MB)",
        f"- File types: {dict(ext_count.most_common())}",
        f"- Zero-byte files: {len(zero_files)}",
        f"- Corrupted PDFs (bad header): {len(bad_files)}",
        f"- Subjects (of {len(rows)}) with no files: {len(empty_subjects)}", "",
    ]
    if failed:
        lines += ["## Problem folders", ""]
        lines += [f"- `{fid[:8]}` {v['status']}: {v.get('error')}" for fid, v in failed.items()]
        for fid, v in failed.items():
            lines += [f"  - failed file: {ff['name']}" for ff in v.get("failed_files", [])[:10]]
        lines.append("")
    if zero_files or bad_files:
        lines += ["## Bad files", ""] + [f"- {p}" for p in zero_files + bad_files] + [""]
    lines += ["## Subject -> folder -> files", "",
              "| Stream | Cycle | Subject | Folder | Files |", "|---|---|---|---|---|"]
    lines += [f"| {s} | {c} | {sub} | {f} | {n} |" for s, c, sub, f, n in rows]

    DOCS.mkdir(exist_ok=True)
    (DOCS / "extraction-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines[:12]))
    print("\nFull report: docs/extraction-report.md")
    healthy = not (failed or not_tried or bad_files or zero_files or empty_subjects)
    print("RESULT:", "PASS" if healthy else "NOT CLEAN YET - see report")
    return 0 if healthy else 2


if __name__ == "__main__":
    sys.exit(main())
