from __future__ import annotations

import argparse
import ctypes
import threading
import time
import webbrowser
from ctypes import wintypes

import webview

try:
    import pystray
except ImportError:
    pystray = None

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None

try:
    from windows_widget.settings import (
        APP_NAME,
        WidgetSettings,
        load_saved_settings,
        resolve_settings,
        save_settings,
        settings_directory,
        settings_file,
        webview_storage_dir,
    )
except ModuleNotFoundError:
    from settings import (  # type: ignore
        APP_NAME,
        WidgetSettings,
        load_saved_settings,
        resolve_settings,
        save_settings,
        settings_directory,
        settings_file,
        webview_storage_dir,
    )

TITLE = "DeskMail Widget"

user32 = ctypes.windll.user32

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_NOOWNERZORDER = 0x0200
HWND_BOTTOM = 1
SPI_GETWORKAREA = 0x0030
SMTO_NORMAL = 0x0000


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Native Windows host for the SamGPT desktop widget.")
    parser.add_argument("--url", default=None, help="Widget URL. Defaults to the hosted /widget page.")
    parser.add_argument("--width", type=int, default=None, help="Initial window width.")
    parser.add_argument("--height", type=int, default=None, help="Initial window height.")
    parser.add_argument("--x", type=int, default=None, help="Initial window X position.")
    parser.add_argument("--y", type=int, default=None, help="Initial window Y position.")
    parser.add_argument(
        "--always-on-top",
        dest="always_on_top",
        action="store_const",
        const=True,
        default=None,
        help="Keep the widget above other windows.",
    )
    parser.add_argument(
        "--not-always-on-top",
        dest="always_on_top",
        action="store_const",
        const=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--pin-desktop",
        dest="pin_desktop",
        action="store_const",
        const=True,
        default=None,
        help="Attach the widget to the desktop layer instead of normal windows.",
    )
    parser.add_argument(
        "--no-pin-desktop",
        dest="pin_desktop",
        action="store_const",
        const=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--hide-from-taskbar",
        dest="hide_from_taskbar",
        action="store_const",
        const=True,
        default=None,
        help="Hide the widget from the taskbar and Alt+Tab.",
    )
    parser.add_argument(
        "--show-in-taskbar",
        dest="hide_from_taskbar",
        action="store_const",
        const=False,
        help="Show the widget in the taskbar.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable the WebView debug mode.")
    parser.add_argument("--reset-settings", action="store_true", help="Reset saved position and size.")
    parser.add_argument("--close-after", type=float, default=0.0, help=argparse.SUPPRESS)
    return parser


def get_work_area() -> tuple[int, int, int, int]:
    rect = RECT()
    success = user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    if success:
        return rect.left, rect.top, rect.right, rect.bottom

    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return 0, 0, width, height


def with_default_position(settings: WidgetSettings) -> WidgetSettings:
    if settings.x is not None and settings.y is not None:
        return settings

    left, top, right, _ = get_work_area()
    x = settings.x if settings.x is not None else max(left + 12, right - settings.width - 36)
    y = settings.y if settings.y is not None else top + 36
    settings.x = x
    settings.y = y
    return settings


def wait_for_window_handle(title: str, timeout_seconds: float = 12.0) -> int:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd
        time.sleep(0.15)
    return 0


def apply_toolwindow(hwnd: int) -> None:
    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex_style = (ex_style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style)
    user32.SetWindowPos(
        hwnd,
        0,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED,
    )


def find_workerw() -> int:
    progman = user32.FindWindowW("Progman", None)
    result = wintypes.ULONG()
    if progman:
        user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result))

    workerw = ctypes.c_void_p(0)
    enum_windows = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, l_param: int) -> bool:
        shell_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if shell_view:
            sibling = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            if sibling:
                ctypes.cast(l_param, ctypes.POINTER(ctypes.c_void_p)).contents.value = sibling
                return False
        return True

    user32.EnumWindows(enum_windows(callback), ctypes.byref(workerw))
    return int(workerw.value or 0)


