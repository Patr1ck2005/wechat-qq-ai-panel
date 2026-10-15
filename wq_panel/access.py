"""The only message-reading boundary used by the panel."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import shutil


class AccessError(RuntimeError):
    def __init__(self, code: str = "ACCESS_FAILED"):
        self.code = code if isinstance(code, str) and code.replace("_", "").isalnum() else "ACCESS_FAILED"
        super().__init__(self.code)


class AccessClient:
    def __init__(self, config_path: Path | None = None):
        saved_path = None
        if config_path is None and not os.environ.get("MESSAGING_ACCESS_CONFIG"):
            pointer = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "WeChatQQAIPanel/access-config.json"
            if pointer.exists():
                try:
                    saved_path = json.loads(pointer.read_text(encoding="utf-8-sig"))["configPath"]
                    if not isinstance(saved_path, str) or not Path(saved_path).is_absolute():
                        raise ValueError()
                except (OSError, ValueError, KeyError, TypeError):
                    raise AccessError("DEPLOYMENT_UNAVAILABLE") from None
        self.config_path = Path(config_path or os.environ.get("MESSAGING_ACCESS_CONFIG") or saved_path or
                                Path(os.environ.get("LOCALAPPDATA", Path.home())) / "MessagingAccess/deployment.json")

    def _deployment(self) -> dict:
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            if not Path(config["pythonExe"]).is_file() or not Path(config["projectRoot"]).is_dir():
                raise ValueError()
            return config
        except (OSError, ValueError, KeyError, TypeError):
            raise AccessError("DEPLOYMENT_UNAVAILABLE") from None

    def call(self, action: str, **kwargs) -> dict:
        config = self._deployment()
        script = Path(config["projectRoot"]) / "scripts/access.py"
        env = os.environ.copy()
        env["MESSAGING_ACCESS_CONFIG"] = str(self.config_path)
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
        config = self._deployment()
        pwsh = shutil.which("pwsh")
        if not pwsh:
            candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "PowerShell/7/pwsh.exe"
            if candidate.is_file():
                pwsh = str(candidate)
        if not pwsh:
            raise AccessError("POWERSHELL_7_REQUIRED")
        command = [pwsh, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                   "-File", str(Path(config["projectRoot"]) / "scripts/cache.ps1"),
                   "-ConfigPath", str(self.config_path), "-Action", "Clean" if clean else "Status",
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
