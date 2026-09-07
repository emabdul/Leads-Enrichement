"""Turn a list of OCR text lines into (app title, publisher) card pairs.

Layout assumption (matches app-store / ad-intel style card grids):
each card shows an icon, then the app title, then the publisher directly
underneath it. The vertical gap between a title and its publisher is much
smaller than the gap between one card row and the next (which contains a
whole icon), so pairing is driven by that gap distribution rather than by
hard-coded pixel sizes.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import List, Optional

from ocr_backends import TextLine

# Leading rating star / bullet glyphs seen on publisher rows. OCR renders the
# star inconsistently (a filled box, a bullet, a tick), so the whole geometric
# shapes block is stripped rather than the few glyphs that showed up in tests.
_LEAD_JUNK = re.compile(
    r"^[\s\*\|:_\-\u00b7\u2022\u2013\u2014\u2212"
    r"\u25a0-\u25ff\u2605\u2606\u22c6\u2b50\u2713\u2714\ufffd]+"
)
# Trailing truncation markers.
_TRUNC = re.compile(r"(\.{2,}|\u2026)\s*$")


@dataclass
class Card:
    title_raw: str
    publisher_raw: str = ""
    box: tuple = (0, 0, 0, 0)  # x0,y0,x1,y1 covering both text lines
    store_hint: str = "unknown"
    country: str = ""  # optional per-card Play storefront override, e.g. "vn"
    notes: List[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        return clean_label(self.title_raw)

    @property
    def publisher(self) -> str:
        return clean_label(self.publisher_raw)

    @property
    def title_truncated(self) -> bool:
        return bool(_TRUNC.search(self.title_raw.strip()))

    @property
    def publisher_truncated(self) -> bool:
        return bool(_TRUNC.search(self.publisher_raw.strip()))


def clean_label(s: str) -> str:
    s = _LEAD_JUNK.sub("", s or "")
    s = _TRUNC.sub("", s.strip())
    return re.sub(r"\s+", " ", s).strip()


def _band_lines(lines: List[TextLine], tol_factor: float = 0.6) -> List[List[TextLine]]:
    """Cluster text lines into horizontal bands by y-centre."""
    if not lines:
        return []
    heights = [l.height for l in lines if l.height > 0] or [10.0]
    tol = max(3.0, statistics.median(heights) * tol_factor)

    bands: List[List[TextLine]] = []
    for line in sorted(lines, key=lambda l: l.cy):
        if bands and abs(line.cy - statistics.mean([b.cy for b in bands[-1]])) <= tol:
            bands[-1].append(line)
        else:
            bands.append([line])
    for band in bands:
        band.sort(key=lambda l: l.x0)
    return bands


def _x_overlap(a: TextLine, b: TextLine) -> float:
    lo = max(a.x0, b.x0)
    hi = min(a.x1, b.x1)
    if hi <= lo:
        return 0.0
    return (hi - lo) / max(1.0, min(a.x1 - a.x0, b.x1 - b.x0))


def _columns(lines: List[TextLine]) -> List[List[TextLine]]:
    """Split lines into card columns by horizontal overlap.

    Text inside one card is left-aligned and overlaps heavily; text in the
    card next door is separated by a gutter and does not overlap at all.
    """
    cols: List[dict] = []
    for line in sorted(lines, key=lambda l: (l.x0, l.y0)):
        best, best_ratio = None, 0.0
        for col in cols:
            overlap = min(line.x1, col["x1"]) - max(line.x0, col["x0"])
            if overlap <= 0:
                continue
            narrower = min(line.x1 - line.x0, col["x1"] - col["x0"])
            ratio = overlap / max(1.0, narrower)
            if ratio > best_ratio:
                best, best_ratio = col, ratio
        if best is not None and best_ratio >= 0.5:
            best["items"].append(line)
            best["x0"] = min(best["x0"], line.x0)
            best["x1"] = max(best["x1"], line.x1)
        else:
            cols.append({"x0": line.x0, "x1": line.x1, "items": [line]})
    return [c["items"] for c in cols]


def _split_cards_vertically(items: List[TextLine], line_h: float
                            ) -> List[List[TextLine]]:
    """Within one column, an icon's worth of blank space separates two cards."""
    items = sorted(items, key=lambda l: l.y0)
    groups: List[List[TextLine]] = [[items[0]]]
    for line in items[1:]:
        if line.y0 - max(x.y1 for x in groups[-1]) > line_h * 3:
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


