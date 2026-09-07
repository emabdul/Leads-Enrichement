#!/usr/bin/env python3
"""Count how many apps each developer has, for pasting into a spreadsheet.

    python dev_app_count.py developers.txt -o counts.tsv

Input: one developer per line - a name ("ColorBean"), a Play developer URL,
or an Apple developer URL. Blank lines are preserved so the output column
stays row-aligned with your sheet.

Output: a TSV, plus a bare single column printed to the screen that you can
copy straight into the next spreadsheet column.

Accuracy, measured rather than assumed:

* Play exposes at most 50 apps per developer through any public endpoint.
  The developer page itself stops at 20 and the numeric dev page at ~10, so
  a pub:"name" search is used. Under 50 the count is exact - ColorBean 6 and
  WODH 9 agree across every method. At 50 the real total is unknown, so it
  is reported as "50+" instead of a number that would be wrong.
* Apple's artist lookup returns the whole catalogue (up to 200), so App Store
  counts are exact in normal cases.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from typing import Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

import sheets

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

PLAY_CAP = 50          # hard ceiling of the pub:"..." search endpoint
APPLE_LIMIT = 200


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def parse_input(raw: str) -> Tuple[str, str]:
    """Return (store, developer name) for a sheet cell.

    Accepts a bare name or a store URL; 'auto' means try Play then Apple.
    """
    raw = raw.strip()
    if not raw:
        return "auto", ""
    if raw.startswith("http"):
        u = urlparse(raw)
        if "play.google.com" in u.netloc:
            qs = parse_qs(u.query)
            return "play", unquote(qs.get("id", [""])[0])
        if "apps.apple.com" in u.netloc:
            m = re.search(r"/developer/([^/]+)/id(\d+)", u.path)
            if m:
                return "appstore", unquote(m.group(1)).replace("-", " ")
            return "appstore", ""
    return "auto", raw


def _resolve_play_developer(name: str, delay: float) -> Optional[str]:
    """Find the developer's real Play name when the sheet holds an alias.

    A pub:"..." lookup needs the exact string, and sheets often carry a short
    form - "TREEPLLA" is really "NEPTUNE(TREEPLLA)" on Play. A plain search
    still surfaces their apps, so the full name can be recovered from the
    developer field of the results.
    """
    from google_play_scraper import search

    try:
        results = search(name, n_hits=20, lang="en", country="us")
    except Exception:
        return None
    time.sleep(delay)
    key = _norm(name)
    if len(key) < 4:
        return None
    tally: dict = {}
    for a in results:
        dev = a.get("developer") or ""
        nd = _norm(dev)
        if nd and (key in nd or nd in key):
            tally[dev] = tally.get(dev, 0) + 1
    if not tally:
        return None
    return max(tally, key=tally.get)


def play_count(name: str, delay: float = 0.5,
               resolve: bool = True
               ) -> Tuple[Optional[int], bool, str, str]:
    """(count, capped). Counts only apps whose developer really is `name`."""
    from google_play_scraper import search

    if not name:
        return None, False, name, ""
    try:
        results = search('pub:"%s"' % name, n_hits=PLAY_CAP,
                         lang="en", country="us")
    except Exception:
        # The endpoint raises rather than returning [] when nothing matches.
        results = []
    time.sleep(delay)
    key = _norm(name)
    mine = [a for a in results
            if _norm(a.get("developer") or "").startswith(key[:12]) or
            key.startswith(_norm(a.get("developer") or "")[:12])]

    if not mine and resolve:
        full = _resolve_play_developer(name, delay)
        if full and _norm(full) != key:
            n, capped, _, sample = play_count(full, delay, resolve=False)
            return n, capped, full, sample  # report the real store name

    if not mine:
        return None, False, name, ""
    # The store's own spelling, not the sheet's: the developer page URL
    # is built from it, and "Grenge,inc" 404s where "Grenge,Inc." works.
    canonical = mine[0].get("developer") or name
    return (len(mine), len(results) >= PLAY_CAP, canonical,
            mine[0].get("appId") or "")


def appstore_count(name: str, delay: float = 0.5
                   ) -> Tuple[Optional[int], bool, str, str]:
    import appstore as apple

    if not name:
        return None, False, name, ""
    cands = apple.artist_candidates(name, country="us", limit=APPLE_LIMIT)
    time.sleep(delay)
    if not cands:
        return None, False, name, ""
    return (len(cands), len(cands) >= APPLE_LIMIT,
            (cands[0].developer or name), cands[0].developer_url)


def _play_developer_url(app_id: str, name: str, delay: float) -> str:
    """Best working developer-page URL for a Play developer.

    Preference order: the developer id the store itself records, then the
    display name, then a pub: search page. Each is checked rather than
    assumed, because a name that reads fine can still 404 - punctuation
    in the id ("Grenge,inc") breaks the developer route entirely.
    """
    import requests
    from google_play_scraper import app as gp
    from urllib.parse import quote

    tries = []
    if app_id:
        try:
            dev_id = str(gp(app_id, lang="en", country="us")
                         .get("developerId") or "")
            time.sleep(delay)
            if dev_id.isdigit():
                tries.append("https://play.google.com/store/apps/dev?id="
                             + dev_id)
            elif dev_id:
                tries.append(sheets.play_developer_url(dev_id))
        except Exception:
            pass
    tries.append(sheets.play_developer_url(name))

    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126 Safari/537.36"}
    for url in tries:
        if not url:
            continue
        try:
            if requests.get(url, headers=ua, timeout=25).status_code == 200:
                return url
        except Exception:
            continue
    return sheets.play_pub_search_url(name)


_CACHE: dict = {}


def count_for(raw: str, delay: float, store: str = "auto") -> dict:
    # Sheets repeat developers (DreamHQ appears three times); look each up once.
    ckey = (raw.strip().lower(), store)
    if ckey in _CACHE:
        return dict(_CACHE[ckey])

    row = _count_for_uncached(raw, delay, store)
    _CACHE[ckey] = dict(row)
    return row


def _count_for_uncached(raw: str, delay: float, store: str = "auto") -> dict:
    detected, name = parse_input(raw)
    # An explicit choice wins, unless the cell itself was a store URL.
    if store != "auto" and not raw.strip().startswith("http"):
        detected = store
    row = {"input": raw.strip(), "developer": name, "store": "", "count": "",
           "exact": "", "note": "", "dev_url": "", "dev_link": ""}
    if not name:
        return row

    order = ["play", "appstore"] if detected == "auto" else [detected]
    for st in order:
        artist_url = sample = ""
        if st == "play":
            n, capped, resolved, sample = play_count(name, delay)
        else:
            n, capped, resolved, artist_url = appstore_count(name, delay)
        if n:
            row["developer"] = resolved or name
            row["dev_url"] = (
                _play_developer_url(sample, row["developer"], delay)
                if st == "play" else artist_url)
            # Show the sheet's own wording, link to the store page.
            row["dev_link"] = sheets.hyperlink(
                row["dev_url"], raw.strip() or row["developer"])
            row["store"] = "Play" if st == "play" else "App Store"
            row["count"] = ("%d+" % n) if capped else str(n)
            row["exact"] = "no" if capped else "yes"
            if capped:
                row["note"] = ("store caps public listings at %d; real total "
                               "is higher" % (PLAY_CAP if st == "play"
                                              else APPLE_LIMIT))
            return row
    row["count"] = "Not found"
    row["note"] = "no developer matched that name"
    return row


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("infile", help="text file, one developer name or URL per line")
    p.add_argument("-o", "--out", default="counts.tsv", help="TSV to write")
    p.add_argument("--delay", type=float, default=0.5,
                   help="seconds between lookups (default 0.5)")
    p.add_argument("--column", default="count", choices=["count", "devlink"],
                   help="column to print for pasting (default: count)")
    p.add_argument("--store", default="auto",
                   choices=["auto", "play", "appstore"],
                   help="force a store instead of auto-detecting")
    args = p.parse_args()

    with open(args.infile, encoding="utf-8") as fh:
        lines = [l.rstrip("\n") for l in fh]

    rows = []
    for i, raw in enumerate(lines, 1):
        if not raw.strip():
            rows.append({"input": "", "developer": "", "store": "",
                         "count": "", "exact": "", "note": ""})
            continue
        row = count_for(raw, args.delay, args.store)
        rows.append(row)
        print("%3d/%d  %-34s %-10s %s" % (i, len(lines),
                                          (row["developer"] or raw)[:34],
                                          row["store"], row["count"]),
              file=sys.stderr)

    cols = ["input", "developer", "store", "count", "exact", "note",
            "dev_url", "dev_link"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")

    key = "dev_link" if args.column == "devlink" else "count"
    print("\n=== copy this column into your sheet (%s) ===" % args.column)
    for r in rows:
        print(r.get(key, ""))
    print("\nTSV written: %s" % args.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
