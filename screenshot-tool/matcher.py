"""Search Google Play for a card's app and score the candidates.

Titles and publishers scraped off a card grid are usually truncated
("Voxel Blast: Cub...", "jennywhiteshri..."), so matching is prefix-aware.
A single query is unreliable - adding the publisher to the query helps for
some apps and actively hurts for others - so several query variants are run
and their results pooled before scoring.
"""
from __future__ import annotations

import difflib
import re
import time
from dataclasses import dataclass
from typing import List, Optional

_PUNCT = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    s = (s or "").lower().replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    return _WS.sub(" ", s).strip()


@dataclass
class Candidate:
    app_id: str
    title: str
    developer: str
    score: float = 0.0
    title_score: float = 0.0
    dev_score: float = 0.0
    store: str = "play"
    url_override: str = ""
    developer_url: str = ""   # the developer/artist page, for sheet links
    developer_id: str = ""    # numeric artist id (App Store)  # App Store supplies a full URL of its own

    @property
    def url(self) -> str:
        if self.url_override:
            return self.url_override
        return f"https://play.google.com/store/apps/details?id={self.app_id}"


def _score_pair(o: str, c: str, truncated: bool) -> float:
    if truncated:
        if c.startswith(o):
            return 1.0
        # Compare only the part of the candidate the card could have shown.
        return difflib.SequenceMatcher(None, o, c[: len(o)]).ratio() * 0.95
    if o == c:
        return 1.0
    if c.startswith(o) or o.startswith(c):
        return 0.93
    return difflib.SequenceMatcher(None, o, c).ratio()


def _field_score(observed: str, candidate: str, truncated: bool) -> float:
    """How well a (possibly truncated) observed string matches a candidate."""
    o, c = norm(observed), norm(candidate)
    if not o or not c:
        return 0.0
    # OCR regularly drops the space between words ("HooksJam", "WEMIXGlobal"),
    # so also compare with all spaces removed and keep whichever reading fits.
    return max(
        _score_pair(o, c, truncated),
        _score_pair(o.replace(" ", ""), c.replace(" ", ""), truncated),
    )


def _clean_query(q: str) -> str:
    """Punctuation-heavy queries make the Play endpoint return unparseable data."""
    q = re.sub(r"[:,;|/\\[\]{}()\"']+", " ", q or "")
    return _WS.sub(" ", q).strip()


def search_url(title: str, publisher: str = "") -> str:
    """A human-checkable Play search link, for cards the API cannot resolve."""
    from urllib.parse import quote_plus

    q = _clean_query((title + " " + (publisher or "")).strip())
    return "https://play.google.com/store/search?q=" + quote_plus(q) + "&c=apps"


def query_variants(title: str, publisher: str) -> List[str]:
    out = []
    if title and publisher:
        out.append(f"{title} {publisher}")
    if title:
        out.append(title)
        # Drop a trailing partial word from a truncated title ("Voxel Blast: Cub").
        words = title.split()
        if len(words) > 1:
            trimmed = " ".join(words[:-1])
            if trimmed and trimmed not in out:
                out.append(trimmed)
    if publisher and publisher not in out:
        out.append(publisher)
    seen, uniq = set(), []
    for q in out:
        q = _clean_query(q)
        k = norm(q)
        if k and k not in seen:
            seen.add(k)
            uniq.append(q)
    return uniq


_PKG_RE = re.compile(r"id=([a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)+)")
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def _spacing_variants(publisher: str) -> List[str]:
    """The publisher as OCR read it, plus a case-split repair of merged words.

    OCR regularly drops the space between two words ("WEMIXGlobal"), and the
    developer page needs the name character-exact, so the merged form 404s.
    The split almost always survives as a case boundary, so restore it:
    lower-to-upper ("HooksJam") and acronym-to-word ("WEMIXGlobal").
    """
    out = [publisher]
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", publisher)
    split = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", split)
    if split != publisher:
        out.append(split)
    return out


def developer_candidates(
    publisher: str, lang: str = "en", country: str = "us",
    limit: int = 12, verbose: bool = False,
) -> List[Candidate]:
    """List a publisher's apps straight off their Play developer page.

    Play's search index does not contain brand-new listings - an app published
    yesterday is simply not findable by any query - but the developer's own
    page lists it immediately. This is the only way to reach those.

    Requires the EXACT developer name: a truncated one 404s, and a shortened
    one can silently land on a different developer. Callers must therefore
    only pass a publisher that was not cut off on the card.
    """
    import requests
    from google_play_scraper import app as gp_app

    out: List[Candidate] = []
    for name in _spacing_variants(publisher):
        for url in (
            "https://play.google.com/store/apps/developer?id={}&hl={}&gl={}",
            "https://play.google.com/store/search?q=pub%3A%22{}%22&c=apps&hl={}&gl={}",
        ):
            try:
                from urllib.parse import quote

                resp = requests.get(
                    url.format(quote(name), lang, country), headers=_UA, timeout=30
                )
                if resp.status_code != 200:
                    continue
                ids = [
                    i for i in dict.fromkeys(_PKG_RE.findall(resp.text))
                    if not i.startswith(("com.google.", "com.android."))
                ]
            except Exception as exc:
                if verbose:
                    print(f"      developer page failed: {type(exc).__name__}: {exc}")
                continue

            for app_id in ids[:limit]:
                try:
                    info = gp_app(app_id, lang=lang, country=country)
                except Exception:
                    continue
                out.append(Candidate(app_id=app_id, title=info.get("title") or "",
                                     developer=info.get("developer") or ""))
            if out:
                break
        if out:
            if verbose:
                print(f"      developer page -> {len(out)} app(s) for {name!r}")
            return out
    if verbose:
        print(f"      developer page -> nothing for {publisher!r}")
    return out


