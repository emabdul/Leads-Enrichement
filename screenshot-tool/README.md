# Screenshot → store links

Finds the Play Store / App Store page for each app in a **screenshot** of app
cards — the case the Chrome extension cannot cover, since it only reads live
AppBird pages.

Reach for this when the games arrive as an image rather than a page you can
scan.

## Setup

```
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Keep the folder path short. `onnxruntime` and `Pillow` fail to load their DLLs
from very deep directories with `ImportError: DLL load failed ... filename or
extension is too long`.

## Use

Double-click `run_gui.bat`, or:

```
run_gui.bat                       window: paste a screenshot with Ctrl+V
run.bat shot.png -o results.csv   command line
run.bat --names-file apps.tsv     skip OCR, feed names directly
run.bat --manual "Coinveyor" "FTY LLC."
```

In the window: **Ctrl+V** to paste a screenshot → check the detected list →
**Search**. Double-click a result row to open it. There is a second tab that
counts a developer's published apps.

The detected list is editable on purpose. OCR on small card labels is good but
not perfect — it merges words ("WEMIXGlobal") — and a wrong publisher is what
stops a brand-new app from being found. Fixing a line by hand there is faster
than re-cropping.

## How matching works

Card labels are usually cut off ("Voxel Blast: Cub…", "jennywhiteshri…"), so
truncated text is matched as a **prefix**, and several search phrasings are
tried per card because no single one wins for every app.

A result only counts as a match when the **developer** corresponds, not just
the title. That is what separates a clone — Play returns a
`Sizzle Master: BBQ Jam Sort!` by a different studio — from the real listing.
Anything failing that prints as `not found on this store` with the near miss
shown, rather than becoming a confident wrong link.

Play exposes at most 50 apps per developer through any public endpoint, so a
developer at the ceiling reads `50+` rather than an understated number.

## Files

| File | Role |
|---|---|
| `gui.py` | the window (screenshot tab + developer-count tab) |
| `playstore_finder.py` | command-line version |
| `ocr_backends.py` | rapidocr / tesseract, auto-selected |
| `cards.py` | splits the card grid, pairs title with publisher |
| `matcher.py` | Play search, query variants, match scoring |
| `appstore.py` | App Store lookup via the iTunes API |
| `dev_app_count.py` | how many apps a developer has published |
| `devcountry.py` | developer country/phone from a Play listing |
| `sheets.py` | HYPERLINK formula helpers |
| `make_test_image*.py` | synthetic card grids for testing |