def _text_rows(items: List[TextLine], line_h: float) -> List[List[TextLine]]:
    """Merge pieces sitting on the same baseline (e.g. a star + publisher)."""
    rows: List[List[TextLine]] = []
    for line in sorted(items, key=lambda l: l.cy):
        if rows and abs(
            line.cy - statistics.mean([r.cy for r in rows[-1]])
        ) <= line_h * 0.6:
            rows[-1].append(line)
        else:
            rows.append([line])
    for row in rows:
        row.sort(key=lambda l: l.x0)
    return rows


def pair_cards(lines: List[TextLine]) -> List[Card]:
    """Group OCR lines into cards, then read title/publisher off each one.

    Segmentation is grid-aware rather than a top-to-bottom walk: split into
    columns, split each column into cards, then take the BOTTOM TWO text rows
    of a card as (title, publisher).

    Taking the bottom two is what makes this survive real screenshots. Cards
    carry extra text ABOVE the title - a country badge like "TH" or "KR"
    printed on the icon - and pairing merely adjacent lines consumes the title
    against that badge, which strands the real publisher as a title with no
    publisher and turns the search into a publisher-only lookup. Everything
    above the last two rows is decoration, so it is ignored.
    """
    lines = [l for l in lines if l.text and l.text.strip()]
    if not lines:
        return []

    heights = [l.height for l in lines if l.height > 0] or [10.0]
    line_h = statistics.median(heights)

    def join(row):
        return " ".join(r.text for r in row).strip()

    def span(row):
        return (min(r.x0 for r in row), min(r.y0 for r in row),
                max(r.x1 for r in row), max(r.y1 for r in row))

    cards: List[Card] = []
    for column in _columns(lines):
        for group in _split_cards_vertically(column, line_h):
            rows = _text_rows(group, line_h)
            if not rows:
                continue
            if len(rows) >= 2:
                tb, pb = span(rows[-2]), span(rows[-1])
                cards.append(Card(
                    title_raw=join(rows[-2]),
                    publisher_raw=join(rows[-1]),
                    box=(min(tb[0], pb[0]), tb[1], max(tb[2], pb[2]), pb[3]),
                ))
            else:
                cards.append(Card(
                    title_raw=join(rows[0]), box=span(rows[0]),
                    notes=["no publisher line matched"],
                ))

    # Reading order: top row of cards first, then left to right within it.
    cards.sort(key=lambda c: (round(c.box[1] / max(1.0, line_h * 4)), c.box[0]))
    return [c for c in cards if c.title]


def detect_store_hint(image, card: Card, line_h: float) -> str:
    """Best-effort guess at the little store badge on the app icon.

    The icon sits directly above the title; its bottom-right corner carries a
    Play Store (multicoloured) or App Store (dark/monochrome) badge. This is a
    colour heuristic, not a classifier - it returns 'unknown' when unsure.
    """
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        return "unknown"

    x0, y0, x1, y1 = card.box
    card_w = max(1.0, x1 - x0)
    icon_bottom = y0 - line_h * 0.3
    icon_top = max(0, icon_bottom - card_w)
    # Badge lives near the icon's bottom-right corner.
    bx0 = int(max(0, x1 - card_w * 0.42))
    bx1 = int(min(image.width, x1 + card_w * 0.06))
    by0 = int(max(0, icon_bottom - card_w * 0.40))
    by1 = int(min(image.height, icon_bottom))
    if bx1 - bx0 < 6 or by1 - by0 < 6 or icon_top >= icon_bottom:
        return "unknown"

    patch = image.crop((bx0, by0, bx1, by1)).convert("HSV")
    pixels = list(patch.getdata())
    if not pixels:
        return "unknown"

    colourful = [p for p in pixels if p[1] > 110 and p[2] > 90]
    dark = [p for p in pixels if p[2] < 90]
    frac_colour = len(colourful) / len(pixels)
    frac_dark = len(dark) / len(pixels)

    if frac_colour >= 0.10:
        hues = {int(p[0] * 360 / 255) // 30 for p in colourful}
        if len(hues) >= 3:
            return "play"
    if frac_dark >= 0.10 and frac_colour < 0.05:
        return "appstore"
    return "unknown"


def parse_names_file(path: str) -> List[Card]:
    """Fallback input, one card per line, bypassing OCR entirely.

        Title <TAB> Publisher <TAB> country

    Publisher and country are optional, and "|" works in place of a tab.
    Country is a Play storefront code (vn, hk, kr...) that overrides
    --country for that row; many of these apps are region-limited.
    """
    cards = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            sep = "\t" if "\t" in raw else ("|" if "|" in raw else None)
            parts = [p.strip() for p in raw.split(sep)] if sep else [raw]
            parts += [""] * (3 - len(parts))
            cards.append(
                Card(
                    title_raw=parts[0],
                    publisher_raw=parts[1],
                    country=parts[2].lower(),
                )
            )
    return cards
