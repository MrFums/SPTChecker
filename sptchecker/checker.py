"""Single-window update checker: pick the SPT folder, check, see what needs
updating. Replaces the old feed/tray app -- no tray icon, no toasts, no
registry entries, nothing runs in the background."""
import json
import os
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog

from PIL import Image, ImageTk

from .config import (
    ACCENT_DANGER, ACCENT_NEW, ACCENT_UPD, APP_VERSION, BG, BORDER, CARD_BG,
    CARD_HOVER, DATA_DIR, SEPARATOR, STATE_FILE, STATUS_BG, TEXT, TEXT_BRIGHT,
    TEXT_DIM, TEXT_FAINT,
)
from .feed import ForgeBlocked
from .localmods import detect_spt_version, scan_installed_mods, validate_spt_root
from .matcher import match_local_mods
from .platform import (
    disable_show_animation, load_app_icon, set_dark_title_bar, set_dpi_aware,
)
from .theme import RoundedPanel, chip, ellipsize, flat_button, font, pill
from .scroll import build_scroll_area

CHECKER_STATE_FILE = DATA_DIR / "update_checker.json"
DEFAULT_SIZE = (580, 680)
MIN_SIZE = (480, 420)


def _load_state():
    try:
        data = json.loads(CHECKER_STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    # First run of this build: carry the folder over from the old app, so an
    # existing user isn't asked to find their install again.
    try:
        old = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return {"spt_path": old.get("spt_install_path", "")}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_state(state):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CHECKER_STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, CHECKER_STATE_FILE)
    except OSError:
        pass


