"""
Step 3a - download_folder.py  (v2)
Downloads the Google Drive folders listed in data/structured/<year>_year_links.json.

v2 changes:
  * downloads PDFs only by default (PPT/DOCX etc. are skipped - we only ingest PDFs)
  * downloads file by file, with retries, and records every failed file
  * stops hammering Google when it is clearly rate-limiting ("too many accesses")
  * safe to re-run: finished files/folders are skipped

Usage (from project root, venv active):
    python scripts/download_folder.py --limit 1     # test with ONE folder
    python scripts/download_folder.py               # all folders
    python scripts/download_folder.py --ext pdf,docx   # also grab Word files
    python scripts/download_folder.py --force
"""
import argparse
import inspect
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import gdown

if hasattr(sys.stdout, "reconfigure"):  # Windows consoles + non-English file names
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
STRUCT = ROOT / "data" / "structured"
RAW = ROOT / "data" / "raw"

FILE_TRIES = 2               # tries per file
QUOTA_ABORT_FOLDER = 5       # this many quota errors in a row -> give up on this folder for now
QUOTA_ABORT_RUN = 2          # this many folders aborted in a row -> stop the whole run


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return s[:40] or "folder"


def load_folders(year: str) -> dict:
    links = STRUCT / f"{year}_year_links.json"
    if not links.exists():
        sys.exit(f"Missing {links}. Run scripts/discover_links.py first.")
    data = json.loads(links.read_text(encoding="utf-8"))
    folders: dict = {}
    for r in data["records"]:
        f = folders.setdefault(r["folder_id"], {"folder_url": r["folder_url"], "subjects": []})
        f["subjects"].append({"stream": r["stream"], "cycle": r["cycle"], "subject": r["subject"]})
    return folders


def folder_dir(year: str, folder_id: str, subjects: list) -> Path:
    name = f"{slugify(subjects[0]['subject'])}__{folder_id[:8]}"
    return RAW / f"{year}_year" / "by_folder" / name


def list_folder(folder_id: str, out_dir: Path):
    """Ask gdown for the file list WITHOUT downloading anything."""
    params = inspect.signature(gdown.download_folder).parameters
    if "skip_download" not in params:
        sys.exit("Your gdown is too old. Run: pip install -U gdown")
    kwargs = {"id": folder_id, "output": str(out_dir), "quiet": True, "skip_download": True}
    if "remaining_ok" in params:
        kwargs["remaining_ok"] = True
    return gdown.download_folder(**kwargs) or []


def is_quota_error(msg: str) -> bool:
    m = msg.lower()
    return "many accesses" in m or "cannot retrieve the public link" in m or "too many users" in m


def download_file(file_id: str, dest: Path):
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for attempt in range(FILE_TRIES):
        try:
            got = gdown.download(id=file_id, output=str(dest), quiet=True)
            if got and dest.exists() and dest.stat().st_size > 0:
                return None
            last = "gdown returned nothing"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        time.sleep(2)
    return " ".join(last.split())[:200]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", default="first")
    ap.add_argument("--limit", type=int, help="only process the first N folders (testing)")
    ap.add_argument("--only", help="only this folder id")
    ap.add_argument("--force", action="store_true", help="re-check folders already marked OK")
    ap.add_argument("--ext", default="pdf", help="comma list of file types to download (default: pdf)")
    ap.add_argument("--sleep", type=float, default=3.0, help="seconds to wait between folders")
    ap.add_argument("--file-sleep", type=float, default=1.0, help="seconds to wait between files")
    args = ap.parse_args(argv)
    wanted = {"." + e.strip().lower().lstrip(".") for e in args.ext.split(",")}

    folders = load_folders(args.year)
    manifest_path = STRUCT / f"{args.year}_year_download_manifest.json"
    manifest = {"year": args.year, "folders": {}}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    ids = [args.only] if args.only else list(folders)
    if args.only and args.only not in folders:
        sys.exit("That folder id is not in the links file.")
    if args.limit:
        ids = ids[: args.limit]

    aborted_in_a_row = 0
    for n, fid in enumerate(ids, 1):
        info = folders[fid]
        out_dir = folder_dir(args.year, fid, info["subjects"])
        prev = manifest["folders"].get(fid, {})
        label = f"[{n}/{len(ids)}] {out_dir.name}"

        if prev.get("status") == "ok" and not args.force:
            print(f"{label}: already OK, skipping")
            continue

        print(f"\n{label}: listing files ...")
        out_dir.mkdir(parents=True, exist_ok=True)
        folder_error, failed, skipped_types, quota_streak, aborted = None, [], {}, 0, False
        try:
            listing = list_folder(fid, out_dir)
        except Exception as e:
            listing, folder_error = [], " ".join(f"{type(e).__name__}: {e}".split())[:200]

        todo = []
        for f in listing:
            local = Path(getattr(f, "local_path", None) or os.path.join(out_dir, f.path))
            ext = local.suffix.lower()
            if ext in wanted:
                todo.append((f.id, local))
            else:
                skipped_types[ext or "(none)"] = skipped_types.get(ext or "(none)", 0) + 1
        print(f"{label}: {len(listing)} files in folder, {len(todo)} to download "
              f"(skipping types: {skipped_types or 'none'})")

        for i, (file_id, local) in enumerate(todo, 1):
            if local.exists() and local.stat().st_size > 0:
                continue  # already have it
            err = download_file(file_id, local)
            if err is None:
                quota_streak = 0
                print(f"   ok  {i}/{len(todo)}  {local.name}")
                time.sleep(args.file_sleep)
            else:
                failed.append({"file_id": file_id, "name": local.name, "error": err})
                print(f"   FAIL {i}/{len(todo)}  {local.name}  ({err[:70]})")
                quota_streak = quota_streak + 1 if is_quota_error(err) else 0
                if quota_streak >= QUOTA_ABORT_FOLDER:
                    aborted = True
                    print(f"{label}: Google is rate-limiting us - pausing this folder. Re-run later.")
                    break

        files = [p for p in out_dir.rglob("*") if p.is_file() and p.suffix.lower() in wanted]
        total = sum(p.stat().st_size for p in files)
        if folder_error and not files:
            status, error = "failed", folder_error
        elif not todo and not files:
            status, error = "empty", "no files of the wanted types in this folder"
        elif failed or aborted:
            status, error = "partial", f"{len(failed)} file(s) failed" + (" (rate-limited)" if aborted else "")
        else:
            status, error = "ok", None

        manifest["folders"][fid] = {
            "dir": out_dir.relative_to(ROOT).as_posix(),
            "folder_url": info["folder_url"],
            "status": status,
            "file_count": len(files),
            "total_bytes": total,
            "error": error,
            "failed_files": failed,
            "skipped_types": skipped_types,
            "attempts": prev.get("attempts", 0) + 1,
            "last_attempt": datetime.now(timezone.utc).isoformat(),
            "subjects": info["subjects"],
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{label}: {status.upper()} - {len(files)} files, {total / 1_048_576:.1f} MB"
              + (f" | {error}" if error else ""))

        aborted_in_a_row = aborted_in_a_row + 1 if aborted else 0
        if aborted_in_a_row >= QUOTA_ABORT_RUN:
            print("\nGoogle is blocking downloads right now. Stop here, wait 1-2 hours "
                  "(or try another network), then run the same command again.")
            break
        if n < len(ids):
            time.sleep(args.sleep)

    ok = sum(1 for v in manifest["folders"].values() if v["status"] == "ok")
    print(f"\nFolders OK: {ok} / {len(folders)} total  (manifest: {manifest_path.name})")
    print("Next: python scripts/validate_extraction.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
