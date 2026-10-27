"""
Step 1 of the pipeline: get the public documents onto your computer.

Ways to add a document:

  A) Automatic download - put the link in sources_list.csv, then run
         python3 src/download.py
  B) You downloaded it yourself in the browser (sites that block scripts) -
     register the file so it gets a source_id:
         python3 src/download.py --register data/raw/ec/<file>.pdf \
             --url "https://..." --title "..." --publisher "..." --type ec --date 2022-04-29
  C) A lead found by src/discover.py:
         python3 src/download.py --lead LD00003            # download + register it
         python3 src/download.py --skip-lead LD00004       # not relevant, ignore it

Update check (used by the scheduled job run_update.sh):
         python3 src/download.py --check
  re-downloads every source, compares a fingerprint and reports which documents
  changed. Old versions are kept, never overwritten. A changed EC document is
  re-extracted into data/staging/ automatically (you still approve the rows).
  A summary is written to logs/last_update.json for the app.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.robotparser
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from schema import RAW, ROOT, add_row, load, save, today  # noqa: E402

SOURCE_LIST = ROOT / "sources_list.csv"
LOGS = ROOT / "logs"
HEADERS = {"User-Agent": "RawMaterialIntel-research-prototype/1.0 (academic project)"}
DELAY_SECONDS = 3   # be polite to government servers


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(path: Path) -> str:
    """For PDFs/Excel: hash of the bytes. For web pages: hash of the visible text only,
    so changing ads, tokens or timestamps in the HTML do not count as a 'change'."""
    if path.suffix.lower() not in (".html", ".htm"):
        return sha256(path)
    html = path.read_text(errors="ignore")
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(text.encode()).hexdigest()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:80]


def robots_allows(url: str) -> bool:
    p = urlparse(url)
    rp = urllib.robotparser.RobotFileParser(f"{p.scheme}://{p.netloc}/robots.txt")
    try:
        rp.read()
        return rp.can_fetch(HEADERS["User-Agent"], url)
    except Exception:
        return True   # no robots.txt reachable -> treat as allowed


def fetch(url: str, dest: Path, quiet: bool = False) -> str:
    """Returns 'ok', 'robots', 'failed' or 'not_pdf'."""
    import requests
    if not robots_allows(url):
        if not quiet:
            print(f"  SKIP (robots.txt disallows): {url}")
        return "robots"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
    except Exception as e:
        if not quiet:
            print(f"  FAILED: {e}\n  -> open the link in your browser, save the file, and use --register")
        return "failed"
    if dest.suffix == ".pdf" and not r.content.startswith(b"%PDF"):
        if not quiet:
            print("  FAILED: the site sent a web page, not a PDF\n  -> open the link in your browser, save the file, and use --register")
        return "not_pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(r.content)
    return "ok"


def register(path: Path, url: str, title: str, publisher: str, stype: str, ddate: str) -> str:
    sources = load("sources")
    digest = sha256(path)
    rel = str(path.resolve().relative_to(ROOT))
    same = sources[sources.sha256 == digest]
    if len(same):
        print(f"  already registered as {same.source_id.iloc[0]} ({rel})")
        return same.source_id.iloc[0]
    sources, sid = add_row(sources, "sources", {
        "title": title, "publisher": publisher, "source_type": stype, "url": url,
        "document_date": ddate, "local_file": rel, "sha256": digest,
        "downloaded_on": today(), "status": "current",
    })
    save("sources", sources)
    print(f"  registered {sid}: {title}")
    return sid


def file_ext(url: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in (".pdf", ".xlsx", ".xls", ".csv", ".html", ".htm"):
        return ext
    if ext in ("", ".php", ".aspx", ".asp") and "download" not in url.lower():
        return ".html"
    return ".pdf"   # links like ...download.jsp?num_id=... serve a PDF


def download_all() -> None:
    todo = pd.read_csv(SOURCE_LIST, dtype=str, keep_default_na=False)
    for _, s in todo.iterrows():
        dest = RAW / s.source_type / f"{slug(s.title)}{file_ext(s.url)}"
        print(f"- {s.title}")
        if dest.exists():
            print("  already downloaded")
        elif fetch(s.url, dest) != "ok":
            continue
        register(dest, s.url, s.title, s.publisher, s.source_type, s.document_date)
        time.sleep(DELAY_SECONDS)


def take_lead(lead_id: str, ddate: str) -> None:
    leads = load("leads")
    hit = leads[leads.lead_id == lead_id]
    if hit.empty:
        sys.exit(f"No lead {lead_id}. See them with: python3 src/discover.py --list")
    i, ld = hit.index[0], hit.iloc[0]
    stype = ld.source_type or "other"
    dest = RAW / stype / f"{slug(ld.title or lead_id)}{file_ext(ld.url)}"
    print(f"- {ld.title}\n  {ld.url}")
    result = fetch(ld.url, dest)
    if result != "ok":
        leads.loc[i, "status"] = "needs manual download"
        save("leads", leads)
        print("  Open the link in Chrome, save the file into data/raw/, then register it with --register.")
        return
    sid = register(dest, ld.url, ld.title or dest.stem, ld.publisher, stype, ddate)
    leads.loc[i, "status"] = f"downloaded ({sid})"
    save("leads", leads)
    if stype == "ec" and dest.suffix == ".pdf":
        print("  Next: python3 src/extract_ec.py " + str(dest.relative_to(ROOT)))


def skip_lead(lead_id: str) -> None:
    leads = load("leads")
    if lead_id not in set(leads.lead_id):
        sys.exit(f"No lead {lead_id}")
    leads.loc[leads.lead_id == lead_id, "status"] = "ignored"
    save("leads", leads)
    print(f"{lead_id} marked as ignored")


def check_updates() -> None:
    sources = load("sources")
    summary = {"run_at": datetime.now().isoformat(timespec="seconds"), "checked": 0,
               "unchanged": [], "changed": [], "skipped_robots": [], "failed": [], "not_checkable": []}
    for i, s in sources[sources.status == "current"].iterrows():
        if not s.url.startswith("http"):
            summary["not_checkable"].append(s.title)          # own calculations, manual files
            continue
        tmp = RAW / "_check" / Path(s.local_file).name
        print(f"- {s.title}")
        result = fetch(s.url, tmp, quiet=True)
        summary["checked"] += 1
        if result == "robots":
            print("  skipped (robots.txt) - check this one by hand in a browser")
            summary["skipped_robots"].append(s.title)
            continue
        if result != "ok":
            print("  could not re-download (site blocked or link is a landing page) - check by hand")
            summary["failed"].append(s.title)
            continue
        if fingerprint(tmp) == fingerprint(ROOT / s.local_file):
            print("  unchanged")
            summary["unchanged"].append(s.title)
            tmp.unlink()
        else:
            versioned = Path(s.local_file).with_name(f"{Path(s.local_file).stem}_{today()}{Path(s.local_file).suffix}")
            (ROOT / versioned).parent.mkdir(parents=True, exist_ok=True)
            tmp.replace(ROOT / versioned)
            sources.loc[i, "status"] = "superseded"
            save("sources", sources)
            new_sid = register(ROOT / versioned, s.url, f"{s.title} ({today()})", s.publisher, s.source_type, today())
            sources = load("sources")
            summary["changed"].append(f"{s.title} -> {new_sid}")
            print(f"  CHANGED: new version saved as {new_sid} (old version kept as {s.source_id})")
            if s.source_type == "ec" and versioned.suffix == ".pdf":
                print("  re-extracting into data/staging/ for your review ...")
                subprocess.run([sys.executable, str(ROOT / "src" / "extract_ec.py"), str(ROOT / versioned)])
        time.sleep(DELAY_SECONDS)
    LOGS.mkdir(exist_ok=True)
    (LOGS / "last_update.json").write_text(json.dumps(summary, indent=2))
    print(f"Update check done: {len(summary['changed'])} changed, {len(summary['unchanged'])} unchanged, "
          f"{len(summary['skipped_robots']) + len(summary['failed'])} need a manual check.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", type=Path)
    ap.add_argument("--url", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--publisher", default="")
    ap.add_argument("--type", default="other", help="who_gmp | ec | pli | company | estimate | other")
    ap.add_argument("--date", default="", help="document date YYYY-MM-DD")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--lead")
    ap.add_argument("--skip-lead")
    a = ap.parse_args()
    if a.register:
        if not a.register.exists():
            sys.exit(f"File not found: {a.register}")
        register(a.register, a.url or "manual", a.title or a.register.stem, a.publisher, a.type, a.date)
    elif a.lead:
        take_lead(a.lead, a.date)
    elif a.skip_lead:
        skip_lead(a.skip_lead)
    elif a.check:
        check_updates()
    else:
        download_all()
