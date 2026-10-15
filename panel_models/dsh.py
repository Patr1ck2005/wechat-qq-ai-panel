"""DSH ACP adapter with a private home and a mandatory execution guard.

Only provider metadata and credential *references* are imported. This module
never opens DSH's credential document or talks to the desktop's private RPC.
"""

import asyncio
import contextlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import uuid

from .common import (ModelCancelled, ModelError, cancellable, env_reference,
                     identifier, quiet_sdk_logs, safe_base_url)

SUPPORTED_DSH_VERSIONS = {"0.2.0-rc.2"}
ACP_SDK_VERSION = "0.12.1"
RESOURCE_ROOT = Path(__file__).resolve().parent.parent / "resources" / "dsh"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROFILE_NAME = "wechat-qq-panel"

_BOOL_COMPAT = {
    "supportsStore", "supportsDeveloperRole", "supportsReasoningEffort",
    "supportsUsageInStreaming", "supportsFinishReason", "requiresToolResultName",
    "requiresAssistantAfterToolResult", "requiresThinkingAsText",
    "requiresReasoningContentOnAssistantMessages", "supportsThinkingTokenBudget",
    "supportsMaxOutputTokens", "supportsStrictMode", "supportsLongCacheRetention",
    "supportsEagerToolInputStreaming", "supportsCacheControlOnTools",
    "supportsTemperature", "forceAdaptiveThinking", "allowEmptySignature", "supportsStrictTools",
}


def _yaml_module():
    try:
        import yaml
        return yaml
    except ImportError:
        raise ModelError("MODEL_DEPENDENCY", "缺少 PyYAML，请重新运行安装程序。") from None


def _mapping(node):
    yaml = _yaml_module()
    if not isinstance(node, yaml.nodes.MappingNode):
        return {}
    return {key.value: value for key, value in node.value if isinstance(key, yaml.nodes.ScalarNode)}


def _scalar(node, default=None):
    yaml = _yaml_module()
    return node.value if isinstance(node, yaml.nodes.ScalarNode) and node.tag.endswith(":str") else default


def _number(node):
    yaml = _yaml_module()
    if isinstance(node, yaml.nodes.ScalarNode) and node.tag.endswith(":int"):
        try:
            n = int(node.value)
            return n if 0 < n < 2**53 else None
        except ValueError:
            pass
    return None


def _bool(node):
    yaml = _yaml_module()
    if isinstance(node, yaml.nodes.ScalarNode) and node.tag.endswith(":bool"):
        return node.value.lower() in ("true", "yes", "on")
    return None


def _sequence(node):
    yaml = _yaml_module()
    return node.value if isinstance(node, yaml.nodes.SequenceNode) else []


def _entries(node):
    """Inspect only loader rows, never execute YAML expression tags."""
    for row in _sequence(node):
        fields = _mapping(row)
        if "id" in fields:
            yield fields
        yield from _entries(fields.get("insert"))
        yield from _entries(fields.get("children"))


def _config_nodes(home):
    yaml = _yaml_module()
    configs = {}
    for path in (home / "profiles" / "desktop" / "cordis.patch.yml", home / "cordis.patch.yml"):
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ModelError("DSH_CONFIG", "DSH 配置文件过大。")
            # Compose an AST instead of constructing the document. Unknown
            # !!js tags are inert, and unselected values are never imported.
            node = yaml.compose(path.read_text(encoding="utf-8-sig"))
            for row in _entries(node):
                row_id = _scalar(row.get("id"))
                if row_id in {"llm-pi-ai", "llm-deepseek", "agent-default-model"} and "config" in row:
                    configs[row_id] = row["config"]
        except ModelError:
            raise
        except Exception:
            raise ModelError("DSH_CONFIG", "无法读取 DSH 的非机密模型配置。") from None
    return configs


def _safe_compat(node):
    out = {}
    for key, value in _mapping(node).items():
        if key in _BOOL_COMPAT:
            hit = _bool(value)
            if hit is not None:
                out[key] = hit
        elif key in {"maxTokensField", "thinkingFormat", "thinkingTokenBudgetField", "cacheControlFormat"}:
            hit = _scalar(value)
            if hit and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", hit):
                out[key] = hit
        elif key == "vllmPriority":
            hit = _number(value)
            if hit is not None:
                out[key] = hit
    return out


