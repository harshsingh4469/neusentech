"""
Component A - automatic discovery of NEW public documents.

    python3 src/discover.py            # look for new documents, save them as leads
    python3 src/discover.py --list     # show leads waiting for a decision

Two ways it finds documents:

 1. Watch pages (free, always on) - official pages listed in watch_pages.csv
    (CDSCO, Department of Pharmaceuticals, company EC pages ...). Every link on the
    page whose text or address matches the keywords and is not already a source
    or a lead becomes a new lead.

 2. Web search (optional) - if you set a Brave Search API key, every query in
    search_queries.txt is searched and PDF results become leads:
        export BRAVE_API_KEY="your-key"      (get one at https://brave.com/search/api/)

A lead is NOT data. It is only a document worth looking at. You decide:
    python3 src/download.py --lead LD00003       -> download + register it
    python3 src/download.py --skip-lead LD00004  -> not relevant
Sites whose robots.txt forbids scripts are not fetched; they are reported so you
can check them by hand in a browser.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from download import HEADERS, robots_allows  # noqa: E402
from schema import ROOT, add_row, load, save, today  # noqa: E402

WATCH = ROOT / "watch_pages.csv"
QUERIES = ROOT / "search_queries.txt"
DOC_RE = re.compile(r"\.(pdf|xlsx?|csv)(\?|$)|download", re.I)


class LinkParser(HTMLParser):
    """Collects every <a href> with its own text AND the text of its table row,
    because government pages often put the title in one cell and 'Download' in another."""

    def __init__(self):
        super().__init__()
        self.links, self._row, self._row_links, self._a = [], [], [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row, self._row_links = [], []
        elif tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "text": a.get("title", "") or ""}

    def handle_data(self, data):
        if self._a is not None:
            self._a["text"] += " " + data
        self._row.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._a is not None:
            self._row_links.append(self._a)
            self.links.append(self._a)
            self._a = None
        elif tag == "tr":
            row_text = " ".join(self._row)
            for link in self._row_links:
                link["row"] = row_text
            self._row, self._row_links = [], []


def clean(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def watch_pages(known: set[str]) -> list[dict]:
    import requests
    if not WATCH.exists():
        return []
    found = []
    for _, w in pd.read_csv(WATCH, dtype=str, keep_default_na=False).iterrows():
        print(f"- watching {w.url}")
        if not robots_allows(w.url):
            print("  robots.txt does not allow scripts here -> check this page by hand in a browser")
            continue
        try:
            r = requests.get(w.url, headers=HEADERS, timeout=60)
            r.raise_for_status()
        except Exception as e:
            print(f"  could not open page: {e}")
            continue
        p = LinkParser()
        p.feed(r.text)
        words = [k.strip().lower() for k in w.keywords.split("|") if k.strip()]
        new = 0
        for link in p.links:
            url = urljoin(w.url, link["href"].strip())
            if urlparse(url).scheme not in ("http", "https") or not DOC_RE.search(url) or url in known:
                continue
            text = clean(link.get("row") or link["text"]) or clean(link["text"])
            if words and not any(k in (text + " " + url).lower() for k in words):
                continue
            title = clean(link["text"]) if len(clean(link["text"])) > 12 else text
            title = re.sub(r"^\d+[.)]?\s+", "", title)
            title = re.sub(r"(\s*\b(download|pdf|view|open|click here|size.*kb)\b\s*)+$", "", title, flags=re.I)[:160]
            found.append({"title": title[:200], "url": url, "found_on": w.url, "query": "",
                          "source_type": w.source_type, "publisher": w.publisher})
            known.add(url)
            new += 1
        print(f"  {len(p.links)} links on page, {new} new matching document(s)")
        time.sleep(2)
    return found


def web_search(known: set[str]) -> list[dict]:
    key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not key or not QUERIES.exists():
        print("- web search: off (set BRAVE_API_KEY to turn it on)")
        return []
    import requests
    found = []
    for q in [l.strip() for l in QUERIES.read_text().splitlines() if l.strip() and not l.startswith("#")]:
        print(f"- searching: {q}")
        try:
            r = requests.get("https://api.search.brave.com/res/v1/web/search",
                             headers={"X-Subscription-Token": key, "Accept": "application/json"},
                             params={"q": q, "count": 20}, timeout=30)
            r.raise_for_status()
            results = r.json().get("web", {}).get("results", [])
        except Exception as e:
            print(f"  search failed: {e}")
            continue
        new = 0
        for item in results:
            url = item.get("url", "")
            if not url or url in known or not re.search(r"\.pdf(\?|$)", url, re.I):
                continue                       # leads = documents, not news pages
            stype = "ec" if re.search(r"parivesh|environmentclearance|seiaa|clearance|eia", url + item.get("title", ""), re.I) else "other"
            found.append({"title": clean(item.get("title", ""))[:200], "url": url, "found_on": "web search",
                          "query": q, "source_type": stype, "publisher": urlparse(url).netloc})
            known.add(url)
            new += 1
        print(f"  {len(results)} results, {new} new PDF lead(s)")
        time.sleep(1)
    return found


def main():
    sources, leads = load("sources"), load("leads")
    known = set(sources.url) | set(leads.url)
    found = watch_pages(known) + web_search(known)
    for f in found:
        leads, _ = add_row(leads, "leads", f | {"discovered_on": today(), "status": "new"})
    save("leads", leads)
    print(f"\nNew leads: {len(found)}. Waiting for a decision: {(leads.status == 'new').sum()}")
    if found:
        print("See them with:  python3 src/discover.py --list")


def show():
    leads = load("leads")
    todo = leads[leads.status.isin(["new", "needs manual download"])]
    if todo.empty:
        print("No leads waiting.")
        return
    for _, l in todo.iterrows():
        print(f"{l.lead_id} | {l.status} | {l.source_type} | {l.title[:90]}\n         {l.url}")
    print("\nDownload one:  python3 src/download.py --lead LD00001\nIgnore one:    python3 src/download.py --skip-lead LD00001")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    show() if ap.parse_args().list else main()
