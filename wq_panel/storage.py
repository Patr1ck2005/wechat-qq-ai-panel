"""Bounded private state and explicit, recoverable cleanup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading


class StorageError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


DEFAULT_PRESETS = [
    {"id": "brief", "name": "新消息速览", "daily": False, "prompt": "用中文概括新消息。按主题整理重要进展、需要我留意的事项，附上来源编号。明确区分事实与推测，略过无信息量闲聊。"},
    {"id": "actions", "name": "待办与待回复", "daily": False, "prompt": "提取需要我采取行动、回复或等待对方的事项。每项写清行动、已给出的截止时间和来源编号。不要猜测未给出的责任人或日期。"},
    {"id": "daily", "name": "今日回顾", "daily": True, "prompt": "整理今天的主要进展、已完成事项、未完成事项和后续关注点。按主题组织并保留来源编号。不要编造消息里没有的信息。"},
]


def default_settings() -> dict:
    return {"schemaVersion": 1, "watched": [], "selectedPreset": "brief",
            "presets": [dict(x) for x in DEFAULT_PRESETS],
            "model": {"backend": "dsh", "dsh": {"executable": "", "home": "", "provider": "", "model": ""},
                      "api": {"base_url": "", "model": "", "key_env": "", "credential_name": "WeChatQQAIPanel/API"}}}


def is_link(path: Path) -> bool:
    """Include Windows junctions/reparse points (Path.is_symlink misses junctions)."""
    try:
        return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WeChatQQAIPanel").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.settings = self._read("settings.json", default_settings())
        defaults = default_settings()
        if (self.settings.get("schemaVersion") != 1 or not isinstance(self.settings.get("presets"), list)
                or not self.settings.get("presets") or not isinstance(self.settings.get("model"), dict)):
            self.settings = defaults
        self.settings.setdefault("watched", [])
        self.settings.setdefault("selectedPreset", self.settings["presets"][0].get("id", "brief"))
        for name in ("api", "dsh"):
            self.settings["model"].setdefault(name, defaults["model"][name])
        state = self._read("state.json", {})
        self.cursors = state.get("cursors", {}) if isinstance(state.get("cursors", {}), dict) else {}
        self.results = state.get("results", {}) if isinstance(state.get("results", {}), dict) else {}

    def _read(self, name, fallback):
        try:
            value = json.loads((self.root / name).read_text(encoding="utf-8"))
            return value if isinstance(value, type(fallback)) else fallback
        except (OSError, ValueError):
            return fallback

    def write(self, name: str, value):
        with self.lock:
            target = self.root / name
            temporary = target.with_suffix(".new")
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)

    def save_settings(self):
        self.write("settings.json", self.settings)

    def commit_result(self, preset_id: str, result: dict, cursor_updates: dict):
        with self.lock:
            # Refuse exceptionally large results explicitly instead of truncating source IDs.
            # At most 20 presets are permitted; each retains one <=8 MiB result.
            if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 8 * 1024 * 1024:
                raise StorageError("RESULT_TOO_LARGE")
            merged_cursors = {**self.cursors, **cursor_updates}
            if len(json.dumps(merged_cursors).encode("utf-8")) > 8 * 1024 * 1024:
                raise StorageError("CURSOR_LIMIT")
            self.replace_state(merged_cursors, {**self.results, preset_id: result})

    def replace_state(self, cursors: dict, results: dict):
        with self.lock:
            if len(json.dumps(cursors).encode("utf-8")) > 8 * 1024 * 1024:
                raise StorageError("CURSOR_LIMIT")
            # One atomic replace is the commit boundary for both result and cursor.
            self.write("state.json", {"schemaVersion": 1, "cursors": cursors, "results": results})
            self.cursors, self.results = cursors, results

    def commit_cursors(self, updates: dict):
        self.replace_state({**self.cursors, **updates}, self.results)

    def invalidate(self, allowed):
        with self.lock:
            results = {key: item for key, item in self.results.items() if set(item.get("refs", [])).issubset(allowed)}
            self.replace_state(self.cursors, results)

    def preview(self, busy: bool = False) -> list[dict]:
        specs = [("results", "整理结果（保留读取进度）", self.root / "state.json", busy),
                 ("dsh", "DSH 专用执行记录", self.root / "dsh", busy),
                 ("webview", "窗口缓存", self.root / "webview", True)]
        out = []
        for ident, label, path, active in specs:
            total, files, links = 0, 0, False
            if is_link(path):
                links = True
            elif path.is_file():
                total, files = path.stat().st_size, 1
            elif path.is_dir():
                for current, dirs, names in os.walk(path, followlinks=False):
                    if any(is_link(Path(current) / name) for name in dirs):
                        links = True
                    dirs[:] = [name for name in dirs if not is_link(Path(current) / name)]
                    for name in names:
                        entry = Path(current) / name
                        if is_link(entry):
                            links = True
                            continue
                        try:
                            total += entry.stat().st_size
                            files += 1
                        except OSError:
                            pass
            out.append({"id": ident, "label": label, "bytes": total, "files": files,
                        "skipped": active or links, "reason": "使用中" if active else ("含链接" if links else ""),
                        "canSchedule": ident == "webview" and not links,
                        "scheduled": ident == "webview" and bool(self.settings.get("cleanupWebviewOnNextStart")),
                        "warning": ident == "dsh" and total >= 200 * 1024 * 1024})
        return out

    def schedule_webview_cleanup(self):
        self.settings["cleanupWebviewOnNextStart"] = True
        self.save_settings()
        return {"scheduled": True}

    def startup_cleanup(self, recycler=None):
        """Called by the primary host only, before WebView creation; never exposed to JS."""
        if not self.settings.get("cleanupWebviewOnNextStart"):
            return
        path = self.root / "webview"
        if path.exists() or is_link(path):
            entry = next(x for x in self.preview() if x["id"] == "webview")
            if entry["reason"] == "含链接" or is_link(path) or not path.resolve().is_relative_to(self.root):
                raise StorageError("UNSAFE_CLEANUP_PATH")
            # Scan reparse points separately because preview reports its active skip first.
            for current, dirs, files in os.walk(path, followlinks=False):
                if any(is_link(Path(current) / name) for name in dirs + files):
                    raise StorageError("UNSAFE_CLEANUP_PATH")
            (recycler or recycle)(path)
            if path.exists():
                raise StorageError("RECYCLE_FAILED")
        self.settings["cleanupWebviewOnNextStart"] = False
        self.save_settings()

    def clean(self, category: str, busy: bool = False, recycler=None) -> dict:
        owned = {"results": "state.json", "dsh": "dsh", "webview": "webview"}
        if category not in owned:
            raise ValueError("INVALID_CATEGORY")
        item = next(x for x in self.preview(busy) if x["id"] == category)
        if item["skipped"]:
            return {"recycled": False, "skipped": True, "reason": item["reason"]}
        target = self.root / owned[category]
        if target.parent != self.root or is_link(target) or not target.resolve().is_relative_to(self.root):
            raise ValueError("UNSAFE_CLEANUP_PATH")
        if not target.exists():
            return {"recycled": False, "skipped": False, "absent": True}
        (recycler or recycle)(target)
        if target.exists():
            raise OSError("RECYCLE_FAILED")
        if category == "results":
            self.replace_state(self.cursors, {})
        return {"recycled": True, "skipped": False, "bytesMoved": item["bytes"], "spaceFreed": 0}


def recycle(path: Path):
    """Use the actual Windows Recycle Bin; never fall back to unlink/rmtree."""
    if os.name != "nt":
        raise OSError("RECYCLE_REQUIRES_WINDOWS")
    try:
        # Deliberately import the modern implementation, not the package's
        # compatibility dispatcher, so missing support fails rather than falling
        # back to a best-effort legacy shell delete.
        from send2trash.win.modern import send2trash
        send2trash(str(path.resolve()))
    except Exception:
        raise StorageError("RECYCLE_FAILED") from None