def pin_to_desktop(hwnd: int) -> None:
    workerw = find_workerw()
    parent = workerw or user32.FindWindowW("Progman", None)
    if not parent:
        return

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style = (style & ~WS_POPUP) | WS_CHILD | WS_VISIBLE
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    user32.SetParent(hwnd, parent)
    user32.SetWindowPos(
        hwnd,
        HWND_BOTTOM,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def persist_window_state(window: webview.Window, settings: WidgetSettings) -> None:
    settings.x = window.x
    settings.y = window.y
    settings.width = window.width
    settings.height = window.height
    save_settings(settings)


def build_overrides(args: argparse.Namespace) -> dict[str, object]:
    return {
        "url": args.url,
        "width": args.width,
        "height": args.height,
        "x": args.x,
        "y": args.y,
        "always_on_top": args.always_on_top,
        "pin_desktop": args.pin_desktop,
        "hide_from_taskbar": args.hide_from_taskbar,
        "debug": args.debug,
        "close_after": args.close_after if args.close_after else None,
    }


def build_tray_image():
    if Image is None or ImageDraw is None:
        raise RuntimeError("Pillow is required to build the tray icon.")

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((7, 8, 57, 56), radius=16, fill=(18, 29, 41, 255), outline=(141, 201, 192, 255), width=3)
    draw.rounded_rectangle((17, 18, 47, 42), radius=8, outline=(239, 244, 247, 255), width=3)
    draw.line((17, 20, 32, 32, 47, 20), fill=(233, 196, 131, 255), width=4)
    draw.line((17, 40, 47, 40), fill=(141, 201, 192, 255), width=3)
    draw.line((22, 47, 42, 47), fill=(239, 244, 247, 255), width=3)

    return image


class NativeShellApi:
    def __init__(self, settings: WidgetSettings) -> None:
        self._settings = settings
        self._window: webview.Window | None = None
        self._hwnd = 0
        self._tray_icon: pystray.Icon | None = None
        self._tray_lock = threading.RLock()
        self._hidden_to_tray = False

    def _tray_supported(self) -> bool:
        return pystray is not None and Image is not None and ImageDraw is not None

    def _attach_window(self, window: webview.Window) -> None:
        self._window = window

    def _set_hwnd(self, hwnd: int) -> None:
        self._hwnd = hwnd

    def _ensure_hwnd(self) -> int:
        if self._hwnd and user32.IsWindow(self._hwnd):
            return self._hwnd

        self._hwnd = wait_for_window_handle(TITLE, timeout_seconds=3.0)
        return self._hwnd

    def _apply_window_mode(self) -> None:
        hwnd = self._ensure_hwnd()
        if not hwnd:
            return

        if self._settings.hide_from_taskbar:
            apply_toolwindow(hwnd)

        if self._settings.pin_desktop:
            pin_to_desktop(hwnd)

    def _start_tray(self) -> bool:
        if not self._tray_supported():
            return False

        with self._tray_lock:
            if self._tray_icon is not None:
                return True

            icon = pystray.Icon(
                APP_NAME,
                build_tray_image(),
                "DeskMail",
                menu=pystray.Menu(
                    pystray.MenuItem("Show widget", self._menu_restore, default=True),
                    pystray.MenuItem("Hide to tray", self._menu_hide),
                    pystray.MenuItem("Quit DeskMail", self._menu_close),
                ),
            )
            self._tray_icon = icon

        threading.Thread(target=icon.run, daemon=True, name="deskmail-tray").start()
        return True

    def _notify_hidden(self) -> None:
        with self._tray_lock:
            icon = self._tray_icon

        if icon is None:
            return

        try:
            icon.notify("DeskMail is still running in the system tray.", "DeskMail")
        except Exception:
            pass

    def _menu_restore(self, icon=None, item=None) -> None:
        self.restore_from_tray()

    def _menu_hide(self, icon=None, item=None) -> None:
        self.minimize_to_tray()

    def _menu_close(self, icon=None, item=None) -> None:
        self.close_window()

    def minimize_to_tray(self) -> dict[str, object]:
        if self._window is None:
            return {"ok": False, "mode": "missing"}

        if not self._start_tray():
            self._window.minimize()
            return {"ok": True, "mode": "minimized"}

        self._hidden_to_tray = True
        self._window.hide()
        self._notify_hidden()
        return {"ok": True, "mode": "tray"}

    def restore_from_tray(self) -> dict[str, object]:
        if self._window is None:
            return {"ok": False}

        self._hidden_to_tray = False
        self._window.show()
        self._window.restore()
        self._apply_window_mode()
        return {"ok": True}

    def close_window(self) -> bool:
        self._stop_tray()
        if self._window is not None:
            self._window.destroy()
        return True

    def open_full_app(self, url: str) -> bool:
        if not url:
            return False
        webbrowser.open(url, new=2, autoraise=True)
        return True

    def _stop_tray(self) -> None:
        with self._tray_lock:
            icon = self._tray_icon
            self._tray_icon = None

        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass

    def _shutdown(self) -> None:
        self._stop_tray()


def create_window(settings: WidgetSettings, shell_api: NativeShellApi) -> webview.Window:
    return webview.create_window(
        TITLE,
        url=settings.url,
        js_api=shell_api,
        width=settings.width,
        height=settings.height,
        x=settings.x,
        y=settings.y,
        resizable=True,
        min_size=(420, 560),
        frameless=True,
        easy_drag=False,
        shadow=True,
        on_top=settings.always_on_top,
        background_color="#0F1721",
        text_select=True,
    )


def bootstrap_native_shell(window: webview.Window, settings: WidgetSettings, shell_api: NativeShellApi) -> None:
    hwnd = wait_for_window_handle(TITLE)
    if not hwnd:
        return

    shell_api._set_hwnd(hwnd)
    shell_api._apply_window_mode()

    if settings.close_after > 0:
        time.sleep(settings.close_after)
        window.destroy()


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.reset_settings:
        settings_path = settings_file()
        if settings_path.exists():
            settings_path.unlink()

    settings_directory().mkdir(parents=True, exist_ok=True)
    saved = load_saved_settings()
    settings = with_default_position(resolve_settings(saved, build_overrides(args)))

    shell_api = NativeShellApi(settings)
    window = create_window(settings, shell_api)
    shell_api._attach_window(window)

    window.events.moved += lambda *_: persist_window_state(window, settings)
    window.events.resized += lambda *_: persist_window_state(window, settings)
    window.events.closing += lambda *_: persist_window_state(window, settings)
    window.events.closing += lambda *_: shell_api._shutdown()
    window.events.shown += lambda *_: threading.Thread(
        target=bootstrap_native_shell, args=(window, settings, shell_api), daemon=True
    ).start()

    # Keep the default browser UA so Cloudflare Turnstile sees a normal WebView2/Edge client.
    webview.start(
        debug=settings.debug,
        private_mode=False,
        storage_path=str(webview_storage_dir()),
    )


if __name__ == "__main__":
    main()