def _ago(ts):
    mins = int((time.time() - ts) // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    if mins < 60 * 24:
        return f"{mins // 60} h ago"
    return time.strftime("%d %b %Y", time.localtime(ts))


class UpdateCheckerApp:
    def __init__(self):
        self.state = _load_state()
        self._checking = False
        self._collapsed = {"Up to date": True, "Not on Forge": True}
        self._last_results = None

        set_dpi_aware()
        self.root = tk.Tk()
        self.root.title("SPT Mod Update Checker")
        self.root.configure(bg=BG)
        self.root.minsize(*MIN_SIZE)
        self.root.geometry(self._saved_geometry())
        set_dark_title_bar(self.root)
        disable_show_animation(self.root)
        self._icon = ImageTk.PhotoImage(load_app_icon().resize((32, 32), Image.LANCZOS))
        self.root.iconphoto(True, self._icon)

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self._refresh_folder()

        cached = self.state.get("results")
        if cached:
            self._show_results(cached)
        if validate_spt_root(self.state.get("spt_path", "")):
            # Opening the app is the request -- check straight away.
            self.root.after(300, self._check)
        elif not cached:
            self._message("Choose your SPT folder to check your mods for updates.")

    # ── Window ────────────────────────────────────────────────────────

    def _saved_geometry(self):
        m = re.fullmatch(r"(\d+)x(\d+)", self.state.get("geometry", ""))
        w, h = (int(m.group(1)), int(m.group(2))) if m else DEFAULT_SIZE
        return f"{max(w, MIN_SIZE[0])}x{max(h, MIN_SIZE[1])}"

    def _quit(self):
        w, h = self.root.winfo_width(), self.root.winfo_height()
        if w > 1 and h > 1:
            self.state["geometry"] = f"{w}x{h}"
        _save_state(self.state)
        self.root.destroy()

    def run(self):
        self.root.mainloop()

    # ── Layout ────────────────────────────────────────────────────────

    def _build(self):
        header = tk.Frame(self.root, bg=STATUS_BG)
        header.pack(fill="x")
        inner = tk.Frame(header, bg=STATUS_BG)
        inner.pack(fill="x", padx=18, pady=(14, 14))
        tk.Label(inner, text="Mod Updates", font=font(13, "bold"), fg=TEXT_BRIGHT,
                 bg=STATUS_BG).pack(side="left")
        self._spt_chip_holder = tk.Frame(inner, bg=STATUS_BG)
        self._spt_chip_holder.pack(side="left", padx=(10, 0))
        self._check_btn = flat_button(inner, "Check for Updates", self._check,
                                      accent=ACCENT_NEW, bg=STATUS_BG, padx=14, pady=6)
        self._check_btn.pack(side="right")

        folder = tk.Frame(self.root, bg=BG)
        folder.pack(fill="x", padx=18, pady=(14, 0))
        flat_button(folder, "Change…", self._browse, bg=BG, padx=10,
                    pady=4).pack(side="right", padx=(8, 0))
        field = RoundedPanel(folder, fill=CARD_BG, outline=BORDER, bg=BG,
                             padx=10, pady=5, radius=6)
        field.pack(side="left", fill="x", expand=True)
        self._path_lbl = tk.Label(field.body, text="", font=font(8), fg=TEXT_DIM,
                                  bg=CARD_BG, anchor="w")
        self._path_lbl.pack(fill="x")
        self._path_lbl.bind("<Configure>", lambda _e: self._fit_path())

        # Summary chips, or the progress bar while a check runs.
        self._status = tk.Frame(self.root, bg=BG, height=1)
        self._status.pack(fill="x", padx=18, pady=(12, 4))
        self._progress_lbl = tk.Label(self._status, text="", font=font(8), fg=TEXT_DIM,
                                      bg=BG, anchor="w")
        self._progress_canvas = tk.Canvas(self._status, height=5, bg=BG,
                                          highlightthickness=0, bd=0)
        self._progress_canvas.bind("<Configure>", lambda _e: self._draw_progress())
        self._progress_frac = 0.0
        self._chips = tk.Frame(self._status, bg=BG)

        footer = tk.Frame(self.root, bg=STATUS_BG)
        footer.pack(side="bottom", fill="x")
        self._footer_lbl = tk.Label(footer, text="", font=font(8), fg=TEXT_FAINT,
                                    bg=STATUS_BG, anchor="w")
        self._footer_lbl.pack(side="left", padx=18, pady=6)
        tk.Label(footer, text=f"v{APP_VERSION}", font=font(8), fg=TEXT_FAINT,
                 bg=STATUS_BG).pack(side="right", padx=18)

        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, padx=(18, 6), pady=(4, 12))
        self._list = build_scroll_area(container)

    def _fit_path(self):
        path = self.state.get("spt_path") or "No SPT folder selected"
        width = self._path_lbl.winfo_width()
        # Trim from the front: the install's own folder name is the tail.
        if width > 20 and font(8).measure(path) > width:
            while len(path) > 4 and font(8).measure("…" + path) > width:
                path = path[1:]
            path = "…" + path
        self._path_lbl.configure(text=path)

    def _refresh_folder(self):
        path = self.state.get("spt_path", "")
        valid = bool(path) and validate_spt_root(path)
        self._fit_path()
        for w in self._spt_chip_holder.winfo_children():
            w.destroy()
        version = detect_spt_version(path) if valid else None
        if version:
            chip(self._spt_chip_holder, f"SPT {version}", TEXT_DIM, surface=STATUS_BG,
                 font_size=8, weight="normal").pack()
        elif path and not valid:
            chip(self._spt_chip_holder, "Not an SPT folder", ACCENT_DANGER,
                 surface=STATUS_BG, font_size=8, weight="normal").pack()
        self._check_btn.configure(state="normal" if valid and not self._checking
                                  else "disabled")

    def _browse(self):
        chosen = filedialog.askdirectory(parent=self.root,
                                         initialdir=self.state.get("spt_path") or None,
                                         title="Select your SPT install folder")
        if not chosen:
            return
        self.state["spt_path"] = os.path.normpath(chosen)
        self.state.pop("results", None)
        self.state.pop("checked_at", None)
        _save_state(self.state)
        self._refresh_folder()
        if validate_spt_root(chosen):
            self._check()
        else:
            self._message("That folder doesn't look like an SPT install -- pick the "
                          "folder that holds BepInEx and SPT_Runtime (or SPT).")

    # ── Checking ──────────────────────────────────────────────────────

    def _check(self):
        path = self.state.get("spt_path", "")
        if self._checking or not validate_spt_root(path):
            return
        self._checking = True
        self._check_btn.configure(state="disabled", text="Checking…")
        self._show_progress("Reading installed mods…", 0.0)
        threading.Thread(target=self._bg_check, args=(path,), daemon=True).start()

    def _bg_check(self, path):
        try:
            mods = scan_installed_mods(path)
            results = match_local_mods(
                mods, spt_version=detect_spt_version(path),
                on_progress=lambda d, t: self.root.after(0, self._on_progress, d, t))
            self.root.after(0, self._on_done, results)
        except ForgeBlocked:
            self.root.after(0, self._on_error,
                            "sp-mod.com is blocking automated requests right now. Try again later.")
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc) or type(exc).__name__)

    def _on_progress(self, done, total):
        self._show_progress(f"Checking {done} of {total} against the Forge…",
                            done / total if total else 0)

    def _on_done(self, results):
        self._checking = False
        self._check_btn.configure(text="Check for Updates")
        self.state["results"] = results
        self.state["checked_at"] = time.time()
        _save_state(self.state)
        self._refresh_folder()
        self._show_results(results)

    def _on_error(self, msg):
        self._checking = False
        self._check_btn.configure(text="Check for Updates")
        self._refresh_folder()
        self._hide_progress()
        self._message(f"Check failed: {msg}", color=ACCENT_DANGER)

    # ── Progress ──────────────────────────────────────────────────────

    def _show_progress(self, text, frac):
        self._chips.pack_forget()
        self._progress_lbl.configure(text=text)
        if not self._progress_lbl.winfo_ismapped():
            self._progress_lbl.pack(fill="x", pady=(0, 5))
            self._progress_canvas.pack(fill="x", pady=(0, 6))
        self._progress_frac = max(0.0, min(1.0, frac))
        self._draw_progress()

    def _hide_progress(self):
        self._progress_lbl.pack_forget()
        self._progress_canvas.pack_forget()

    def _draw_progress(self):
        c = self._progress_canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 2 or h < 2:
            return
        self._track_img = pill(w, h, SEPARATOR)
        c.create_image(0, 0, anchor="nw", image=self._track_img)
        filled = int(w * self._progress_frac)
        if filled >= h:
            self._fill_img = pill(filled, h, ACCENT_UPD)
            c.create_image(0, 0, anchor="nw", image=self._fill_img)

    # ── Results ───────────────────────────────────────────────────────

    def _clear(self):
        for w in self._list.winfo_children():
            w.destroy()

    def _message(self, text, color=TEXT_FAINT):
        self._clear()
        tk.Label(self._list, text=text, font=font(9), fg=color, bg=BG,
                 wraplength=420, justify="center").pack(pady=(60, 0))

    def _show_results(self, results):
        self._last_results = results
        self._hide_progress()
        self._clear()
        updates = [r for r in results if r["update_available"]]
        current = [r for r in results if r["forge"] and not r["update_available"]]
        unchecked = [r for r in results if not r["forge"] and r.get("lookup_failed")]
        missing = [r for r in results if not r["forge"] and not r.get("lookup_failed")]

        for w in self._chips.winfo_children():
            w.destroy()
        parts = [(len(updates), "to update", ACCENT_UPD),
                 (len(current), "up to date", ACCENT_NEW),
                 (len(missing), "not on Forge", TEXT_DIM)]
        if unchecked:
            parts.append((len(unchecked), "couldn't check", ACCENT_DANGER))
        for n, label, color in parts:
            chip(self._chips, f"{n} {label}", color, surface=BG, font_size=8,
                 weight="normal").pack(side="left", padx=(0, 6))
        self._chips.pack(fill="x", pady=(0, 6))

        checked_at = self.state.get("checked_at")
        self._footer_lbl.configure(
            text=f"{len(results)} mods  ·  checked {_ago(checked_at)}" if checked_at else "")

        if updates:
            links = [r["forge"]["link"] for r in updates]
            head = self._section("Updates available", ACCENT_UPD, len(updates))
            if len(links) > 1:
                flat_button(head, "Open all", lambda: self._open_all(links), font_size=8,
                            padx=8, pady=2, bg=BG).pack(side="right", padx=(0, 8))
            for r in sorted(updates, key=self._name_key):
                self._update_row(r)
        else:
            tk.Label(self._list, text="✓  Everything is up to date", font=font(11, "bold"),
                     fg=ACCENT_NEW, bg=BG).pack(anchor="w", pady=(12, 4))

        if unchecked:
            self._section("Couldn't check", ACCENT_DANGER, len(unchecked))
            tk.Label(self._list, text="The Forge rate-limited these. Check again in a minute.",
                     font=font(8), fg=TEXT_DIM, bg=BG, anchor="w").pack(fill="x", pady=(0, 4))
            for r in sorted(unchecked, key=self._name_key):
                self._plain_row(self._local_name(r), r["current_version"])

        for title, rows, color in (("Up to date", current, ACCENT_NEW),
                                   ("Not on Forge", missing, TEXT_DIM)):
            if not rows:
                continue
            self._section(title, color, len(rows), collapsible=True)
            if not self._collapsed[title]:
                for r in sorted(rows, key=self._name_key):
                    self._plain_row(self._local_name(r) if not r["forge"] else
                                    r["forge"]["title"], r["current_version"],
                                    link=r["forge"]["link"] if r["forge"] else None)

    @staticmethod
    def _local_name(r):
        return r["local"].get("name") or "(unknown)"

    @staticmethod
    def _name_key(r):
        return ((r["forge"] or {}).get("title") or r["local"].get("name") or "").casefold()

    def _section(self, title, color, count, collapsible=False):
        row = tk.Frame(self._list, bg=BG, cursor="hand2" if collapsible else "arrow")
        row.pack(fill="x", pady=(16, 6))
        labels = []
        if collapsible:
            labels.append(tk.Label(row, text="▸" if self._collapsed[title] else "▾",
                                   font=font(9), fg=TEXT_DIM, bg=BG))
        labels.append(tk.Label(row, text=title.upper(), font=font(8, "bold"), fg=color, bg=BG))
        labels.append(tk.Label(row, text=str(count), font=font(8, "bold"), fg=TEXT_FAINT, bg=BG))
        for i, lbl in enumerate(labels):
            lbl.pack(side="left", padx=(0, 6))
        if collapsible:
            def toggle(_e=None):
                self._collapsed[title] = not self._collapsed[title]
                self._show_results(self._last_results)
            for w in (row, *labels):
                w.bind("<Button-1>", toggle)
        return row

    def _update_row(self, r):
        forge = r["forge"]
        panel = RoundedPanel(self._list, fill=CARD_BG, bg=BG, padx=14, pady=9)
        panel.pack(fill="x", pady=3, padx=(0, 8))
        body = panel.body
        body.columnconfigure(0, weight=1)
        name = tk.Label(body, text=forge["title"], font=font(10, "bold"), fg=TEXT_BRIGHT,
                        bg=CARD_BG, anchor="w")
        name.grid(row=0, column=0, sticky="ew")
        meta = tk.Label(body, text=f"by {forge.get('author') or 'Unknown'}", font=font(8),
                        fg=TEXT_DIM, bg=CARD_BG, anchor="w")
        meta.grid(row=1, column=0, sticky="ew")
        version = tk.Label(body, text=f"{r['current_version']}  →  {r['available_version']}",
                           font=font(9), fg=ACCENT_UPD, bg=CARD_BG)
        version.grid(row=0, column=1, rowspan=2, padx=(12, 12))
        open_btn = flat_button(body, "Open", lambda: webbrowser.open(forge["link"]),
                               font_size=8, padx=10, pady=3, bg=CARD_BG)
        open_btn.grid(row=0, column=2, rowspan=2)

        def hover(on):
            fill = CARD_HOVER if on else CARD_BG
            panel.set_fill(fill)
            for w in (name, meta, version):
                w.configure(bg=fill)
            # PillButton.configure ignores bg (it paints its own), so the
            # canvas behind its rounded corners is recoloured directly.
            tk.Canvas.configure(open_btn, bg=fill)
            open_btn._bg = fill
            open_btn._redraw()
        for w in (panel, body, name, meta, version):
            w.bind("<Enter>", lambda _e: hover(True))
            w.bind("<Leave>", lambda _e: hover(False))
            if w is not panel:
                w.configure(cursor="hand2")
                w.bind("<Button-1>", lambda _e: webbrowser.open(forge["link"]))
        name.bind("<Configure>", lambda e: name.configure(
            text=ellipsize(font(10, "bold"), forge["title"], max(e.width, 40))))

    def _plain_row(self, text, version, link=None):
        row = tk.Frame(self._list, bg=BG, cursor="hand2" if link else "arrow")
        row.pack(fill="x", padx=(2, 8), pady=1)
        name = tk.Label(row, text=text, font=font(9), fg=TEXT, bg=BG, anchor="w")
        name.pack(side="left", fill="x", expand=True)
        ver = tk.Label(row, text=version or "?", font=font(8), fg=TEXT_FAINT, bg=BG)
        ver.pack(side="right")
        if link:
            for w in (row, name, ver):
                w.bind("<Button-1>", lambda _e: webbrowser.open(link))
                w.bind("<Enter>", lambda _e: name.configure(fg=TEXT_BRIGHT))
                w.bind("<Leave>", lambda _e: name.configure(fg=TEXT))

    def _open_all(self, links):
        # Staggered: a burst of tabs gets some silently dropped by browsers.
        for i, link in enumerate(links):
            self.root.after(i * 200, webbrowser.open, link)
