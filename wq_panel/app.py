"""Windows tray host. UI uses in-process pywebview bridging, never HTTP."""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import threading

from .access import AccessClient
from .controller import Controller, PanelError, safe_error
from .storage import Store


APP_USER_MODEL_ID = "WeChatQQAI.Panel"
MIN_WINDOW_WIDTH = 600


def set_application_identity():
    """Identify the process before WinForms creates its first native window."""
    if os.name == "nt":
        setter = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
        setter.argtypes = (ctypes.c_wchar_p,)
        setter.restype = ctypes.c_long
        if setter(APP_USER_MODEL_ID) != 0:
            raise PanelError("APP_ID_UNAVAILABLE")


def load_app_icons(asset_directory=None):
    """Use the bundled identity at every native surface; never use Python's icon."""
    from PIL import Image
    import xml.etree.ElementTree as ET
    directory = Path(asset_directory) if asset_directory is not None else Path(__file__).parent / "assets"
    icon = directory / "app.ico"
    tray = directory / "app.png"
    vector = directory / "app.svg"
    if not icon.is_file() or not tray.is_file() or not vector.is_file():
        raise PanelError("APP_ICON_MISSING")
    try:
        with Image.open(icon) as source:
            if source.format != "ICO":
                raise ValueError()
            source.load()
        with Image.open(tray) as source:
            if source.format != "PNG":
                raise ValueError()
            image = source.convert("RGBA")
        svg = vector.read_text(encoding="utf-8")
        if ET.fromstring(svg).tag != "{http://www.w3.org/2000/svg}svg":
            raise ValueError()
    except (OSError, ValueError, ET.ParseError):
        raise PanelError("APP_ICON_INVALID") from None
    return icon.resolve(), image, svg


BRIDGE_METHODS = ("bootstrap", "status", "catalog", "conversations", "save_policy", "save_settings", "start", "stop",
                  "result", "storage", "clean", "save_api_key", "delete_api_key", "discover_dsh", "copy_result",
                  "export_result", "hide", "quit")


def expose_bridge(window, bridge):
    # An explicit function allowlist avoids pywebview recursively walking js_api
    # objects such as controller.reader/store or the native window itself.
    window.expose(*(getattr(bridge, name) for name in BRIDGE_METHODS))


