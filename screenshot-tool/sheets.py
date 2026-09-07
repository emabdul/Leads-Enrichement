"""Build Google Sheets HYPERLINK formulas.

Pasting `=HYPERLINK("url", "text")` into Sheets gives a cell that shows the
name and links to the store page - the same shape as a hand-made hyperlink,
which is what the sheet this feeds already uses.
"""
from __future__ import annotations

from urllib.parse import quote


def hyperlink(url: str, text: str) -> str:
    """A Sheets formula, or plain text when there is no URL to link to."""
    text = (text or "").strip()
    url = (url or "").strip()
    if not url:
        return text
    if not text:
        text = url
    # Inside a Sheets string literal a double quote is escaped by doubling it.
    return '=HYPERLINK("%s","%s")' % (url.replace('"', '%22'),
                                      text.replace('"', '""'))


def play_developer_url(name: str) -> str:
    """Developer page for an exact Play developer name."""
    name = (name or "").strip()
    if not name:
        return ""
    return "https://play.google.com/store/apps/developer?id=" + quote(name)


def play_pub_search_url(name: str) -> str:
    """Fallback landing page listing a publisher's apps.

    Some developer pages simply do not resolve - "Grenge,inc" 404s under
    every encoding because of the comma - so this guarantees the link in
    the sheet still lands somewhere that shows their apps.
    """
    return ("https://play.google.com/store/search?q="
            + quote('pub:"%s"' % (name or "")) + "&c=apps")


def play_app_url(app_id: str) -> str:
    app_id = (app_id or "").strip()
    if not app_id:
        return ""
    return "https://play.google.com/store/apps/details?id=" + app_id
