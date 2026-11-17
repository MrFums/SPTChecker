"""The app window: SPT folder, one Check button, results in three tabs.
Nothing runs in the background and nothing is written outside DATA_DIR."""
import json
import os
import re
import shutil
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageTk

from .config import (
    ACCENT_DANGER, ACCENT_NEW, ACCENT_UPD, APP_NAME, BEPINEX_PLUGINS_SUBPATH, BG, CARD_BG,
    DATA_DIR,
    LEGACY_DATA_DIR, MATCH_CACHE_FILE, SEPARATOR, STATUS_BG, TEXT, TEXT_BRIGHT,
    TEXT_DIM, TEXT_FAINT,
)
from .feed import ForgeBlocked, set_wait_listener
from .localmods import (
    _same_folder, detect_spt_version, resolve_headless_root, scan_installed_mods,
    validate_spt_root,
)
from .matcher import match_local_mods
from .platform import (
    disable_show_animation, load_app_icon, set_dark_title_bar, set_dpi_aware,
)
from .scroll import build_scroll_area
from .theme import chip, ellipsize, flat_button, font

SETTINGS_FILE = DATA_DIR / "settings.json"
DEFAULT_SIZE = (600, 700)
MIN_SIZE = (500, 440)
PAD_X = 22

TAB_UPDATES, TAB_CURRENT, TAB_MISSING = "Updates", "Up to date", "Not on Forge"


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _load_state():
    state = _read_json(SETTINGS_FILE)
    if state is not None:
        return state
    # First run: take the SPT folder (and the warm match cache) from the
    # original SPTChecker, so switching over doesn't start from scratch.
    old = (_read_json(LEGACY_DATA_DIR / "update_checker.json") or {}).get("spt_path") \
        or (_read_json(LEGACY_DATA_DIR / "spt_mods_state.json") or {}).get("spt_install_path")
    legacy_cache = LEGACY_DATA_DIR / "match_cache.json"
    if legacy_cache.is_file() and not MATCH_CACHE_FILE.exists():
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(legacy_cache, MATCH_CACHE_FILE)
        except OSError:
            pass
    return {"spt_path": os.path.normpath(old)} if old else {}


def _save_state(state):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, SETTINGS_FILE)
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


def _hover_group(widgets, on_enter, on_leave):
    for w in widgets:
        w.bind("<Enter>", lambda _e: on_enter())
        w.bind("<Leave>", lambda _e: on_leave())