class Bridge:
    def __init__(self, controller):
        self.controller = controller
        self.window = None
        self.quit_callback = None

    def _call(self, function, *args, **kwargs):
        try:
            return {"ok": True, "data": function(*args, **kwargs)}
        except Exception as exc:
            return {"ok": False, "error": safe_error(exc)}

    def bootstrap(self):
        return self._call(self.controller.bootstrap)

    def status(self):
        return self._call(self.controller.status)

    def catalog(self):
        return self._call(self.controller.catalog)

    def conversations(self):
        return self._call(self.controller.conversations)

    def save_policy(self, accounts, watched):
        return self._call(self.controller.save_policy, accounts, watched)

    def save_settings(self, settings):
        return self._call(self.controller.save_settings, settings)

    def start(self, action, preset, refs=None):
        return self._call(self.controller.start, action, preset, refs)

    def stop(self):
        return self._call(self.controller.stop)

    def result(self, preset):
        return self._call(self.controller.result, preset)

    def storage(self):
        def execute():
            categories = self.controller.store.preview(self.controller.status()["busy"])
            available = True
            for kind in ("WeChatCache", "WeChatMedia", "Snapshots", "Logs"):
                try:
                    categories.extend(self.controller.reader.cache(category=kind)["categories"])
                except Exception:
                    available = False
                    break
            return {"categories": categories, "accessAvailable": available,
                    "note": "只清理本产品已识别的副本。底座默认保留最近7天；移入回收站不等于释放磁盘空间。"}
        return self._call(execute)

    def clean(self, category):
        with self.controller.lock:
            if category == "webview":
                return self._call(self.controller.store.schedule_webview_cleanup)
            if isinstance(category, str) and category.startswith("access:"):
                if self.controller.state["busy"]:
                    return {"ok": True, "data": {"skipped": True, "reason": "任务运行中"}}
                return self._call(self.controller.reader.cache, True, category.split(":", 1)[1])
            return self._call(self.controller.store.clean, category, self.controller.state["busy"])

    def save_api_key(self, name, value):
        def execute():
            if not isinstance(name, str) or not 1 <= len(name) <= 200 or not isinstance(value, str) or not value:
                raise PanelError("INVALID_SETTINGS")
            from panel_models import store_api_key
            store_api_key(name, value)
            return {"saved": True}
        return self._call(execute)

    def delete_api_key(self, name):
        def execute():
            if not isinstance(name, str) or not 1 <= len(name) <= 200:
                raise PanelError("INVALID_SETTINGS")
            from panel_models import delete_api_key
            delete_api_key(name)
            return {"deleted": True}
        return self._call(execute)

    def discover_dsh(self):
        def execute():
            from panel_models import discover_dsh
            return discover_dsh()
        return self._call(execute)

    def copy_result(self, preset):
        def execute():
            result = self.controller.result(preset).get("result")
            if not result:
                raise PanelError("RESULT_UNAVAILABLE")
            copy_clipboard(markdown_result(result))
            return {"copied": True}
        return self._call(execute)

    def export_result(self, preset):
        def execute():
            if not self.window:
                raise PanelError("WINDOW_UNAVAILABLE")
            result = self.controller.result(preset).get("result")
            if not result:
                raise PanelError("RESULT_UNAVAILABLE")
            import webview
            selected = self.window.create_file_dialog(webview.SAVE_DIALOG, save_filename="chat-summary.md",
                                                     file_types=("Markdown (*.md)",))
            if not selected:
                return {"cancelled": True}
            path = Path(selected[0] if isinstance(selected, (list, tuple)) else selected)
            # Re-check after the native dialog; policy might have changed while it was open.
            result = self.controller.result(preset).get("result")
            if not result:
                raise PanelError("RESULT_UNAVAILABLE")
            path.write_text(markdown_result(result), encoding="utf-8")
            return {"exported": True}
        return self._call(execute)

    def hide(self):
        if self.window:
            self.window.hide()
        return {"ok": True, "data": {}}

    def quit(self):
        if self.quit_callback:
            self.quit_callback()
        return {"ok": True, "data": {}}


def markdown_result(result):
    text = result["text"] + "\n\n---\n\n来源\n\n"
    return text + "\n".join(f"- [{source['id']}] {source['title']} · {source['time']} · 消息 {source['messageId']}"
                            for source in result.get("sources", [])) + "\n"


def copy_clipboard(text):
    if os.name != "nt":
        raise PanelError("CLIPBOARD_REQUIRES_WINDOWS")
    kernel = ctypes.windll.kernel32
    user = ctypes.windll.user32
    kernel.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel.GlobalAlloc.restype = ctypes.c_void_p
    kernel.GlobalLock.argtypes = (ctypes.c_void_p,)
    kernel.GlobalLock.restype = ctypes.c_void_p
    kernel.GlobalUnlock.argtypes = (ctypes.c_void_p,)
    kernel.GlobalFree.argtypes = (ctypes.c_void_p,)
    user.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.c_void_p)
    user.SetClipboardData.restype = ctypes.c_void_p
    data = (text + "\0").encode("utf-16-le")
    handle = kernel.GlobalAlloc(0x0002, len(data))
    if not handle:
        raise PanelError("CLIPBOARD_UNAVAILABLE")
    pointer = kernel.GlobalLock(handle)
    if not pointer:
        kernel.GlobalFree(handle)
        raise PanelError("CLIPBOARD_UNAVAILABLE")
    ctypes.memmove(pointer, data, len(data))
    kernel.GlobalUnlock(handle)
    if not user.OpenClipboard(None):
        kernel.GlobalFree(handle)
        raise PanelError("CLIPBOARD_UNAVAILABLE")
    try:
        user.EmptyClipboard()
        if not user.SetClipboardData(13, handle):
            kernel.GlobalFree(handle)
            raise PanelError("CLIPBOARD_UNAVAILABLE")
    finally:
        user.CloseClipboard()


