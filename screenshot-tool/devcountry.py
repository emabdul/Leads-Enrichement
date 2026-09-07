"""Work out a Play developer's country from their store listing.

Google exposes a postal address under "About the developer" on each app page.
The scraper library returns None for it, so the page is fetched directly and
the country read off the end of the address.
"""
from __future__ import annotations

import re
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126 Safari/537.36",
      "Accept-Language": "en-US,en;q=0.9"}

# Names as Google writes them, plus the aliases that show up in addresses.
COUNTRIES = [
    "United States", "United Kingdom", "United Arab Emirates", "South Korea",
    "Korea", "Hong Kong", "Singapore", "India", "Japan", "China", "Taiwan",
    "Vietnam", "Viet Nam", "Thailand", "Indonesia", "Malaysia", "Philippines",
    "Pakistan", "Bangladesh", "Sri Lanka", "Nepal", "Turkey", "Türkiye",
    "Cyprus", "Israel", "Egypt", "Morocco", "Nigeria", "Kenya", "South Africa",
    "Australia", "New Zealand", "Canada", "Mexico", "Brazil", "Argentina",
    "Chile", "Colombia", "Peru", "Germany", "France", "Spain", "Portugal",
    "Italy", "Netherlands", "Belgium", "Switzerland", "Austria", "Sweden",
    "Norway", "Denmark", "Finland", "Iceland", "Ireland", "Poland", "Czechia",
    "Czech Republic", "Slovakia", "Hungary", "Romania", "Bulgaria", "Greece",
    "Croatia", "Slovenia", "Serbia", "Ukraine", "Belarus", "Russia",
    "Kazakhstan", "Uzbekistan", "Azerbaijan", "Georgia", "Armenia", "Estonia",
    "Latvia", "Lithuania", "Luxembourg", "Malta", "Monaco", "Cayman Islands",
    "British Virgin Islands", "Seychelles", "Mauritius", "Panama", "Uruguay",
    "Saudi Arabia", "Qatar", "Kuwait", "Bahrain", "Oman", "Jordan", "Lebanon",
]
ALIAS = {"Viet Nam": "Vietnam", "Korea": "South Korea", "Türkiye": "Turkey",
         "Czechia": "Czech Republic"}

_ADDR = re.compile(r'"((?:[^"\\]|\\.){12,160})"')


def _country_from(text: str):
    """Longest country name appearing in the address wins ('United States'
    must beat 'States'-style partials, and 'Hong Kong' beat 'Kong')."""
    best = None
    for name in COUNTRIES:
        if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(name), text,
                     re.IGNORECASE):
            if best is None or len(name) > len(best):
                best = name
    return ALIAS.get(best, best) if best else None


_DEV_BLOCK = re.compile(
    r'\["([^"]{1,80})",\["([^"@]+@[^"]+)"\],\["([^"]{0,220})"\],"([^"]{0,40})"')


def play_contact(app_id: str, timeout: int = 40):
    """(country, phone, address) from a Play app page.

    Google's "About the developer" block carries legal name, email, postal
    address and phone as one array; reading it gives country and phone in a
    single fetch. Falls back to scanning for an address when the block is
    missing (older listings).
    """
    if not app_id:
        return None, None, None
    url = ("https://play.google.com/store/apps/details?id=%s&hl=en&gl=US"
           % app_id)
    try:
        html = requests.get(url, headers=UA, timeout=timeout).text
    except Exception:
        return None, None, None

    m = _DEV_BLOCK.search(html)
    if m:
        # The page embeds the address with a literal backslash-n, not a real
        # newline, so the two-character sequence is what has to be replaced.
        address = m.group(3).replace("\\n", ", ").strip()
        phone = m.group(4).strip()
        return _country_from(address), phone, address

    country, address = play_country(app_id, timeout)
    return country, None, address


def play_country(app_id: str, timeout: int = 40):
    """(country, raw address) for a Play app id, or (None, None)."""
    if not app_id:
        return None, None
    url = ("https://play.google.com/store/apps/details?id=%s&hl=en&gl=US"
           % app_id)
    try:
        html = requests.get(url, headers=UA, timeout=timeout).text
    except Exception:
        return None, None

    # An address is a quoted blob with a line break in it; keep the last one
    # that names a country, which is the developer block near the page end.
    hit = None
    for raw in _ADDR.findall(html):
        if "\\n" not in raw:
            continue
        country = _country_from(raw.replace("\\n", ", "))
        if country:
            hit = (country, raw.replace("\\n", ", "))
    if hit:
        return hit
    return None, None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    for pid in sys.argv[1:]:
        c, a = play_country(pid)
        print("%-46s %-16s %s" % (pid[:46], c or "-", (a or "")[:60]))