class UpdateCheckerApp:
    def __init__(self):
        self.state = _load_state()
        self._checking = False
        self._stage_text = ""
        self._wait_after = None
        self._results = None
        self._tab = TAB_UPDATES
        self._error = None
        self._headless = False

        set_dpi_aware()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.minsize(*MIN_SIZE)
        self.root.geometry(self._saved_geometry())
        set_dark_title_bar(self.root)
        disable_show_animation(self.root)
        icon = load_app_icon()
        self._icon = ImageTk.PhotoImage(icon.resize((32, 32), Image.LANCZOS))
        self._header_icon = ImageTk.PhotoImage(icon.resize((22, 22), Image.LANCZOS))
        self.root.iconphoto(True, self._icon)

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self._quit)
        self._refresh_folder()

        if self.state.get("results"):
            self._results = self.state["results"]
        self._render()
        if self._folder_valid():
            # Opening the app is the request -- check straight away.
            self.root.after(300, self._check)

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

    def _server_path(self):
        """The separate server folder, or None when the game folder is it."""
        return self.state.get("server_path") or None

    def _headless_root(self):
        """The headless folder in use: the one set, or one auto-detected in
        a separate server folder, or None."""
        game = self.state.get("spt_path", "")
        return resolve_headless_root(game, self._server_path(),
                                     self.state.get("headless_path")) if game else None

    def _bad_folders(self):
        """Names of folders that are set but don't look right."""
        bad = []
        game, server = self.state.get("spt_path", ""), self._server_path()
        headless = self.state.get("headless_path")
        if game and not validate_spt_root(game):
            bad.append("game")
        if server and not validate_spt_root(server):
            bad.append("server")
        if headless and not (Path(headless) / BEPINEX_PLUGINS_SUBPATH).is_dir():
            bad.append("headless")
        return bad

    def _folder_valid(self):
        return bool(self.state.get("spt_path")) and not self._bad_folders()

    # ── Layout ────────────────────────────────────────────────────────

    def _build(self):
        # Header bar: icon, name, installed SPT version.
        header = tk.Frame(self.root, bg=STATUS_BG)
        header.pack(fill="x")
        tk.Label(header, image=self._header_icon, bg=STATUS_BG).pack(
            side="left", padx=(PAD_X - 4, 8), pady=10)
        tk.Label(header, text=APP_NAME, font=font(10, "bold"), fg=TEXT_BRIGHT,
                 bg=STATUS_BG).pack(side="left")
        self._spt_chip_holder = tk.Frame(header, bg=STATUS_BG)
        self._spt_chip_holder.pack(side="right", padx=PAD_X)

        # Footer: which installs are being checked -- the game (client mods),
        # optionally a separate server, and optionally a headless client,
        # which may sit in the server folder or in a folder of its own.
        footer = tk.Frame(self.root, bg=STATUS_BG)
        footer.pack(side="bottom", fill="x")
        footer.columnconfigure(1, weight=1)
        self._path_lbls = {}
        self._reset_lbls = {}
        rows = (("spt_path", "GAME", None),
                ("server_path", "SERVER", "Use game folder"),
                ("headless_path", "HEADLESS", "Auto-detect"))
        for row, (key, title, reset) in enumerate(rows):
            pad = (9 if row == 0 else 2, 9 if row == len(rows) - 1 else 2)
            tk.Label(footer, text=title, font=font(7, "bold"), fg=TEXT_FAINT, bg=STATUS_BG,
                     anchor="w").grid(row=row, column=0, padx=(PAD_X, 12), pady=pad,
                                                sticky="w")
            lbl = tk.Label(footer, text="", font=font(8), fg=TEXT_DIM, bg=STATUS_BG, anchor="w")
            lbl.grid(row=row, column=1, sticky="ew", pady=pad)
            lbl.bind("<Configure>", lambda _e: self._fit_paths())
            self._path_lbls[key] = lbl
            links = tk.Frame(footer, bg=STATUS_BG)
            links.grid(row=row, column=2, padx=(8, PAD_X), pady=pad, sticky="e")
            if reset:
                self._reset_lbls[key] = self._link(
                    links, reset, lambda k=key: self._set_folder(k, None), color=TEXT_DIM)
            self._link(links, "Change", lambda k=key: self._browse(k)).pack(side="right")

        # Headline: the one number that matters, plus the Check button.
        hero = tk.Frame(self.root, bg=BG)
        hero.pack(fill="x", padx=PAD_X, pady=(20, 14))
        self._check_btn = flat_button(hero, "Check now", self._check, accent=ACCENT_NEW,
                                      bg=BG, font_size=10, padx=18, pady=8)
        self._check_btn.pack(side="right", anchor="center")
        text = tk.Frame(hero, bg=BG)
        text.pack(side="left", fill="x", expand=True)
        line = tk.Frame(text, bg=BG)
        line.pack(anchor="w")
        self._count_lbl = tk.Label(line, text="", font=font(26, "bold"), fg=TEXT_BRIGHT, bg=BG)
        self._count_lbl.pack(side="left")
        self._headline_lbl = tk.Label(line, text="", font=font(12), fg=TEXT, bg=BG)
        self._headline_lbl.pack(side="left", padx=(10, 0), pady=(10, 0))
        self._sub_lbl = tk.Label(text, text="", font=font(9), fg=TEXT_DIM, bg=BG, anchor="w",
                                 justify="left")
        self._sub_lbl.pack(anchor="w", fill="x")
        # Wrap rather than clip: error and rate-limit messages run long.
        text.bind("<Configure>", lambda e: self._sub_lbl.configure(
            wraplength=max(e.width - 4, 100)))

        # Thin progress line between the headline and the tabs.
        self._progress = tk.Canvas(self.root, height=2, bg=SEPARATOR,
                                   highlightthickness=0, bd=0)
        self._progress.pack(fill="x")
        self._progress.bind("<Configure>", lambda _e: self._draw_progress())
        self._progress_frac = None

        self._tabs = tk.Frame(self.root, bg=BG)
        self._tabs.pack(fill="x", padx=PAD_X - 10, pady=(8, 0))
        tk.Frame(self.root, bg=SEPARATOR, height=1).pack(fill="x")

        container = tk.Frame(self.root, bg=BG)
        container.pack(fill="both", expand=True, pady=(0, 2))
        self._list = build_scroll_area(container)

    @staticmethod
    def _link(parent, text, command, color=ACCENT_NEW):
        lbl = tk.Label(parent, text=text, font=font(8, "bold"), fg=color, bg=STATUS_BG,
                       cursor="hand2")
        lbl.bind("<Button-1>", lambda _e: command())
        _hover_group([lbl], lambda: lbl.configure(fg=TEXT_BRIGHT),
                     lambda: lbl.configure(fg=color))
        return lbl

    def _fit_paths(self):
        f = font(8)
        game = self.state.get("spt_path") or "None selected"
        server = self._server_path()
        headless_set = self.state.get("headless_path")
        headless = self._headless_root()
        if headless_set:
            headless_text = headless_set
        elif headless:
            headless_text = "Auto: found in the server folder"
        else:
            headless_text = "None found -- set it if your headless has its own folder"
        texts = {"spt_path": game,
                 "server_path": server or "Same as game folder",
                 "headless_path": headless_text}
        dim = {"spt_path": True, "server_path": bool(server), "headless_path": bool(headless)}
        for key, lbl in self._path_lbls.items():
            text, width = texts[key], lbl.winfo_width()
            # Trim from the front: the install's own folder name is the tail.
            if width > 20 and f.measure(text) > width:
                while len(text) > 4 and f.measure("…" + text) > width:
                    text = text[1:]
                text = "…" + text
            lbl.configure(text=text, fg=TEXT_DIM if dim[key] else TEXT_FAINT)

    def _refresh_folder(self):
        game = self.state.get("spt_path", "")
        server = self._server_path()
        bad = self._bad_folders()
        self._headless = "headless" not in bad and bool(self._headless_root())
        valid = self._folder_valid()
        self._fit_paths()
        for key, lbl in self._reset_lbls.items():
            if self.state.get(key):
                lbl.pack(side="right", padx=(0, 12))
            else:
                lbl.pack_forget()
        for w in self._spt_chip_holder.winfo_children():
            w.destroy()
        version = detect_spt_version(server or game) if valid else None
        chips = []
        if version:
            chips.append((f"SPT {version}", ACCENT_NEW))
        if self._headless:
            chips.append(("Headless", TEXT_DIM))
        if bad:
            chips = [(f"Not an SPT {bad[0]} folder", ACCENT_DANGER)]
        for text, color in chips:
            chip(self._spt_chip_holder, text, color, surface=STATUS_BG,
                 font_size=8).pack(side="left", padx=(6, 0))
        self._check_btn.configure(state="normal" if valid and not self._checking
                                  else "disabled")

    def _browse(self, key):
        if self._checking:
            return
        title = {"spt_path": "Select your SPT game folder",
                 "server_path": "Select your SPT server folder",
                 "headless_path": "Select your Fika headless client folder"}[key]
        chosen = filedialog.askdirectory(
            parent=self.root, title=title,
            initialdir=self.state.get(key) or self.state.get("spt_path") or None)
        if chosen:
            self._set_folder(key, os.path.normpath(chosen))

    def _set_folder(self, key, path):
        if self._checking:
            return
        if key != "spt_path" and path and _same_folder(path, self.state.get("spt_path", "")):
            path = None  # the game folder is the default for the server already
        if path:
            self.state[key] = path
        else:
            self.state.pop(key, None)
        self.state.pop("results", None)
        self.state.pop("checked_at", None)
        self._results = None
        self._error = None
        _save_state(self.state)
        self._refresh_folder()
        self._render()
        if self._folder_valid():
            self._check()

    # ── Checking ──────────────────────────────────────────────────────

    def _check(self):
        path = self.state.get("spt_path", "")
        if self._checking or not self._folder_valid():
            return
        self._checking = True
        self._error = None
        self._check_btn.configure(state="disabled", text="Checking…")
        self._set_stage("Reading installed mods…", 0.0)
        threading.Thread(target=self._bg_check,
                         args=(path, self._server_path(), self.state.get("headless_path")),
                         daemon=True).start()

    def _bg_check(self, path, server, headless):
        set_wait_listener(lambda s: self.root.after(0, self._on_wait, s))
        try:
            mods = scan_installed_mods(path, server, headless)
            results = match_local_mods(
                mods, spt_version=detect_spt_version(server or path),
                on_progress=lambda d, t: self.root.after(
                    0, self._set_stage, f"Checking mod {d} of {t} on the Forge…",
                    d / t if t else 0),
                on_stage=lambda text: self.root.after(0, self._set_stage, text, 1.0))
            self.root.after(0, self._on_done, results)
        except ForgeBlocked:
            self.root.after(0, self._on_error,
                            "sp-mod.com is blocking automated requests right now. Try later.")
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc) or type(exc).__name__)
        finally:
            set_wait_listener(None)

    def _set_stage(self, text, frac):
        self._stage_text = text
        self._progress_frac = frac
        self._draw_progress()
        if not self._wait_after:
            self._sub_lbl.configure(text=text, fg=TEXT_DIM)
        if self._results is None:
            self._count_lbl.configure(text="…", fg=TEXT_FAINT)
            self._headline_lbl.configure(text="Checking your mods")

    def _on_wait(self, seconds):
        """The Forge allows ~50 requests a minute; past that we wait. Count
        it down so a stalled progress line doesn't look like a hang."""
        if self._wait_after:
            self.root.after_cancel(self._wait_after)
        end = time.monotonic() + seconds

        def tick():
            left = int(end - time.monotonic() + 0.99)
            if not self._checking or left <= 0:
                self._wait_after = None
                if self._checking:
                    self._sub_lbl.configure(text=self._stage_text, fg=TEXT_DIM)
                return
            self._sub_lbl.configure(
                text=f"Forge rate limit reached, resuming in {left}s…", fg=ACCENT_UPD)
            self._wait_after = self.root.after(250, tick)
        tick()

    def _on_done(self, results):
        self._finish()
        self._results = results
        self.state["results"] = results
        self.state["checked_at"] = time.time()
        _save_state(self.state)
        self._render()

    def _on_error(self, msg):
        self._finish()
        self._error = msg
        self._render()

    def _finish(self):
        self._checking = False
        self._progress_frac = None
        self._draw_progress()
        self._check_btn.configure(text="Check now")
        self._refresh_folder()

    def _draw_progress(self):
        c = self._progress
        c.delete("all")
        w = c.winfo_width()
        if self._progress_frac is not None and w > 1:
            c.create_rectangle(0, 0, int(w * self._progress_frac), 3,
                               fill=ACCENT_NEW, width=0)

    # ── Rendering ─────────────────────────────────────────────────────

    def _split(self):
        r = self._results or []
        return {
            TAB_UPDATES: [x for x in r if x["update_available"]],
            TAB_CURRENT: [x for x in r if x["forge"] and not x["update_available"]],
            TAB_MISSING: [x for x in r if not x["forge"] and not x.get("lookup_failed")],
            "unchecked": [x for x in r if not x["forge"] and x.get("lookup_failed")],
        }

    def _render(self):
        groups = self._split()
        self._render_headline(groups)
        self._render_tabs(groups)
        self._render_list(groups)

    def _render_headline(self, groups):
        if self._checking:
            return
        if self._error:
            self._count_lbl.configure(text="!", fg=ACCENT_DANGER)
            self._headline_lbl.configure(text="Check failed")
            self._sub_lbl.configure(text=self._error, fg=ACCENT_DANGER)
            return
        if not self._folder_valid():
            self._count_lbl.configure(text="—", fg=TEXT_FAINT)
            self._headline_lbl.configure(text="Choose your SPT folder")
            self._sub_lbl.configure(
                text="Click Change next to GAME at the bottom. If your server or "
                     "headless live elsewhere, set those too.", fg=TEXT_DIM)
            return
        if self._results is None:
            self._count_lbl.configure(text="…", fg=TEXT_FAINT)
            self._headline_lbl.configure(text="Not checked yet")
            self._sub_lbl.configure(text="", fg=TEXT_DIM)
            return
        n = len(groups[TAB_UPDATES])
        if n:
            self._count_lbl.configure(text=str(n), fg=ACCENT_UPD)
            self._headline_lbl.configure(text="update available" if n == 1 else "updates available")
        else:
            self._count_lbl.configure(text="✓", fg=ACCENT_NEW)
            self._headline_lbl.configure(text="All mods up to date")
        sub = f"{len(self._results)} mods"
        if self.state.get("checked_at"):
            sub += f"  ·  checked {_ago(self.state['checked_at'])}"
        if groups["unchecked"]:
            sub += f"  ·  {len(groups['unchecked'])} couldn't be checked"
        self._sub_lbl.configure(text=sub, fg=TEXT_DIM)

    def _render_tabs(self, groups):
        for w in self._tabs.winfo_children():
            w.destroy()
        for name, color in ((TAB_UPDATES, ACCENT_UPD), (TAB_CURRENT, ACCENT_NEW),
                            (TAB_MISSING, TEXT_DIM)):
            selected = name == self._tab
            tab = tk.Frame(self._tabs, bg=BG, cursor="hand2")
            tab.pack(side="left", padx=(0, 4))
            row = tk.Frame(tab, bg=BG)
            row.pack(padx=10, pady=(4, 8))
            label = tk.Label(row, text=name, font=font(9, "bold" if selected else "normal"),
                             fg=TEXT_BRIGHT if selected else TEXT_DIM, bg=BG)
            label.pack(side="left")
            count = tk.Label(row, text=str(len(groups[name])) if self._results else "",
                             font=font(8, "bold"), fg=color if selected else TEXT_FAINT, bg=BG)
            count.pack(side="left", padx=(6, 0))
            tk.Frame(tab, bg=color if selected else BG, height=2).pack(fill="x", padx=6)
            for w in (tab, row, label, count):
                w.bind("<Button-1>", lambda _e, n=name: self._select_tab(n))
            if not selected:
                _hover_group((tab, row, label, count),
                             lambda l=label: l.configure(fg=TEXT),
                             lambda l=label: l.configure(fg=TEXT_DIM))

    def _select_tab(self, name):
        if name != self._tab:
            self._tab = name
            self._render()

    def _render_list(self, groups):
        for w in self._list.winfo_children():
            w.destroy()
        if self._results is None:
            return
        rows = sorted(groups[self._tab], key=self._name_key)
        if self._tab == TAB_UPDATES:
            if groups["unchecked"]:
                self._notice(f"{len(groups['unchecked'])} mods couldn't be checked: the Forge "
                             "rate-limited the lookups. Check again in a minute.")
            if len(rows) > 1:
                bar = tk.Frame(self._list, bg=BG)
                bar.pack(fill="x", padx=PAD_X, pady=(10, 2))
                flat_button(bar, f"Open all {len(rows)} on the Forge",
                            lambda links=[r["forge"]["link"] for r in rows]: self._open_all(links),
                            font_size=8, padx=10, pady=3, bg=BG).pack(side="right")
        if not rows:
            text = {TAB_UPDATES: "Nothing to update.",
                    TAB_CURRENT: "No mods are confirmed up to date.",
                    TAB_MISSING: "Every mod was found on the Forge."}[self._tab]
            tk.Label(self._list, text=text, font=font(10), fg=TEXT_FAINT, bg=BG).pack(pady=50)
            return
        for i, r in enumerate(rows):
            if i:
                tk.Frame(self._list, bg=SEPARATOR, height=1).pack(fill="x", padx=PAD_X)
            self._row(r)

    def _notice(self, text):
        box = tk.Frame(self._list, bg=BG)
        box.pack(fill="x", padx=PAD_X, pady=(12, 0))
        tk.Frame(box, bg=ACCENT_DANGER, width=3).pack(side="left", fill="y")
        tk.Label(box, text=text, font=font(8), fg=TEXT, bg=BG, anchor="w", justify="left",
                 wraplength=440).pack(side="left", padx=(10, 0))

    @staticmethod
    def _name_key(r):
        return ((r["forge"] or {}).get("title") or r["local"].get("name") or "").casefold()

    def _row(self, r):
        forge = r["forge"]
        is_update = self._tab == TAB_UPDATES
        link = forge["link"] if forge else None
        title = forge["title"] if forge else (r["local"].get("name") or "(unknown)")

        row = tk.Frame(self._list, bg=BG, cursor="hand2" if link else "arrow")
        row.pack(fill="x")
        inner = tk.Frame(row, bg=BG)
        inner.pack(fill="x", padx=PAD_X, pady=9 if is_update else 6)
        inner.columnconfigure(0, weight=1)
        name_font = font(10, "bold") if is_update else font(9)
        name = tk.Label(inner, text=title, font=name_font,
                        fg=TEXT_BRIGHT if is_update else TEXT, bg=BG, anchor="w")
        name.grid(row=0, column=0, sticky="ew")
        name.bind("<Configure>", lambda e: name.configure(
            text=ellipsize(name_font, title, max(e.width, 40))))
        parts = [row, inner, name]

        if is_update:
            meta = tk.Frame(inner, bg=BG)
            meta.grid(row=1, column=0, sticky="ew")
            meta_parts = [tk.Label(meta, text=f"by {forge.get('author') or 'Unknown'}",
                                   font=font(8), fg=TEXT_DIM, bg=BG)]
            # Where it's installed; the copies that are behind in coral, so
            # a stale headless or server copy is obvious at a glance.
            outdated = set(r.get("outdated_sources") or [])
            for src in r.get("sources") or []:
                meta_parts.append(tk.Label(meta, text="·", font=font(8), fg=TEXT_FAINT, bg=BG))
                meta_parts.append(tk.Label(
                    meta, text=src, font=font(8, "bold" if src in outdated else "normal"),
                    fg=ACCENT_UPD if src in outdated else TEXT_FAINT, bg=BG))
            for w in meta_parts:
                w.pack(side="left", padx=(0, 5))
            parts += meta_parts
            ver = tk.Frame(inner, bg=BG)
            ver.grid(row=0, column=1, rowspan=2, padx=(14, 0))
            old = tk.Label(ver, text=r["current_version"] or "?", font=font(9),
                           fg=TEXT_DIM, bg=BG)
            arrow = tk.Label(ver, text="→", font=font(9), fg=TEXT_FAINT, bg=BG)
            new = tk.Label(ver, text=r["available_version"] or "?", font=font(9, "bold"),
                           fg=ACCENT_UPD, bg=BG)
            for w in (old, arrow, new):
                w.pack(side="left", padx=(0, 6))
            parts += [meta, ver, old, arrow, new]
        else:
            ver = tk.Label(inner, text=r["current_version"] or "?", font=font(8),
                           fg=TEXT_FAINT, bg=BG)
            ver.grid(row=0, column=1, padx=(14, 0))
            parts.append(ver)

        if link:
            go = tk.Label(inner, text="↗", font=font(11), fg=TEXT_FAINT, bg=BG)
            go.grid(row=0, column=2, rowspan=2, padx=(10, 0))
            parts.append(go)

            def enter():
                for w in parts:
                    w.configure(bg=CARD_BG)
                go.configure(fg=ACCENT_NEW)

            def leave():
                for w in parts:
                    w.configure(bg=BG)
                go.configure(fg=TEXT_FAINT)
            _hover_group(parts, enter, leave)
            for w in parts:
                w.bind("<Button-1>", lambda _e: webbrowser.open(link))

    def _open_all(self, links):
        # Staggered: a burst of tabs gets some silently dropped by browsers.
        for i, link in enumerate(links):
            self.root.after(i * 200, webbrowser.open, link)
