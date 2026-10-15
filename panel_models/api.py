"""OpenAI's official Python SDK, restricted to text Chat Completions."""

import asyncio
import os

from .common import (ModelCancelled, ModelError, cancellable, env_reference,
                     identifier, quiet_sdk_logs, safe_base_url)

SERVICE_NAME = "WeChatQQAIPanel"


def _credential_backend():
    # Select Windows Credential Manager explicitly. A user-installed plaintext
    # keyring backend must never silently receive an API key.
    if os.name != "nt":
        raise ModelError("CREDENTIAL_UNAVAILABLE", "此密钥存储仅支持 Windows 凭据管理器。")
    try:
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    except Exception:
        raise ModelError("CREDENTIAL_UNAVAILABLE", "Windows 凭据管理器不可用；可改用环境变量。") from None


def store_api_key(name, value):
    name = identifier(name, max_length=80)
    if not isinstance(value, str) or not value.strip() or len(value) > 16384:
        raise ModelError("CREDENTIAL_VALUE", "请输入有效密钥。")
    try:
        _credential_backend().set_password(SERVICE_NAME, name, value)
    except ModelError:
        raise
    except Exception:
        raise ModelError("CREDENTIAL_WRITE", "无法保存 Windows 凭据。") from None


def delete_api_key(name):
    name = identifier(name, max_length=80)
    try:
        _credential_backend().delete_password(SERVICE_NAME, name)
    except ModelError:
        raise
    except Exception:
        raise ModelError("CREDENTIAL_DELETE", "无法删除 Windows 凭据；该项可能不存在。") from None


def _resolve_key(config):
    env = config.get("key_env", "")
    credential = config.get("credential_name", "")
    if env:
        key = os.environ.get(env_reference(env))
    elif credential:
        try:
            key = _credential_backend().get_password(SERVICE_NAME, identifier(credential, max_length=80))
        except ModelError:
            raise
        except Exception:
            raise ModelError("CREDENTIAL_READ", "无法读取 Windows 凭据。") from None
    else:
        key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ModelError("CREDENTIAL_MISSING", "找不到所选 API 的密钥；请设置环境变量或保存 Windows 凭据。")
    return key


def _new_client(**kwargs):
    try:
        from openai import AsyncOpenAI
    except ImportError:
        raise ModelError("MODEL_DEPENDENCY", "缺少 OpenAI Python SDK，请重新运行安装程序。") from None
    return AsyncOpenAI(**kwargs)


class ApiModel:
    def __init__(self, config):
        if not isinstance(config, dict) or set(config) - {"base_url", "model", "key_env", "credential_name"}:
            raise ModelError("MODEL_CONFIG", "API 配置只能保存地址、模型和凭据引用。")
        self.config = dict(config)
        self.base_url = safe_base_url(config.get("base_url", "https://api.openai.com/v1"))
        self.model = identifier(config.get("model"))
        if config.get("key_env"):
            env_reference(config["key_env"])
        if config.get("credential_name"):
            identifier(config["credential_name"], max_length=80)

    def generate(self, system, text, on_chunk, cancel):
        if cancel.is_set():
            raise ModelCancelled()
        quiet_sdk_logs()
        try:
            return asyncio.run(self._generate(system, text, on_chunk, cancel))
        except ModelError:
            raise
        except Exception:
            # Exceptions may include Authorization headers, URLs, and user text.
            raise ModelError("API_REQUEST_FAILED", "API 请求失败，请核对地址、模型、凭据和网络。") from None

    async def _generate(self, system, text, on_chunk, cancel):
        client = _new_client(api_key=_resolve_key(self.config), base_url=self.base_url,
                             timeout=300.0, max_retries=0)
        stream = None
        try:
            stream = await cancellable(client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                stream=True,
                # No tools/functions are registered, and no response is ever
                # dispatched to a local capability.
            ), cancel)
            chunks = []
            finish = None
            iterator = stream.__aiter__()
            while True:
                try:
                    item = await cancellable(iterator.__anext__(), cancel)
                except StopAsyncIteration:
                    break
                for choice in item.choices:
                    delta = choice.delta
                    if getattr(delta, "tool_calls", None) or getattr(delta, "function_call", None):
                        raise ModelError("TOOLS_DISABLED", "模型请求了工具；本面板拒绝执行。")
                    finish = choice.finish_reason or finish
                    content = getattr(delta, "content", None)
                    if content:
                        if not isinstance(content, str):
                            raise ModelError("MODEL_RESPONSE", "模型返回了不支持的内容。")
                        chunks.append(content)
                        on_chunk(content)
            if cancel.is_set():
                raise ModelCancelled()
            if finish == "length":
                raise ModelError("OUTPUT_TRUNCATED", "模型输出达到长度上限；本次整理未完成。")
            if finish not in ("stop",):
                raise ModelError("MODEL_INCOMPLETE", "模型未完整结束；本次整理未完成。")
            result = "".join(chunks)
            if not result.strip():
                raise ModelError("MODEL_EMPTY", "模型未返回整理结果。")
            return result
        finally:
            if stream is not None:
                try:
                    await stream.close()
                except Exception:
                    pass
            try:
                await client.close()
            except Exception:
                pass
