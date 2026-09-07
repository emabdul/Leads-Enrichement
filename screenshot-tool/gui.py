#!/usr/bin/env python3
"""Tkinter front end: paste a screenshot, get store links.

    run_gui.bat          (or:  .venv\\Scripts\\python gui.py)

Flow: paste an image with Ctrl+V -> OCR fills in an editable Title/Publisher
list -> Search -> results table with clickable links.

The editable middle step is deliberate. OCR on small card labels is good but
not perfect (it merges words, e.g. "WEMIXGlobal"), and a wrong publisher is
what stops a brand-new app from being found. Fixing a line by hand there is
faster than re-cropping the screenshot.
"""
from __future__ import annotations

import csv
import os
import queue
import sys
import tempfile
import threading


def _fix_tcl_paths() -> None:
    """Point Tcl/Tk at the base install when running from a venv.

    Windows venvs do not copy the tcl/ tree, and the interpreter only looks
    for it beside sys.prefix, so importing tkinter from .venv dies with
    "Can't find a usable init.tcl". The files exist under sys.base_prefix.
    """
    if os.name != "nt" or sys.prefix == sys.base_prefix:
        return
    tcl_root = os.path.join(sys.base_prefix, "tcl")
    if not os.path.isdir(tcl_root):
        return
    for name in sorted(os.listdir(tcl_root)):
        full = os.path.join(tcl_root, name)
        if not os.path.isdir(full):
            continue
        if name.startswith("tcl8.") and "TCL_LIBRARY" not in os.environ:
            os.environ["TCL_LIBRARY"] = full
        elif name.startswith("tk8.") and "TK_LIBRARY" not in os.environ:
            os.environ["TK_LIBRARY"] = full


_fix_tcl_paths()

import tkinter as tk  # noqa: E402
import webbrowser  # noqa: E402
from tkinter import filedialog, messagebox, ttk  # noqa: E402

import appstore
import cards as cards_mod
import sheets
from cards import Card
from matcher import confidence, find_app, is_match, search_url

APP_TITLE = "App Store Link Finder"
STORE_LABEL = {"play": "Play", "appstore": "App Store"}


