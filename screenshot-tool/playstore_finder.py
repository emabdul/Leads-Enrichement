#!/usr/bin/env python3
"""Find Google Play links for the apps shown in a screenshot of app cards.

Give it an image where each card has an icon, an app title and a publisher
name underneath. It OCRs the labels, pairs each title with its publisher,
searches Google Play, and prints the best-matching store link per card.

    python playstore_finder.py shot.png
    python playstore_finder.py shot.png -o results.csv --json results.json
    python playstore_finder.py --names-file apps.tsv        # skip OCR
    python playstore_finder.py --manual "Coinveyor" "FTY LLC."

Card titles and publishers in these grids are usually cut off with "...".
That is handled: truncated text is matched as a prefix, and several search
phrasings are tried per card because no single one wins for every app.
Always sanity-check anything reported as medium/low confidence.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List

import appstore
import cards as cards_mod
import sheets
from cards import Card, parse_names_file
from matcher import (MIN_DEV_SCORE, MIN_TITLE_SCORE, confidence, find_app,
                     is_match, search_url)

STORE_LABEL = {"play": "Play", "appstore": "App Store"}

# App titles are full of CJK and other non-latin characters; the default
# Windows console codepage raises UnicodeEncodeError on them mid-run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _ocr_cards(args) -> List[Card]:
    from ocr_backends import OcrError, run_ocr

    try:
        backend, lines = run_ocr(args.image, args.ocr)
    except OcrError as exc:
        sys.exit("error: " + str(exc))

    if args.verbose:
        print("OCR backend: {}, {} text lines".format(backend, len(lines)))
        for l in lines:
            print("   [{:6.0f},{:6.0f}] {!r}".format(l.x0, l.y0, l.text))

    found = cards_mod.pair_cards(lines)

    if args.detect_store and found:
        try:
            import statistics

            from PIL import Image

            img = Image.open(args.image).convert("RGB")
            line_h = statistics.median([l.height for l in lines if l.height > 0] or [10])
            for c in found:
                c.store_hint = cards_mod.detect_store_hint(img, c, line_h)
        except Exception as exc:
            print("warning: store-badge detection skipped ({})".format(exc),
                  file=sys.stderr)

    return found


def main() -> int:
    p = argparse.ArgumentParser(
        description="Find Play Store links for apps in a card screenshot.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("image", nargs="?", help="screenshot to read")
    p.add_argument("--names-file", help="TSV of Title<TAB>Publisher instead of OCR")
    p.add_argument(
        "--manual", nargs="+", metavar="TEXT",
        help="look up one app directly: --manual TITLE [PUBLISHER]",
    )
    p.add_argument("-o", "--out", help="write results to this CSV")
    p.add_argument("--json", dest="json_out", help="write results to this JSON")
    p.add_argument(
        "--store", default="both", choices=["both", "play", "appstore"],
        help="which store(s) to search (default: both)",
    )
    p.add_argument("--lang", default="en")
    p.add_argument("--country", default="us", help="Play storefront, e.g. us, kr, vn")
    p.add_argument("--ocr", default="auto", choices=["auto", "rapidocr", "tesseract"])
    p.add_argument("--hits", type=int, default=5, help="results per search query")
    p.add_argument("--max-queries", type=int, default=3, help="query variants per card")
    p.add_argument("--delay", type=float, default=0.6, help="seconds between queries")
    p.add_argument(
        "--min-score", type=float, default=0.65,
        help="below this a result is reported as not found (default 0.65)",
    )
    p.add_argument(
        "--min-title", type=float, default=MIN_TITLE_SCORE,
        help="minimum title score for a match (default %.2f)" % MIN_TITLE_SCORE,
    )
    p.add_argument(
        "--min-dev", type=float, default=MIN_DEV_SCORE,
        help="minimum developer score for a match (default %.2f)" % MIN_DEV_SCORE,
    )
    p.add_argument(
        "--detect-store", action="store_true",
        help="guess the Play/App Store badge on each icon (rough colour heuristic)",
    )
    p.add_argument(
        "--no-deep", dest="deep", action="store_false",
        help="skip the developer-page fallback used for weak matches",
    )
    p.add_argument("--alternatives", action="store_true", help="print runner-up matches")
    p.add_argument("--list-backends", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    if args.list_backends:
        from ocr_backends import available_backends

        found = available_backends()
        print("usable OCR backends:", ", ".join(found) if found else "none")
        return 0

    if args.manual:
        found = [Card(title_raw=args.manual[0],
                      publisher_raw=args.manual[1] if len(args.manual) > 1 else "")]
    elif args.names_file:
        found = parse_names_file(args.names_file)
    elif args.image:
        found = _ocr_cards(args)
    else:
        p.error("give an image, --names-file, or --manual")

    if not found:
        print("No app cards found in the image.")
        print("Tips: crop tighter around the cards, or use a 2x larger screenshot.")
        print("You can also bypass OCR with --names-file (see --help).")
        return 1

    stores = ["play", "appstore"] if args.store == "both" else [args.store]
    print("\nFound {} card(s). Searching {} (storefront {})...\n".format(
        len(found), " + ".join(STORE_LABEL[s] for s in stores), args.country))

    rows = []
    for i, card in enumerate(found, 1):
        label = card.title + (" ..." if card.title_truncated else "")
        pub = card.publisher + (" ..." if card.publisher_truncated else "")
        print("{:>2}. {}{}".format(
            i, label, "   [" + pub + "]" if pub else "   [no publisher]"))

        row = {
            "n": i,
            "card_title": card.title,
            "card_title_truncated": card.title_truncated,
            "card_publisher": card.publisher,
            "card_publisher_truncated": card.publisher_truncated,
            "store_badge_hint": card.store_hint,
            "storefront": card.country or args.country,
        }
        row["alternatives"] = {}

        for store in stores:
            if store == "play":
                best, ranked, problems = find_app(
                    card, lang=args.lang, country=args.country, hits=args.hits,
                    max_queries=args.max_queries, delay=args.delay,
                    verbose=args.verbose, deep=args.deep,
                )
                manual = search_url(card.title, card.publisher)
            else:
                best, ranked, problems = appstore.find_app(
                    card, lang=args.lang, country=args.country, hits=args.hits,
                    max_queries=args.max_queries, delay=args.delay,
                    verbose=args.verbose, deep=args.deep,
                )
                manual = appstore.search_url(
                    card.title, card.publisher, card.country or args.country)

            for msg in problems:
                print("      ! " + msg)

            conf = confidence(best, card)
            matched = is_match(best, card, args.min_score,
                               args.min_title, args.min_dev)
            tag = STORE_LABEL[store]

            if matched:
                print("      {:<10} {:<6} {:.2f}  {}  |  {}".format(
                    tag, conf, best.score, best.title, best.developer))
                print("      {:<10} {}".format("", best.url))
            else:
                print("      {:<10} {:<6}       not found on this store".format(
                    tag, "none"))
                if best:
                    # Keep the near-miss visible, clearly labelled as a guess.
                    print("      {:<10}   closest: {:.2f}  {} | {}".format(
                        "", best.score, best.title, best.developer))
                print("      {:<10}   check by hand: {}".format("", manual))

            if args.alternatives:
                for alt in ranked[1:4]:
                    print("      {:<10}   alt {:.2f}  {} | {}".format(
                        "", alt.score, alt.title, alt.developer))

            row.update({
                store + "_matched": matched,
                store + "_title": best.title if matched else "",
                store + "_developer": best.developer if matched else "",
                store + "_app_id": best.app_id if matched else "",
                store + "_url": best.url if matched else "",
                store + "_score": round(best.score, 3) if best else 0.0,
                store + "_dev_score": round(best.dev_score, 3) if best else 0.0,
                store + "_confidence": conf if matched else "none",
                store + "_closest_title": "" if matched or not best else best.title,
                store + "_closest_url": "" if matched or not best else best.url,
                store + "_search_url": manual,
                # Paste-ready for a spreadsheet: shows the game name,
                # links to the store page.
                store + "_sheet_link": sheets.hyperlink(
                    best.url if matched else "",
                    (best.title if matched else card.title)),
            })
            row["alternatives"][store] = [
                {"app_id": a.app_id, "title": a.title, "developer": a.developer,
                 "score": round(a.score, 3), "url": a.url}
                for a in ranked[1:4]
            ]

        if card.store_hint == "appstore" and "play" in stores:
            print("      note: icon badge looks like App Store; a Play hit may be a clone")
        for note in card.notes:
            print("      note: " + note)
        print()
        rows.append(row)

    for store in stores:
        found_n = sum(1 for r in rows if r[store + "_matched"])
        hi = sum(1 for r in rows if r[store + "_confidence"] == "high")
        print("{:<10} {} found ({} high confidence) out of {}.".format(
            STORE_LABEL[store] + ":", found_n, hi, len(rows)))
    print("'not found on this store' usually means the app is only on the other one.")

    if args.out:
        cols = [c for c in rows[0] if c != "alternatives"]
        with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        print("CSV written: " + args.out)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, ensure_ascii=False)
        print("JSON written: " + args.json_out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