def _safe_model(node, *, model_id=None):
    fields = _mapping(node)
    out = {}
    mid = model_id or _scalar(fields.get("id"))
    if mid is not None:
        out["id"] = identifier(mid)
    for key in ("contextWindow", "maxTokens"):
        hit = _number(fields.get(key))
        if hit is not None:
            out[key] = hit
    name = _scalar(fields.get("name"))
    if name:
        out["name"] = identifier(name)
    inputs = [_scalar(x) for x in _sequence(fields.get("input"))]
    if inputs:
        if any(x not in ("text", "image") for x in inputs):
            raise ModelError("DSH_CONFIG", "DSH 模型输入类型不受支持。")
        out["input"] = inputs
    levels = fields.get("reasoningEfforts")
    if _bool(levels) is False:
        out["reasoningEfforts"] = False
    elif _mapping(levels):
        safe_levels = {}
        for key, value in _mapping(levels).items():
            if key not in ("off", "minimal", "low", "medium", "high", "xhigh"):
                continue
            if value.tag.endswith(":null"):
                safe_levels[key] = None
            else:
                hit = _scalar(value)
                if hit is not None:
                    safe_levels[key] = identifier(hit, max_length=80)
        out["reasoningEfforts"] = safe_levels
    compat = _safe_compat(fields.get("compat"))
    if compat:
        out["compat"] = compat
    return out


def _selected_provider(home, provider, model):
    nodes = _config_nodes(home)
    selected = _mapping(nodes.get("agent-default-model"))
    provider = identifier(provider or _scalar(selected.get("provider")), code="DSH_ROUTE")
    model = identifier(model or _scalar(selected.get("model")), code="DSH_ROUTE")
    if provider == "deepseek-official":
        fields = _mapping(nodes.get("llm-deepseek"))
        ref = _scalar(fields.get("apiKeyEnv"), "DEEPSEEK_API_KEY")
        safe = {"apiKeyEnv": env_reference(ref)}
        base = _scalar(fields.get("baseURL"))
        if base:
            safe["baseURL"] = safe_base_url(base)
        for key in ("thinking", "reasoningEffort"):
            value = _scalar(fields.get(key))
            if value:
                safe[key] = identifier(value)
        for key in ("maxTokens", "defaultContextWindow", "streamIdleTimeoutMs"):
            value = _number(fields.get(key))
            if value is not None:
                safe[key] = value
        return provider, model, {"native": safe}
    providers = _mapping(_mapping(nodes.get("llm-pi-ai")).get("providers"))
    fields = _mapping(providers.get(provider))
    if not fields:
        raise ModelError("DSH_ROUTE", "所选 DSH 路由不在现有桌面模型配置中。")
    # Inline keys and auth headers are intentionally excluded. A selected route
    # must name a credential reference; pi-ai's ambient discovery is disabled.
    ref = _scalar(fields.get("apiKeyEnv"))
    if not ref:
        raise ModelError("DSH_CREDENTIAL_REFERENCE", "该 DSH 路由缺少 apiKeyEnv 凭据引用。")
    if _mapping(fields.get("headers")):
        raise ModelError("DSH_HEADERS", "该 DSH 路由包含自定义请求头，面板不自动导入；请使用独立 API 配置。")
    out = {"apiKeyEnv": env_reference(ref)}
    for key in ("displayName", "api", "reasoning", "cacheRetention", "transport"):
        value = _scalar(fields.get(key))
        if value:
            out[key] = identifier(value)
    base = _scalar(fields.get("baseURL"))
    if base:
        out["baseURL"] = safe_base_url(base)
    for key in ("defaultContextWindow", "defaultMaxTokens", "timeoutMs", "streamIdleTimeoutMs"):
        value = _number(fields.get(key))
        if value is not None:
            out[key] = value
    models = [_safe_model(x) for x in _sequence(fields.get("models"))]
    if models:
        if any("id" not in x for x in models):
            raise ModelError("DSH_CONFIG", "DSH 模型列表缺少稳定模型 ID。")
        out["models"] = models
    overrides = {key: _safe_model(value) for key, value in _mapping(fields.get("modelOverrides")).items()}
    for value in overrides.values():
        value.pop("id", None)
    if overrides:
        out["modelOverrides"] = overrides
    compat = _safe_compat(fields.get("compat"))
    if compat:
        out["compat"] = compat
    return provider, model, {"pi": {provider: out}}


