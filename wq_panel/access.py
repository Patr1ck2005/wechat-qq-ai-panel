"""The only message-reading boundary used by the panel."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import shutil
import threading


class AccessError(RuntimeError):
    def __init__(self, code: str = "ACCESS_FAILED"):
        self.code = code if isinstance(code, str) and code.replace("_", "").isalnum() else "ACCESS_FAILED"
        super().__init__(self.code)


class AccessClient:
    def __init__(self, config_path: Path | None = None):
        self._connection_lock = threading.RLock()
        self._explicit_config = Path(config_path) if config_path is not None else None
        self.config_path = self._select_config()

    def _select_config(self) -> Path:
        with self._connection_lock:
            return self._select_config_locked()

    def _select_config_locked(self) -> Path:
        local = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        self._diagnostic_root = local / "WeChatQQAIPanel"
        pointer = self._diagnostic_root / "access-config.json"
        regular = Path.home() / ".local/share/wechat-qq-access/deployment.json"
        legacy = local / "MessagingAccess/deployment.json"
        default = regular if regular.exists() or not legacy.exists() else legacy
        environment = os.environ.get("MESSAGING_ACCESS_CONFIG")
        self._connection_state = {
            "configSource": "explicit" if self._explicit_config is not None else "environment" if environment else "default",
            "pointerExists": False, "pointerValid": False,
            "selectedMatchesPointer": False, "selectedMatchesDefault": False,
            "configExists": False, "pythonExists": False, "rootExists": False,
        }
        saved_path, pointer_error = None, None
        try:
            self._connection_state["pointerExists"] = pointer.exists()
            if self._connection_state["pointerExists"]:
                value = json.loads(pointer.read_text(encoding="utf-8-sig"))
                saved_path = value["configPath"]
                if not isinstance(saved_path, str) or not Path(saved_path).is_absolute():
                    raise ValueError()
                saved_path = Path(saved_path)
                self._connection_state["pointerValid"] = True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            pointer_error = exc
        if self._explicit_config is not None:
            selected = self._explicit_config
        elif environment:
            selected = Path(environment)
        elif self._connection_state["pointerExists"] or pointer_error is not None:
            self._connection_state["configSource"] = "installer_pointer"
            if pointer_error is not None:
                self._fail("DEPLOYMENT_POINTER_INVALID", "pointer", pointer_error)
            selected = saved_path
        else:
            selected = default
        def same(left, right):
            if left is None or right is None:
                return False
            return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))
        self._connection_state["selectedMatchesPointer"] = same(selected, saved_path)
        self._connection_state["selectedMatchesDefault"] = same(selected, default)
        return Path(selected)

    def _fail(self, code: str, stage: str, exc=None):
        # Fixed vocabulary only. No exception text, paths, JSON, account data or
        # credentials can reach this bounded, overwritten diagnostic snapshot.
        types = {"FileNotFoundError", "PermissionError", "OSError", "JSONDecodeError", "UnicodeDecodeError",
                 "ValueError", "KeyError", "TypeError"}
        exception_type = type(exc).__name__ if exc is not None else "None"
        if exception_type not in types | {"None"}:
            exception_type = "Other"
        data = {"schemaVersion": 1, "stage": stage, "code": code,
                **self._connection_state, "exceptionType": exception_type}
        try:
            self._diagnostic_root.mkdir(parents=True, exist_ok=True)
            target = self._diagnostic_root / "connection-diagnostic.json"
            temporary = self._diagnostic_root / "connection-diagnostic.new"
            encoded = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
            if len(encoded.encode("ascii")) <= 2048:
                temporary.write_text(encoded, encoding="utf-8")
                os.replace(temporary, target)
        except (OSError, ValueError):
            pass  # Diagnostic failure must not replace or relax the actual error.
        raise AccessError(code) from None

    def _deployment(self) -> dict:
        with self._connection_lock:
            return self._deployment_locked()

    def _deployment_locked(self) -> dict:
        # Re-resolve automatic configuration after installer changes. Explicit
        # constructor input remains pinned; invalid selected input never falls back.
        self.config_path = self._select_config()
        try:
            self._connection_state["configExists"] = self.config_path.is_file()
            if not self._connection_state["configExists"]:
                self._fail("DEPLOYMENT_CONFIG_MISSING", "config")
            source = self.config_path.read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            self._fail("DEPLOYMENT_CONFIG_INVALID", "config", exc)
        except OSError as exc:
            self._fail("DEPLOYMENT_CONFIG_UNREADABLE", "config", exc)
        try:
            config = json.loads(source)
            if (not isinstance(config, dict) or any(not isinstance(config.get(key), str) or not config[key]
                                                  for key in ("pythonExe", "projectRoot"))):
                raise ValueError()
            python, root = Path(config["pythonExe"]), Path(config["projectRoot"])
            if not python.is_absolute() or not root.is_absolute():
                raise ValueError()
        except (ValueError, KeyError, TypeError) as exc:
            self._fail("DEPLOYMENT_CONFIG_INVALID", "config", exc)
        try:
            self._connection_state["pythonExists"] = python.is_file()
            self._connection_state["rootExists"] = root.is_dir()
        except (OSError, ValueError) as exc:
            self._fail("DEPLOYMENT_PATH_CHECK_FAILED", "runtime", exc)
        if not self._connection_state["pythonExists"]:
            self._fail("DEPLOYMENT_PYTHON_MISSING", "runtime")
        if not self._connection_state["rootExists"]:
            self._fail("DEPLOYMENT_ROOT_MISSING", "runtime")
        return config

    def call(self, action: str, **kwargs) -> dict:
        with self._connection_lock:
            config = self._deployment()
            config_path = self.config_path
        script = Path(config["projectRoot"]) / "scripts/access.py"
        env = os.environ.copy()
        env["MESSAGING_ACCESS_CONFIG"] = str(config_path)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            result = subprocess.run(
                [config["pythonExe"], str(script)],
                input=json.dumps({"action": action, **kwargs}, ensure_ascii=False),
                capture_output=True, encoding="utf-8", errors="strict", env=env,
                timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            payload = json.loads(result.stdout)
            if not payload.get("ok"):
                raise AccessError(payload.get("error", {}).get("code", "ACCESS_FAILED"))
            if result.returncode or not isinstance(payload.get("data"), dict):
                raise AccessError("ACCESS_RESPONSE_INVALID")
            return payload["data"]
        except AccessError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError, UnicodeError):
            raise AccessError("ACCESS_UNAVAILABLE") from None

    def cache(self, clean: bool = False, category: str = "WeChatCache") -> dict:
        if category not in {"WeChatCache", "WeChatMedia", "Snapshots", "Logs"}:
            raise AccessError("INVALID_CATEGORY")
        with self._connection_lock:
            config = self._deployment()
            config_path = self.config_path
        pwsh = shutil.which("pwsh")
        if not pwsh:
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell/7/pwsh.exe"
            if candidate.is_file():
                pwsh = str(candidate)
        if not pwsh:
            raise AccessError("POWERSHELL_7_REQUIRED")
        command = [pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(Path(config["projectRoot"]) / "scripts/cache.ps1"),
                   "-ConfigPath", str(config_path), "-Action", "Clean" if clean else "Status",
                   "-Category", category, "-Json"]
        try:
            result = subprocess.run(command, capture_output=True, timeout=180, encoding="utf-8", errors="replace",
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise AccessError("CACHE_OPERATION_FAILED")
            data = json.loads(result.stdout.lstrip("\ufeff"))
            # Whitelist aggregate fields; never forward paths or exception text.
            return {"categories": [{"id": "access:" + str(item["Category"]), "label": str(item["Category"]),
                                     "bytes": int(float(item.get("MiB", 0)) * 1024 * 1024),
                                     "files": int(item.get("Files", 0)),
                                     "eligible": int(item.get("ReclaimableFiles", 0)),
                                     "recycled": int(item.get("RecycledFiles", 0)),
                                     "failed": int(item.get("FailedOrChangedFiles", 0)),
                                     "skipped": bool(data.get("WeChatReaderActive")) if category.startswith("WeChat") else False,
                                     "reason": "活跃读取中" if data.get("WeChatReaderActive") else "", "warning": False}
                                    for item in data.get("Categories", [])], "spaceFreed": 0}
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
            raise AccessError("CACHE_OPERATION_FAILED") from None