def find_app(
    card,
    lang: str = "en",
    country: str = "us",
    hits: int = 5,
    max_queries: int = 3,
    delay: float = 0.6,
    verbose: bool = False,
    deep: bool = True,
) -> tuple[Optional[Candidate], List[Candidate], List[str]]:
    from google_play_scraper import search
    from google_play_scraper.exceptions import GooglePlayScraperException

    problems: List[str] = []
    pool: dict[str, Candidate] = {}
    country = (getattr(card, "country", "") or country).lower()

    for i, q in enumerate(query_variants(card.title, card.publisher)[:max_queries]):
        if i:
            time.sleep(delay)
        try:
            results = search(q, n_hits=hits, lang=lang, country=country)
        except GooglePlayScraperException as exc:
            problems.append(f"query {q!r} failed: {exc}")
            continue
        except TypeError:
            # google-play-scraper raises this while parsing a zero-result
            # response. It means "nothing found", not a real failure.
            if verbose:
                print(f"      query {q!r} -> no results")
            continue
        except Exception as exc:
            problems.append(f"query {q!r} failed: {type(exc).__name__}: {exc}")
            continue
        if verbose:
            print(f"      query {q!r} -> {len(results)} hits")
        for r in results:
            app_id = r.get("appId")
            if app_id and app_id not in pool:
                pool[app_id] = Candidate(
                    app_id=app_id,
                    title=r.get("title") or "",
                    developer=r.get("developer") or "",
                )

    def rescore():
        for c in pool.values():
            c.title_score = _field_score(card.title, c.title, card.title_truncated)
            c.dev_score = (
                _field_score(card.publisher, c.developer, card.publisher_truncated)
                if card.publisher else 0.0
            )
            c.score = (0.55 * c.title_score + 0.45 * c.dev_score
                       if card.publisher else c.title_score)

    rescore()
    best_so_far = max((c.score for c in pool.values()), default=0.0)

    # Search cannot see brand-new listings. Fall back to the publisher's own
    # developer page, but only when the card showed their full name - a
    # truncated one resolves to the wrong developer or to nothing at all.
    if deep and best_so_far < 0.85 and card.publisher and not card.publisher_truncated:
        if verbose:
            print(f"      weak match ({best_so_far:.2f}), trying developer page")
        for cand in developer_candidates(card.publisher, lang, country, verbose=verbose):
            pool.setdefault(cand.app_id, cand)
        rescore()

    ranked = sorted(pool.values(), key=lambda c: c.score, reverse=True)
    best = ranked[0] if ranked else None
    return best, ranked[:5], problems


# Title and developer are gated separately, because the two ways a wrong app
# gets returned fail on different fields and a combined score hides both:
#
#   clone            right title, wrong developer  ByteTiger 0.29, Codore 0.67
#   same publisher   right developer, wrong title  "Mowing Master" by the real
#                                                  FTY LLC., title 0.48
#
# Measured over the example screenshot, every genuine match scored 1.00 on
# both fields while no wrong answer cleared 0.75 combined - so these floors sit
# in a wide empty gap rather than being tuned to the edge of the data.
# A publisher's own catalogue is the hard case: "Arrow Path Solve Puzzle"
# and "Arrow Flow Path Solver" share a developer, so only the title tells
# them apart (0.74 vs 0.93). 0.80 sits mid-band of the values that classify
# every labelled case correctly.
MIN_TITLE_SCORE = 0.80
MIN_DEV_SCORE = 0.78


def is_match(cand: Optional[Candidate], card, min_score: float = 0.65,
             min_title: float = MIN_TITLE_SCORE,
             min_dev: float = MIN_DEV_SCORE) -> bool:
    """Is this candidate the app on the card, or just the closest thing found?

    Searching two stores means most cards get a plausible-looking result from
    the store they are not on, so "closest result" must not be reported as
    "found". A wrong link is worse than an honest miss, hence the strictness.
    """
    if cand is None:
        return False
    if cand.score < min_score:
        return False
    if cand.title_score < min_title:
        return False
    if card.publisher and cand.dev_score < min_dev:
        return False
    return True


def confidence(cand: Optional[Candidate], card) -> str:
    if cand is None:
        return "none"
    if cand.score >= 0.90 and (not card.publisher or cand.dev_score >= 0.80):
        return "high"
    if cand.score >= 0.72:
        return "medium"
    return "low"
