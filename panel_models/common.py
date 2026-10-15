"""Small public errors intentionally never contain provider exception text."""

import asyncio
import ipaddress
import re
from urllib.parse import urlsplit


class ModelError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class ModelCancelled(ModelError):
    def __init__(self):
        super().__init__("CANCELLED", "任务已停止。")


def identifier(value, *, code="MODEL_CONFIG", max_length=256):
    if not isinstance(value, str) or not value.strip() or len(value) > max_length or any(ord(x) < 32 for x in value):
        raise ModelError(code, "模型配置包含无效名称。")
    return value.strip()


def env_reference(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ModelError("CREDENTIAL_REFERENCE", "密钥必须使用环境变量名称或 Windows 凭据名称。")
    return value


def safe_base_url(value):
    value = identifier(value, max_length=2048)
    try:
        url = urlsplit(value)
    except ValueError:
        raise ModelError("MODEL_URL", "API 地址格式无效。") from None
    try:
        local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = url.hostname == "localhost"
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ModelError("MODEL_URL", "API 地址须为不含凭据、查询参数和片段的 HTTP(S) 地址。")
    if url.scheme == "http" and not local:
        raise ModelError("MODEL_URL", "远程 API 地址须使用 HTTPS；本机服务可使用 HTTP。")
    return value.rstrip("/")


async def cancellable(awaitable, cancel, interval=0.05):
    """Cancel pending network/SDK operations promptly, including a silent stream."""
    task = asyncio.ensure_future(awaitable)
    try:
        while not task.done():
            if cancel.is_set():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
                raise ModelCancelled()
            await asyncio.wait({task}, timeout=interval)
        if cancel.is_set():
            raise ModelCancelled()
        return await task
    finally:
        if not task.done():
            task.cancel()


def quiet_sdk_logs():
    # SDK debug logs can contain request bodies. The UI exposes only our fixed
    # error codes; never attach raw SDK exceptions to application diagnostics.
    import logging
    for name in ("openai", "httpx", "httpx2", "httpcore", "acp"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.CRITICAL)
        logger.propagate = False