def _find_executable():
    candidates = []
    # Windows App Paths and installer metadata avoid machine-specific literals.
    if os.name == "nt":
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\App Paths\DeepSeek Harness.exe") as key:
                        candidates.append(winreg.QueryValue(key, None))
                except OSError:
                    pass
                for uninstall in (r"Software\Microsoft\Windows\CurrentVersion\Uninstall", r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                    try:
                        with winreg.OpenKey(hive, uninstall) as key:
                            for i in range(winreg.QueryInfoKey(key)[0]):
                                with winreg.OpenKey(key, winreg.EnumKey(key, i)) as item:
                                    try:
                                        if "DeepSeek Harness" in str(winreg.QueryValueEx(item, "DisplayName")[0]):
                                            location = winreg.QueryValueEx(item, "InstallLocation")[0]
                                            candidates.append(str(Path(location) / "DeepSeek Harness.exe"))
                                    except OSError:
                                        pass
                    except OSError:
                        pass
        except ImportError:
            pass
    for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(env)
        if value:
            candidates.extend(str(Path(value) / tail / "DeepSeek Harness.exe") for tail in ("DeepSeek Harness", "Programs/DeepSeek Harness"))
    candidates.append(shutil.which("dsh") or "")
    return next((str(Path(x)) for x in candidates if x and Path(x).is_file()), "")


def discover_dsh():
    """Return only safe local metadata; never boot DSH or inspect credentials."""
    home = Path(os.environ.get("DSH_HOME") or Path.home() / ".dsh")
    result = {"executable": _find_executable(), "home": str(home), "provider": "", "model": "", "providers": []}
    try:
        nodes = _config_nodes(home)
        selected = _mapping(nodes.get("agent-default-model"))
        result["provider"] = _scalar(selected.get("provider"), "")
        result["model"] = _scalar(selected.get("model"), "")
        routes = _mapping(_mapping(nodes.get("llm-pi-ai")).get("providers"))
        for provider, node in routes.items():
            fields = _mapping(node)
            result["providers"].append({"provider": provider, "models": [
                _scalar(_mapping(x).get("id"), "") for x in _sequence(fields.get("models"))
            ]})
    except ModelError:
        result["warning"] = "DSH_CONFIG"
    return result


def _command(executable):
    path = Path(executable)
    env = os.environ.copy()
    if not path.is_file():
        hit = shutil.which(executable)
        if not hit:
            raise ModelError("DSH_EXECUTABLE", "找不到 DSH 启动程序，请在设置中选择。")
        path = Path(hit)
    if path.suffix.lower() == ".cmd":
        # The official desktop shim is a batch file. Bypass cmd.exe entirely to
        # keep paths and subsequent arguments free of shell interpretation.
        for directory in path.parents:
            desktop = directory / "DeepSeek Harness.exe"
            if desktop.is_file() and (directory / "resources" / "app.asar").is_file():
                path = desktop
                break
        else:
            # npm's ordinary dsh.cmd has a fixed adjacent JS bin and node.exe.
            entry = path.parent / "node_modules" / "@deepseek-ai" / "dsh" / "lib" / "bin.js"
            node = path.parent / "node.exe"
            node_exe = str(node) if node.is_file() else shutil.which("node")
            if not entry.is_file() or not node_exe:
                raise ModelError("DSH_EXECUTABLE", "仅支持官方 DSH 桌面启动器或原生 CLI。")
            return [node_exe, str(entry)], env
    if path.name.lower() == "deepseek harness.exe":
        archive = path.parent / "resources" / "app.asar"
        if not archive.is_file():
            raise ModelError("DSH_EXECUTABLE", "DSH 桌面运行时不完整。")
        env["ELECTRON_RUN_AS_NODE"] = "1"
        entry = archive / "dsh" / "node_modules" / "@deepseek-ai" / "dsh-desktop-host" / "lib" / "cli.js"
        return [str(path), "--expose-internals", str(entry)], env
    # POSIX npm entry points are normally symlinks to the JS bin. Resolve the
    # symlink and invoke Node directly so the sanitized bootstrap can be used.
    resolved = path.resolve()
    if resolved.suffix.lower() in (".js", ".mjs") and shutil.which("node"):
        return [shutil.which("node"), str(resolved)], env
    return [str(path)], env


def _probe_version(command, env):
    try:
        result = subprocess.run([*command, "--version"], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=15, creationflags=CREATE_NO_WINDOW,
                                check=False)
        version = result.stdout.decode("utf-8", errors="replace").strip()
    except Exception:
        raise ModelError("DSH_VERSION", "无法检查 DSH 版本。") from None
    if result.returncode or version not in SUPPORTED_DSH_VERSIONS:
        raise ModelError("DSH_VERSION", "此 DSH 版本尚未验证工具隔离；请使用已支持版本 0.2.0-rc.2。")
    return version


def _require_sdk():
    try:
        if importlib.metadata.version("agent-client-protocol") != ACP_SDK_VERSION:
            raise ValueError()
        import acp
        return acp
    except Exception:
        raise ModelError("MODEL_DEPENDENCY", "请安装 agent-client-protocol==0.12.1。") from None


def _guarded_command(command):
    """Use official profile boot without CLI's raw startup-report writer."""
    if len(command) == 3 and command[1] == "--expose-internals":
        entry = Path(command[2])
        prefix = command[:2]
    elif len(command) == 2 and Path(command[1]).suffix.lower() in (".js", ".mjs"):
        entry = Path(command[1])
        prefix = command[:1]
    else:
        raise ModelError("DSH_EXECUTABLE", "无法定位官方 DSH 模块；请选用桌面启动器或 npm 原生 CLI。")
    if len(entry.parents) < 3 or entry.parents[2].name != "@deepseek-ai":
        raise ModelError("DSH_EXECUTABLE", "DSH 模块布局不受支持。")
    resource = RESOURCE_ROOT / "launch.mjs"
    if not resource.is_file():
        raise ModelError("DSH_GUARD", "DSH 安全启动组件缺失。")
    return [*prefix, str(resource), str(entry.parents[2])]


def _profile_patches(provider, model, imported, private_root, system, nonce):
    # No desktop/home patch is copied. Unknown future tools are still caught by
    # the global monotonic execution guard, even when not listed here.
    disabled = {
        "agent-instructions", "skill", "skill-filesystem", "skill-badge", "tool-skill",
        "mcp-resources", "plan-mode", "session-title-llm", "session-projection-cache",
        "session-telemetry-otel", "plugin-manager", "config-editor", "settings", "hmr",
        "tool-plugin-manager", "tool-bash", "tool-pwsh", "tool-jobs", "tool-fs", "tool-fs-search",
        "tool-subagent-control", "tool-subagent-list-agents", "tool-subagent", "tool-subagent-fork",
        "tool-workflow", "tool-todo", "tool-goal", "tool-ralph", "tool-web", "ptc-runtime",
        "workflow-ptc", "subagent-spawn-in-process", "subagent-fork-in-process", "subagent",
        "web", "web-search-deepseek", "web-fetch-http", "deepseek-account", "llm-deepseek-account",
        "shell-env", "goal-round-driver", "command-goal", "command-feedback", "command-compact",
    }
    rows = [{"id": x, "disabled": True} for x in sorted(disabled)]
    rows.extend([
        {"id": "tools", "config": {"mode": "native"}},
        {"id": "system-prompt", "config": {"personaPrefix": system, "personaSuffix": ""}},
        {"id": "agent-loop", "config": {"agents": []}},
        {"id": "agent-default-model", "config": {"provider": provider, "model": model}},
        {"id": "session-persistence-jsonl", "config": {"root": str(private_root / "dsh" / "sessions")}},
        {"id": "session-query-sqlite", "config": {"path": ":memory:", "openAt": "never"}},
        {"id": "storage-json", "config": {"root": str(private_root / "dsh" / "runtime-home" / "storages")}},
        {"id": "acp", "inject": ["acpAppStartup", "panelNoTools"], "config": {"provider": provider, "model": model}},
        {"insert": [{"id": "panel-no-tools", "name": "./panel-no-tools.mjs", "config": {
            "nonce": nonce, "readyPath": str(private_root / "dsh" / "runtime-home" / "guard-ready.json"),
        }}]},
    ])
    if "pi" in imported:
        rows.append({"id": "llm-pi-ai", "config": {"providers": imported["pi"]}})
        rows.append({"id": "llm-deepseek", "disabled": True})
    else:
        rows.append({"id": "llm-pi-ai", "disabled": True})
        rows.append({"id": "llm-deepseek", "config": imported["native"]})
    return rows


class DshModel:
    def __init__(self, config, private_root):
        if not isinstance(config, dict) or set(config) - {"executable", "home", "provider", "model"}:
            raise ModelError("MODEL_CONFIG", "DSH 配置只能保存启动路径、配置目录和模型选择。")
        self.config = dict(config)
        self.private_root = Path(private_root).resolve()
        self.lock = threading.Lock()

    def _prepare(self, system):
        acp = _require_sdk()
        source_home = Path(self.config.get("home") or os.environ.get("DSH_HOME") or Path.home() / ".dsh").expanduser().resolve()
        provider, model, imported = _selected_provider(source_home, self.config.get("provider"), self.config.get("model"))
        executable = self.config.get("executable") or _find_executable()
        command, env = _command(identifier(executable, max_length=32767))
        version = _probe_version(command, env)
        resource = RESOURCE_ROOT / "no-tools.mjs"
        if not resource.is_file():
            raise ModelError("DSH_GUARD", "工具隔离组件缺失，DSH 未启动。")
        command = _guarded_command(command)
        runtime_home = self.private_root / "dsh" / "runtime-home"
        profile = runtime_home / "profiles" / PROFILE_NAME
        profile.mkdir(parents=True, exist_ok=True)
        workspace = self.private_root / "dsh" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        nonce = uuid.uuid4().hex
        patches = _profile_patches(provider, model, imported, self.private_root, system, nonce)
        patches.append({"id": "credentials", "config": {
            # DSH alone reads this document. The adapter never reads, copies,
            # exports, prints, or serializes its contents.
            "path": str(source_home / ".credentials.yaml"), "watch": False,
        }})
        manifest = {"name": "wechat-qq-panel-private-profile", "private": True,
                    "dependencies": {}, "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-acp-app"]}}}
        (profile / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
        (profile / "cordis.yml").write_text("[]\n", encoding="utf-8")
        (profile / "cordis.patch.yml").write_text(_yaml_module().safe_dump(patches, allow_unicode=True, sort_keys=False), encoding="utf-8")
        (profile / "panel-no-tools.mjs").write_bytes(resource.read_bytes())
        env.update({"DSH_HOME": str(runtime_home), "DSH_TELEMETRY_DISABLED": "1"})
        env.pop("DSH_TELEMETRY_OTLP_URL", None)
        return acp, command, env, workspace, nonce, version

    @staticmethod
    def _check_ready(private_root, nonce):
        try:
            data = json.loads((private_root / "dsh" / "runtime-home" / "guard-ready.json").read_text(encoding="utf-8"))
            if data != {"guardVersion": 1, "nonce": nonce, "toolsDisabled": True}:
                raise ValueError()
        except Exception:
            raise ModelError("DSH_GUARD", "DSH 未确认执行层工具隔离，本次任务已拒绝。") from None

    def generate(self, system, text, on_chunk, cancel):
        if cancel.is_set():
            raise ModelCancelled()
        if not self.lock.acquire(blocking=False):
            raise ModelError("MODEL_BUSY", "DSH 正在执行另一项面板任务。")
        quiet_sdk_logs()
        try:
            prepared = self._prepare(system)
            return asyncio.run(self._generate(prepared, text, on_chunk, cancel))
        except ModelError:
            raise
        except Exception:
            raise ModelError("DSH_REQUEST_FAILED", "DSH 请求失败，请核对已配置的路由、凭据引用和网络。") from None
        finally:
            self.lock.release()

    async def _generate(self, prepared, text, on_chunk, cancel):
        acp, command, env, workspace, nonce, _version = prepared
        schema = acp.schema
        chunks = []

        class NoToolsClient(acp.Client):
            violation = False

            async def request_permission(self, **kwargs):
                # No "allow once" path exists in this client.
                self.violation = True
                raise acp.RequestError.method_not_found("session/request_permission")

            async def session_update(self, session_id, update, **kwargs):
                kind = getattr(update, "session_update", "")
                if kind in ("tool_call", "tool_call_update"):
                    self.violation = True
                if kind == "agent_message_chunk":
                    content = getattr(update, "content", None)
                    if getattr(content, "type", None) == "text":
                        value = content.text
                        chunks.append(value)
                        if not cancel.is_set():
                            on_chunk(value)

            async def ext_method(self, method, params):
                raise acp.RequestError.method_not_found(method)

            async def ext_notification(self, method, params):
                return None

            async def read_text_file(self, **kwargs):
                self.violation = True
                raise acp.RequestError.method_not_found("fs/read_text_file")

            async def write_text_file(self, **kwargs):
                self.violation = True
                raise acp.RequestError.method_not_found("fs/write_text_file")

            async def create_terminal(self, **kwargs):
                self.violation = True
                raise acp.RequestError.method_not_found("terminal/create")

            async def terminal_output(self, **kwargs):
                raise acp.RequestError.method_not_found("terminal/output")

            async def release_terminal(self, **kwargs):
                raise acp.RequestError.method_not_found("terminal/release")

            async def wait_for_terminal_exit(self, **kwargs):
                raise acp.RequestError.method_not_found("terminal/wait_for_exit")

            async def kill_terminal(self, **kwargs):
                raise acp.RequestError.method_not_found("terminal/kill")

        process = None
        conn = None
        session_id = None
        client = NoToolsClient()
        try:
            process = await asyncio.create_subprocess_exec(
                *command, "--profile", PROFILE_NAME, env=env, cwd=str(workspace),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW,
            )
            conn = acp.connect_to_agent(client, process.stdin, process.stdout)
            try:
                await asyncio.wait_for(cancellable(conn.initialize(
                    protocol_version=acp.PROTOCOL_VERSION,
                    client_capabilities=schema.ClientCapabilities(),
                    client_info=schema.Implementation(name="wechat-qq-ai-panel", version="0.1.0"),
                ), cancel), timeout=40)
                self._check_ready(self.private_root, nonce)
            except ModelCancelled:
                raise
            except Exception:
                raise ModelError("DSH_GUARD", "DSH 启动或工具隔离检查未通过；没有发送消息内容。") from None
            session = await asyncio.wait_for(cancellable(conn.new_session(mcp_servers=[], cwd=str(workspace)), cancel), timeout=40)
            session_id = session.session_id
            # Check again immediately before admitting any message body.
            self._check_ready(self.private_root, nonce)
            prompt_task = asyncio.create_task(conn.prompt(
                session_id=session_id, prompt=[schema.TextContentBlock(type="text", text=text)],
            ))
            while not prompt_task.done():
                if cancel.is_set() or client.violation:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(conn.cancel(session_id=session_id), timeout=2)
                    prompt_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await prompt_task
                    if client.violation:
                        raise ModelError("TOOLS_DISABLED", "模型请求了工具；本面板拒绝执行。")
                    raise ModelCancelled()
                await asyncio.wait({prompt_task}, timeout=0.05)
            response = await prompt_task
            if cancel.is_set():
                raise ModelCancelled()
            if client.violation:
                raise ModelError("TOOLS_DISABLED", "模型请求了工具；本面板拒绝执行。")
            stop = getattr(response, "stop_reason", None)
            if stop != "end_turn":
                raise ModelError("MODEL_INCOMPLETE", "DSH 未完整结束，本次整理未完成。")
            result = "".join(chunks)
            if not result.strip():
                raise ModelError("MODEL_EMPTY", "DSH 未返回整理结果。")
            return result
        finally:
            if conn is not None and session_id:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conn.close_session(session_id=session_id), timeout=2)
            if conn is not None:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(conn.close(), timeout=2)
            if process is not None:
                if process.stdin:
                    process.stdin.close()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    if process.returncode is None:
                        process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
