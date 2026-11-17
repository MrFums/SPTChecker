"""Windows window chrome: DPI awareness, dark title bar, app icon."""
import ctypes

from PIL import Image, ImageDraw

from .config import ACCENT_NEW, ASSETS_DIR, BG, CARD_BG, TEXT_BRIGHT


def _rgb(hex_color, alpha=255):
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5)) + (alpha,)


def set_dpi_aware():
    """Per-monitor DPI aware, so Windows doesn't bitmap-stretch (and blur) the
    window on scaled displays. Must run before the Tk root is created."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_SWP_FLAGS = 0x2 | 0x1 | 0x4 | 0x20  # NOMOVE | NOSIZE | NOZORDER | FRAMECHANGED
_DWMWA_TRANSITIONS_FORCEDISABLED = 3


def _set_dwm_attribute(window, attr, value=1):
    hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
    c_value = ctypes.c_int(value)
    result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, attr, ctypes.byref(c_value), ctypes.sizeof(c_value))
    return hwnd, result


def set_dark_title_bar(window, show=True):
    try:
        window.withdraw()
        window.update_idletasks()
        # 20 is DWMWA_USE_IMMERSIVE_DARK_MODE; 19 is its pre-20H1 value.
        for attr in (20, 19):
            hwnd, result = _set_dwm_attribute(window, attr)
            if result == 0:
                break
        # The attribute alone doesn't always repaint the frame.
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, _SWP_FLAGS)
    except Exception:
        pass
    if show:
        window.deiconify()


def disable_show_animation(window):
    """Skip Windows' show animation, which flashes an unpainted white frame."""
    try:
        _set_dwm_attribute(window, _DWMWA_TRANSITIONS_FORCEDISABLED)
    except Exception:
        pass


def load_app_icon():
    icon_path = ASSETS_DIR / "icon.png"
    if icon_path.exists():
        return Image.open(icon_path)
    img = Image.new("RGBA", (64, 64), _rgb(BG))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([4, 4, 60, 60], radius=12, fill=_rgb(CARD_BG),
                           outline=_rgb(ACCENT_NEW), width=3)
    draw.text((14, 8), "SPT", fill=_rgb(TEXT_BRIGHT))
    return img
