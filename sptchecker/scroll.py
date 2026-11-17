"""Dark scrollable area: canvas + slim scrollbar that only shows on overflow."""
import tkinter as tk
import weakref

from .config import BG, BORDER
from .theme import lighten, pill

# One app-wide wheel handler finds the canvas under the pointer. Binding
# <Enter>/<Leave> on the canvas breaks once it holds embedded windows: Tk
# reports a Leave as soon as the pointer moves onto a child.
_scroll_canvases = weakref.WeakSet()
_wheel_bound = set()


def _on_global_wheel(e):
    widget = e.widget
    while widget is not None:
        if widget in _scroll_canvases:
            widget.yview_scroll(int(-e.delta / 40), "units")
            return "break"
        widget = getattr(widget, "master", None)
    return None


def _sync_scrollbar(canvas, scrollbar):
    """Coalesced via after_idle: N packed rows fire N <Configure> events."""
    if getattr(canvas, "_scroll_sync_pending", False):
        return
    canvas._scroll_sync_pending = True

    def sync():
        canvas._scroll_sync_pending = False
        if not canvas.winfo_exists():
            return
        canvas.update_idletasks()
        bbox = canvas.bbox("all")
        canvas.configure(scrollregion=bbox)
        content_h = (bbox[3] - bbox[1]) if bbox else 0
        if content_h > canvas.winfo_height():
            if not scrollbar.winfo_ismapped():
                # before=canvas, or the expanding canvas leaves it no width.
                scrollbar.pack(side="right", fill="y", before=canvas)
        elif scrollbar.winfo_ismapped():
            scrollbar.pack_forget()
            canvas.yview_moveto(0)

    canvas.after_idle(sync)


def build_scroll_area(parent, bg=BG):
    """Returns the inner frame to pack content into."""
    # width=1: a Canvas otherwise requests 378px and starves the scrollbar.
    canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, bd=0, width=1, height=1)
    scrollbar = MiniScrollbar(parent, bg=bg)
    canvas.configure(yscrollcommand=scrollbar.set)
    scrollbar.set_command(canvas.yview)
    canvas.pack(side="left", fill="both", expand=True)

    inner = tk.Frame(canvas, bg=bg)
    inner_id = canvas.create_window(0, 0, window=inner, anchor="nw")
    inner.bind("<Configure>", lambda _e: _sync_scrollbar(canvas, scrollbar))
    canvas.bind("<Configure>", lambda e: (
        canvas.itemconfigure(inner_id, width=e.width),
        _sync_scrollbar(canvas, scrollbar),
    ))

    _scroll_canvases.add(canvas)
    key = str(canvas.winfo_toplevel())
    if key not in _wheel_bound:
        _wheel_bound.add(key)
        canvas.bind_all("<MouseWheel>", _on_global_wheel, add="+")
    return inner


class MiniScrollbar(tk.Canvas):
    def __init__(self, parent, **kw):
        kw.setdefault("bg", BG)
        super().__init__(parent, highlightthickness=0, bd=0, width=10, **kw)
        self._first, self._last = 0.0, 1.0
        self._command = None
        self._drag_y = self._drag_first = None
        self._hover = False
        self._thumb_img = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag_y", None))

    def set_command(self, command):
        self._command = command

    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    def _set_hover(self, on):
        self._hover = on
        self._draw()

    def _thumb(self):
        h = self.winfo_height()
        if h < 2:
            return None
        y0, y1 = self._first * h, self._last * h
        if y1 - y0 < 24:
            mid = (y0 + y1) / 2
            y0 = max(0, mid - 12)
            y1 = min(h, y0 + 24)
        return y0, y1

    def _draw(self):
        self.delete("all")
        coords = self._thumb()
        if self._last - self._first >= 0.999 or not coords:
            return
        y0, y1 = coords
        self._thumb_img = pill(max(1, self.winfo_width() - 6), max(1, int(y1 - y0) - 2),
                               lighten(BORDER, 0.18) if self._hover else BORDER)
        self.create_image(3, int(y0) + 1, anchor="nw", image=self._thumb_img)

    def _on_press(self, e):
        coords = self._thumb()
        if not (coords and coords[0] <= e.y <= coords[1]) and self._command:
            self._command("moveto", max(0.0, min(1.0, e.y / max(1, self.winfo_height()))))
        self._drag_y, self._drag_first = e.y, self._first

    def _on_drag(self, e):
        h = self.winfo_height()
        if self._drag_y is None or not self._command or h < 2:
            return
        self._command("moveto", max(0.0, min(1.0, self._drag_first + (e.y - self._drag_y) / h)))