class Finder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(940, 600)

        self.image = None          # PIL image currently loaded
        self.image_path = None     # temp path handed to the OCR backend
        self.rows = []             # result rows, for CSV export
        self.count_rows = []       # developer-count rows, for TSV export
        self.queue: queue.Queue = queue.Queue()
        self.busy = False

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.tab_links = ttk.Frame(self.nb)
        self.tab_counts = ttk.Frame(self.nb)
        self.nb.add(self.tab_links, text="  Screenshot → Store Links  ")
        self.nb.add(self.tab_counts, text="  Developer App Counts  ")

        self._build(self.tab_links)
        self._build_counts(self.tab_counts)
        self._build_footer()

        self.bind_all("<Control-v>", lambda e: self.paste())
        self.bind_all("<Control-V>", lambda e: self.paste())
        self.after(100, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self, root):
        bar = ttk.Frame(root, padding=(10, 8))
        bar.pack(fill="x")

        ttk.Button(bar, text="Paste Screenshot  (Ctrl+V)",
                   command=self.paste).pack(side="left")
        ttk.Button(bar, text="Open Image…",
                   command=self.open_image).pack(side="left", padx=(6, 0))

        ttk.Label(bar, text="Store:").pack(side="left", padx=(18, 4))
        self.store = tk.StringVar(value="both")
        for label, val in (("Both", "both"), ("Play", "play"),
                           ("App Store", "appstore")):
            ttk.Radiobutton(bar, text=label, value=val,
                            variable=self.store).pack(side="left")

        ttk.Label(bar, text="Country:").pack(side="left", padx=(18, 4))
        self.country = tk.StringVar(value="us")
        ttk.Entry(bar, textvariable=self.country, width=5).pack(side="left")

        self.search_btn = ttk.Button(bar, text="Search",
                                     command=self.start_search)
        self.search_btn.pack(side="right")

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        # left: preview + editable card list
        left = ttk.Frame(panes)
        panes.add(left, weight=1)

        self.preview = ttk.Label(left, text="Paste a screenshot (Ctrl+V)",
                                 anchor="center", relief="groove", padding=10)
        self.preview.pack(fill="x")

        ttk.Label(left, text="Detected cards — edit if OCR got one wrong "
                             "(Title <TAB> Publisher):").pack(
            anchor="w", pady=(10, 2))
        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True)
        self.text = tk.Text(wrap, height=12, wrap="none", undo=True)
        ysb = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)

        # right: results
        right = ttk.Frame(panes)
        panes.add(right, weight=2)

        cols = ("app", "publisher", "store", "conf", "url")
        self.tree = ttk.Treeview(right, columns=cols, show="headings",
                                 selectmode="browse")
        for key, head, width in (
            ("app", "App", 230), ("publisher", "Publisher", 180),
            ("store", "Store", 80), ("conf", "Confidence", 90),
            ("url", "Link  (double-click to open)", 420),
        ):
            self.tree.heading(key, text=head)
            self.tree.column(key, width=width, anchor="w")
        tsb = ttk.Scrollbar(right, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Double-1>", self.open_link)
        self.tree.tag_configure("miss", foreground="#999999")

        acts = ttk.Frame(root, padding=(10, 0, 10, 8))
        acts.pack(fill="x")
        ttk.Button(acts, text="Export CSV…",
                   command=self.export_csv).pack(side="right")
        ttk.Button(acts, text="Copy All Links",
                   command=self.copy_links).pack(side="right", padx=(0, 6))
        ttk.Button(acts, text="Copy for Sheets (hyperlinks)",
                   command=self.copy_link_formulas).pack(side="right",
                                                         padx=(0, 6))

    def _build_counts(self, root):
        bar = ttk.Frame(root, padding=(10, 8))
        bar.pack(fill="x")
        ttk.Label(bar, text="Store:").pack(side="left")
        self.count_store = tk.StringVar(value="auto")
        for label, val in (("Auto", "auto"), ("Play", "play"),
                           ("App Store", "appstore")):
            ttk.Radiobutton(bar, text=label, value=val,
                            variable=self.count_store).pack(side="left")
        self.count_btn = ttk.Button(bar, text="Count Apps",
                                    command=self.start_counts)
        self.count_btn.pack(side="right")

        panes = ttk.PanedWindow(root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        left = ttk.Frame(panes)
        panes.add(left, weight=1)
        ttk.Label(left, text="Paste your Developer Name column here — one per "
                             "line.\nBlank lines are kept, so the result column "
                             "stays row-aligned with your sheet.").pack(
            anchor="w", pady=(0, 4))
        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True)
        self.count_text = tk.Text(wrap, height=20, wrap="none", undo=True)
        ysb = ttk.Scrollbar(wrap, orient="vertical",
                            command=self.count_text.yview)
        self.count_text.configure(yscrollcommand=ysb.set)
        ysb.pack(side="right", fill="y")
        self.count_text.pack(side="left", fill="both", expand=True)

        right = ttk.Frame(panes)
        panes.add(right, weight=2)
        cols = ("input", "resolved", "store", "count", "note")
        self.ctree = ttk.Treeview(right, columns=cols, show="headings",
                                  selectmode="browse")
        for key, head, width in (
            ("input", "Developer (from sheet)", 220),
            ("resolved", "Resolved name on store", 220),
            ("store", "Store", 80), ("count", "Games", 70),
            ("note", "Note", 260),
        ):
            self.ctree.heading(key, text=head)
            self.ctree.column(key, width=width, anchor="w")
        tsb = ttk.Scrollbar(right, orient="vertical", command=self.ctree.yview)
        self.ctree.configure(yscrollcommand=tsb.set)
        tsb.pack(side="right", fill="y")
        self.ctree.pack(side="left", fill="both", expand=True)
        self.ctree.tag_configure("miss", foreground="#999999")

        acts = ttk.Frame(root, padding=(10, 0, 10, 8))
        acts.pack(fill="x")
        ttk.Button(acts, text="Export TSV…",
                   command=self.export_counts).pack(side="right")
        ttk.Button(acts, text="Copy Count Column",
                   command=self.copy_counts).pack(side="right", padx=(0, 6))
        ttk.Button(acts, text="Copy Developer Hyperlinks",
                   command=self.copy_dev_links).pack(side="right",
                                                     padx=(0, 6))

    def _build_footer(self):
        foot = ttk.Frame(self, padding=(10, 0, 10, 10))
        foot.pack(fill="x")
        self.status = ttk.Label(foot, text="Ready.")
        self.status.pack(side="left")
        self.bar = ttk.Progressbar(foot, mode="determinate", length=220)
        self.bar.pack(side="right", padx=(0, 12))

    # ------------------------------------------------------ developer counts
    def start_counts(self):
        if self.busy:
            return
        lines = self.count_text.get("1.0", "end").rstrip("\n").split("\n")
        if not any(l.strip() for l in lines):
            messagebox.showinfo(APP_TITLE,
                                "Paste your Developer Name column first.")
            return
        self.busy = True
        self.count_btn.state(["disabled"])
        self.ctree.delete(*self.ctree.get_children())
        self.count_rows = []
        self.bar.configure(maximum=len(lines), value=0)
        threading.Thread(target=self._counts_worker,
                         args=(lines, self.count_store.get()),
                         daemon=True).start()

    def _counts_worker(self, lines, store):
        import dev_app_count as dac
        try:
            for raw in lines:
                if not raw.strip():
                    # Preserve the blank so pasted output lines up with the sheet.
                    row = {"input": "", "developer": "", "store": "",
                           "count": "", "exact": "", "note": ""}
                else:
                    row = dac.count_for(raw, 0.5, store)
                self.queue.put(("crow", row))
            self.queue.put(("cdone", len(lines)))
        except Exception as exc:
            self.queue.put(("error", "Counting failed:\n%s" % exc))

    def copy_counts(self):
        if not self.count_rows:
            messagebox.showinfo(APP_TITLE, "Nothing counted yet.")
            return
        text = "\n".join(str(r.get("count", "")) for r in self.count_rows)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("Copied %d rows — paste into your sheet's new column."
                        % len(self.count_rows))

    def copy_dev_links(self):
        """A HYPERLINK column: sheet's wording, developer page URL."""
        if not self.count_rows:
            messagebox.showinfo(APP_TITLE, "Nothing counted yet.")
            return
        text = "\n".join(str(r.get("dev_link", "") or r.get("input", ""))
                         for r in self.count_rows)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("Copied %d developer hyperlink(s)."
                        % len(self.count_rows))

    def export_counts(self):
        if not self.count_rows:
            messagebox.showinfo(APP_TITLE, "Nothing counted yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".tsv", initialfile="counts.tsv",
            filetypes=[("TSV", "*.tsv"), ("All files", "*.*")])
        if not path:
            return
        cols = ["input", "developer", "store", "count", "exact", "note",
                "dev_url", "dev_link"]
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            fh.write("\t".join(cols) + "\n")
            for r in self.count_rows:
                fh.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
        self.set_status("Saved %s" % path)

    # ------------------------------------------------------------- image in
    def paste(self):
        try:
            from PIL import ImageGrab
        except ImportError:
            messagebox.showerror(APP_TITLE, "Pillow is not installed.")
            return
        try:
            grabbed = ImageGrab.grabclipboard()
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "Could not read clipboard:\n%s" % exc)
            return

        if isinstance(grabbed, list):  # files were copied, not a bitmap
            paths = [p for p in grabbed
                     if str(p).lower().endswith((".png", ".jpg", ".jpeg", ".bmp"))]
            if not paths:
                messagebox.showinfo(APP_TITLE, "No image found on the clipboard.")
                return
            self._load(paths[0])
            return
        if grabbed is None:
            messagebox.showinfo(
                APP_TITLE,
                "No image on the clipboard.\n\n"
                "Copy a screenshot first — Win+Shift+S, or right-click an "
                "image and choose Copy image.")
            return
        self._set_image(grabbed)

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Open screenshot",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp"), ("All files", "*.*")])
        if path:
            self._load(path)

    def _load(self, path):
        from PIL import Image
        try:
            self._set_image(Image.open(path), path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, "Could not open image:\n%s" % exc)

    def _set_image(self, img, path=None):
        from PIL import Image, ImageTk

        self.image = img.convert("RGB")
        if path is None:
            fd, path = tempfile.mkstemp(suffix=".png", prefix="pasted_")
            os.close(fd)
            self.image.save(path)
        self.image_path = path

        thumb = self.image.copy()
        thumb.thumbnail((520, 240), Image.LANCZOS)
        self._thumb = ImageTk.PhotoImage(thumb)
        self.preview.configure(image=self._thumb, text="")
        self.set_status("Image loaded (%d x %d). Reading text…"
                        % self.image.size)
        threading.Thread(target=self._ocr_worker, daemon=True).start()

    # ----------------------------------------------------------------- OCR
    def _ocr_worker(self):
        try:
            from ocr_backends import run_ocr
            backend, lines = run_ocr(self.image_path, "auto")
            found = cards_mod.pair_cards(lines)
            self.queue.put(("ocr", backend, found))
        except Exception as exc:
            self.queue.put(("error", "OCR failed:\n%s" % exc))

    def _fill_text(self, found):
        self.text.delete("1.0", "end")
        for c in found:
            self.text.insert("end", "%s\t%s\n" % (c.title, c.publisher))

    # -------------------------------------------------------------- search
    def _cards_from_text(self):
        out = []
        for raw in self.text.get("1.0", "end").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            sep = "\t" if "\t" in raw else ("|" if "|" in raw else None)
            parts = [p.strip() for p in raw.split(sep)] if sep else [raw]
            parts += [""] * (3 - len(parts))
            out.append(Card(title_raw=parts[0], publisher_raw=parts[1],
                            country=parts[2].lower()))
        return out

    def start_search(self):
        if self.busy:
            return
        found = self._cards_from_text()
        if not found:
            messagebox.showinfo(APP_TITLE,
                                "Nothing to search — paste a screenshot, or "
                                "type 'Title<TAB>Publisher' lines.")
            return
        self.busy = True
        self.search_btn.state(["disabled"])
        self.tree.delete(*self.tree.get_children())
        self.rows = []
        stores = (["play", "appstore"] if self.store.get() == "both"
                  else [self.store.get()])
        self.bar.configure(maximum=len(found) * len(stores), value=0)
        threading.Thread(target=self._search_worker,
                         args=(found, stores, self.country.get().strip() or "us"),
                         daemon=True).start()

    def _search_worker(self, found, stores, country):
        try:
            for i, card in enumerate(found, 1):
                row = {"n": i, "card_title": card.title,
                       "card_publisher": card.publisher}
                for store in stores:
                    mod = find_app if store == "play" else appstore.find_app
                    try:
                        best, _ranked, _problems = mod(
                            card, country=country, verbose=False)
                    except Exception as exc:
                        best = None
                        self.queue.put(("status", "%s error: %s" % (store, exc)))
                    matched = is_match(best, card)
                    conf = confidence(best, card) if matched else "none"
                    row.update({
                        store + "_matched": matched,
                        store + "_title": best.title if matched else "",
                        store + "_developer": best.developer if matched else "",
                        store + "_url": best.url if matched else "",
                        store + "_score": round(best.score, 3) if best else 0.0,
                        store + "_confidence": conf,
                        store + "_search_url": (
                            search_url(card.title, card.publisher)
                            if store == "play" else
                            appstore.search_url(card.title, card.publisher, country)),
                    })
                    self.queue.put(("row", card, store, best, matched, conf))
                self.rows.append(row)
            self.queue.put(("done", len(found)))
        except Exception as exc:
            self.queue.put(("error", "Search failed:\n%s" % exc))

    # ------------------------------------------------------------ ui pump
    def _drain(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                kind = msg[0]
                if kind == "ocr":
                    _, backend, found = msg
                    self._fill_text(found)
                    self.set_status("Read %d card(s) with %s. Check the list, "
                                    "then press Search." % (len(found), backend))
                elif kind == "row":
                    _, card, store, best, matched, conf = msg
                    if matched:
                        self.tree.insert("", "end", values=(
                            best.title, best.developer, STORE_LABEL[store],
                            conf, best.url))
                    else:
                        closest = ("closest: %s" % best.title) if best else "—"
                        self.tree.insert("", "end", tags=("miss",), values=(
                            card.title, card.publisher, STORE_LABEL[store],
                            "not found", closest))
                    self.bar.step(1)
                    self.set_status("Searching… %d result(s)"
                                    % len(self.tree.get_children()))
                elif kind == "crow":
                    row = msg[1]
                    self.count_rows.append(row)
                    if row["input"]:
                        found = str(row.get("count", "")) not in ("", "Not found")
                        self.ctree.insert(
                            "", "end", tags=() if found else ("miss",),
                            values=(row["input"], row.get("developer", ""),
                                    row.get("store", ""), row.get("count", ""),
                                    row.get("note", "")))
                    self.bar.step(1)
                    self.set_status("Counting… %d of %d"
                                    % (len(self.count_rows), self.bar["maximum"]))
                elif kind == "cdone":
                    self.busy = False
                    self.count_btn.state(["!disabled"])
                    hits = sum(1 for r in self.count_rows
                               if str(r.get("count", "")) not in ("", "Not found"))
                    self.set_status(
                        "Done. %d of %d developer(s) counted. Use Copy Count "
                        "Column, then paste into your sheet."
                        % (hits, sum(1 for r in self.count_rows if r["input"])))
                elif kind == "status":
                    self.set_status(msg[1])
                elif kind == "done":
                    self.busy = False
                    self.search_btn.state(["!disabled"])
                    hits = sum(1 for r in self.rows
                               if r.get("play_matched") or r.get("appstore_matched"))
                    self.set_status("Done. %d of %d card(s) matched to a store."
                                    % (hits, msg[1]))
                elif kind == "error":
                    self.busy = False
                    self.search_btn.state(["!disabled"])
                    self.set_status("Error.")
                    messagebox.showerror(APP_TITLE, msg[1])
        except queue.Empty:
            pass
        self.after(100, self._drain)

    def set_status(self, text):
        self.status.configure(text=text)

    # ------------------------------------------------------------- outputs
    def open_link(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        url = self.tree.item(sel[0], "values")[4]
        if url.startswith("http"):
            webbrowser.open(url)

    def copy_link_formulas(self):
        """One HYPERLINK formula per result row, ready to paste."""
        out = []
        for i in self.tree.get_children():
            name, _pub, _store, _conf, url = self.tree.item(i, "values")
            out.append(sheets.hyperlink(url, name)
                       if str(url).startswith("http") else name)
        if not out:
            messagebox.showinfo(APP_TITLE, "No results yet.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(out))
        self.set_status("Copied %d hyperlink formula(s) — paste into "
                        "Sheets." % len(out))

    def copy_links(self):
        urls = [v for v in (self.tree.item(i, "values")[4]
                            for i in self.tree.get_children())
                if v.startswith("http")]
        if not urls:
            messagebox.showinfo(APP_TITLE, "No links to copy yet.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(urls))
        self.set_status("Copied %d link(s) to the clipboard." % len(urls))

    def export_csv(self):
        if not self.rows:
            messagebox.showinfo(APP_TITLE, "No results to export yet.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="results.csv",
            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        keys = list(self.rows[0])
        for r in self.rows:
            for k in r:
                if k not in keys:
                    keys.append(k)
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(self.rows)
        self.set_status("Saved %s" % path)


if __name__ == "__main__":
    try:
        Finder().mainloop()
    except tk.TclError as exc:
        sys.exit("Could not start the GUI: %s" % exc)