class SingleInstance:
    def __init__(self):
        self.handle = self.event = None
        self.primary = True
        if os.name == "nt":
            kernel = ctypes.windll.kernel32
            kernel.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.CreateEventW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_wchar_p)
            kernel.CreateEventW.restype = ctypes.c_void_p
            self.handle = kernel.CreateMutexW(None, False, "Local\\WeChatQQAIPanel.Mutex")
            if not self.handle:
                raise PanelError("SINGLE_INSTANCE_FAILED")
            self.primary = kernel.GetLastError() != 183
            self.event = kernel.CreateEventW(None, False, False, "Local\\WeChatQQAIPanel.Activate")
            if not self.event:
                self.close()
                raise PanelError("SINGLE_INSTANCE_FAILED")
            if not self.primary:
                kernel.SetEvent.argtypes = (ctypes.c_void_p,)
                kernel.SetEvent(self.event)

    def listen(self, show, stopped):
        if not self.event:
            return
        kernel = ctypes.windll.kernel32
        kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint)
        while not stopped.is_set():
            if kernel.WaitForSingleObject(self.event, 1000) == 0:
                show()

    def close(self):
        if os.name == "nt":
            close = ctypes.windll.kernel32.CloseHandle
            close.argtypes = (ctypes.c_void_p,)
            for handle in (self.event, self.handle):
                if handle:
                    close(handle)


def run(config_path: Path | None = None):
    instance = SingleInstance()
    if not instance.primary:
        instance.close()
        return
    try:
        native_icon, icon_image, svg_icon = load_app_icons()
        set_application_identity()
    except PanelError as exc:
        instance.close()
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None,
                "应用图标或窗口身份无法加载，请重新运行安装脚本。\n错误代码：" + exc.code,
                "微信 · QQ AI — 启动失败", 0x10)
        raise
    import webview
    import pystray
    store = Store()
    controller = Controller(AccessClient(config_path), store)
    try:
        store.startup_cleanup()
    except Exception:
        controller.state["progress"] = "窗口缓存暂未清理，已保留；可在空间管理中重试。"
    bridge = Bridge(controller)
    html = (Path(__file__).parent / "ui.html").read_text(encoding="utf-8")
    # Only the repository's bundled vector is inserted; message/model text never enters HTML.
    html = html.replace("<!--APP_ICON-->", svg_icon)
    window = webview.create_window("微信 · QQ AI", html=html, width=MIN_WINDOW_WIDTH, height=720,
                                   min_size=(MIN_WINDOW_WIDTH, 540), background_color="#f3f4f5", text_select=True)
    expose_bridge(window, bridge)
    bridge.window = window
    stopped = threading.Event()
    exiting = threading.Event()
    def show(*_args):
        window.show()
        window.restore()
    icon = pystray.Icon("wechat-qq-ai-panel", icon_image, "微信 / QQ AI 小面板")
    def quit_app(*_args):
        exiting.set()
        stopped.set()
        controller.stop()
        if controller.thread and controller.thread.is_alive():
            controller.thread.join(timeout=3)
        icon.stop()
        window.destroy()
    bridge.quit_callback = quit_app
    icon.menu = pystray.Menu(pystray.MenuItem("打开面板", show, default=True),
                            pystray.MenuItem("退出", quit_app))
    def closing():
        if exiting.is_set():
            return True
        window.hide()
        return False
    window.events.closing += closing
    def started():
        threading.Thread(target=icon.run, daemon=True).start()
        threading.Thread(target=instance.listen, args=(show, stopped), daemon=True).start()
    try:
        # Inline HTML avoids pywebview's file-serving HTTP mode.
        # pywebview 6.2.1's WinForms host loads this ICO through System.Drawing.Icon.
        webview.start(started, gui="edgechromium", debug=False, private_mode=True,
                      storage_path=str(store.root / "webview"), icon=str(native_icon))
    finally:
        stopped.set()
        controller.stop()
        icon.stop()
        instance.close()
