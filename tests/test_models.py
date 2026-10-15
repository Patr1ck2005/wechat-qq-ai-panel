"""Synthetic-only model boundary tests. No real credentials or providers."""

import asyncio
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from panel_fixtures import RecycleFixture
import threading
import time
import types
import unittest
from unittest.mock import patch

from panel_models import ApiModel, DshModel, ModelCancelled, ModelError, create_model
from panel_models import api, dsh


def chunk(text=None, *, finish=None, tools=None):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(
        delta=types.SimpleNamespace(content=text, tool_calls=tools, function_call=None), finish_reason=finish,
    )])


class FakeStream:
    def __init__(self, items, *, wait=False):
        self.items = iter(items)
        self.wait = wait
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.wait:
            await asyncio.sleep(30)
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration()

    async def close(self):
        self.closed = True


class FakeApi:
    def __init__(self, stream):
        self.stream = stream
        self.calls = []
        self.closed = False
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream

    async def close(self):
        self.closed = True


class ApiTests(unittest.TestCase):
    def model(self):
        return ApiModel({"base_url": "https://example.invalid/v1", "model": "synthetic-model", "key_env": "PANEL_SYNTHETIC_KEY"})

    def run_model(self, client, cancel=None, callback=None):
        seen = []
        with patch.dict(os.environ, {"PANEL_SYNTHETIC_KEY": "SYNTHETIC-SECRET"}), patch.object(api, "_new_client", return_value=client) as factory:
            result = self.model().generate("Summarize", "Synthetic message", callback or seen.append, cancel or threading.Event())
        return result, seen, factory

    def test_stream_and_explicit_route_without_tools(self):
        client = FakeApi(FakeStream([chunk("Hello "), chunk("world"), chunk(finish="stop")]))
        result, seen, factory = self.run_model(client)
        self.assertEqual(result, "Hello world")
        self.assertEqual(seen, ["Hello ", "world"])
        self.assertEqual(factory.call_args.kwargs["base_url"], "https://example.invalid/v1")
        self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
        self.assertNotIn("tools", client.calls[0])
        self.assertNotIn("functions", client.calls[0])
        self.assertTrue(client.closed and client.stream.closed)

    def test_unsolicited_tool_request_cannot_execute(self):
        client = FakeApi(FakeStream([chunk(tools=[{"name": "read_private_db"}])]))
        executed = []
        with self.assertRaises(ModelError) as error:
            self.run_model(client, callback=executed.append)
        self.assertEqual(error.exception.code, "TOOLS_DISABLED")
        self.assertEqual(executed, [])
        self.assertTrue(client.closed and client.stream.closed)

    def test_incomplete_output_is_not_success(self):
        for finish in ("length", "content_filter", None):
            with self.subTest(finish=finish), self.assertRaises(ModelError):
                self.run_model(FakeApi(FakeStream([chunk("partial", finish=finish)])))

    def test_cancel_interrupts_silent_stream(self):
        client = FakeApi(FakeStream([], wait=True))
        cancel = threading.Event()
        timer = threading.Timer(0.1, cancel.set)
        started = time.monotonic()
        timer.start()
        try:
            with self.assertRaises(ModelCancelled):
                self.run_model(client, cancel)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(client.closed and client.stream.closed)

    def test_pre_cancel_does_not_resolve_credentials(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(api, "_resolve_key") as resolve, self.assertRaises(ModelCancelled):
            self.model().generate("s", "t", lambda _: None, cancel)
        resolve.assert_not_called()

    def test_secret_and_message_are_absent_from_error(self):
        async def broken(**kwargs):
            raise RuntimeError("Authorization: SYNTHETIC-SECRET; message=Synthetic message")
        client = FakeApi(FakeStream([]))
        client.chat.completions.create = broken
        with self.assertRaises(ModelError) as error:
            self.run_model(client)
        self.assertEqual(error.exception.code, "API_REQUEST_FAILED")
        self.assertNotIn("SYNTHETIC-SECRET", str(error.exception))
        self.assertNotIn("Synthetic message", str(error.exception))
        self.assertTrue(error.exception.__suppress_context__)

    def test_env_and_windows_credential_reference(self):
        backend = types.SimpleNamespace(get_password=lambda service, name: "synthetic-value")
        with patch.object(api, "_credential_backend", return_value=backend):
            self.assertEqual(api._resolve_key({"credential_name": "my-api"}), "synthetic-value")
        with patch.dict(os.environ, {"PANEL_SYNTHETIC_KEY": "synthetic-env"}), patch.object(api, "_credential_backend") as vault:
            self.assertEqual(api._resolve_key({"key_env": "PANEL_SYNTHETIC_KEY", "credential_name": "my-api"}), "synthetic-env")
            vault.assert_not_called()

    def test_key_write_is_only_to_explicit_credential_backend(self):
        stored = []
        backend = types.SimpleNamespace(set_password=lambda *x: stored.append(x), delete_password=lambda *x: stored.append(x))
        with patch.object(api, "_credential_backend", return_value=backend):
            api.store_api_key("test", "synthetic-key")
            api.delete_api_key("test")
        self.assertEqual(stored, [(api.SERVICE_NAME, "test", "synthetic-key"), (api.SERVICE_NAME, "test")])

    def test_keyring_raw_exception_is_redacted(self):
        def fail(*args):
            raise RuntimeError("synthetic-key")
        backend = types.SimpleNamespace(set_password=fail)
        with patch.object(api, "_credential_backend", return_value=backend), self.assertRaises(ModelError) as error:
            api.store_api_key("test", "synthetic-key")
        self.assertNotIn("synthetic-key", str(error.exception))

    def test_plaintext_key_config_and_credential_url_are_rejected(self):
        bad_configs = [
            {"model": "x", "api_key": "synthetic"},
            {"model": "x", "base_url": "https://user:synthetic@example.invalid/v1"},
            {"model": "x", "base_url": "https://example.invalid/v1?key=synthetic"},
            {"model": "x", "base_url": "http://example.invalid/v1"},
            {"model": "x", "base_url": "https://[malformed"},
            {"model": "x", "key_env": "SECRET=value"},
        ]
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(ModelError):
                ApiModel(config)
        ApiModel({"model": "x", "base_url": "http://127.0.0.1:8080/v1"})

    @unittest.skipUnless(importlib.util.find_spec("openai"), "official OpenAI SDK not installed")
    def test_official_sdk_against_loopback_synthetic_sse(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for value in ["Synthetic ", "SDK summary", None]:
                    item = {"id": "synthetic", "object": "chat.completion.chunk", "created": 1, "model": "exact-id", "choices": [{
                        "index": 0, "delta": {"content": value} if value else {}, "finish_reason": "stop" if value is None else None,
                    }]}
                    self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                    self.wfile.flush()
                self.wfile.write(b"data: [DONE]\n\n")

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            model = ApiModel({"base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "exact-id", "key_env": "PANEL_SYNTHETIC_KEY"})
            with patch.dict(os.environ, {"PANEL_SYNTHETIC_KEY": "SYNTHETIC-NOT-A-REAL-KEY", "NO_PROXY": "127.0.0.1"}):
                result = model.generate("Synthetic system", "Synthetic message only", lambda _: None, threading.Event())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertEqual(result, "Synthetic SDK summary")
        self.assertEqual(requests[0]["model"], "exact-id")
        self.assertNotIn("tools", requests[0])
        self.assertNotIn("SYNTHETIC-NOT-A-REAL-KEY", json.dumps(requests))


class DshConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = RecycleFixture()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "original-dsh"
        self.profile = self.home / "profiles" / "desktop"
        self.profile.mkdir(parents=True)
        self.source = self.profile / "cordis.patch.yml"
        self.source.write_text("""- id: agent-default-model
  config: {provider: synthetic, model: exact-id}
- id: llm-pi-ai
  config:
    providers:
      synthetic:
        apiKeyEnv: PANEL_ONLY_REFERENCE
        api: openai-completions
        baseURL: https://example.invalid/v1
        ignoredSecret: SYNTHETIC-SECRET-MUST-NOT-IMPORT
        models:
          - {id: exact-id, contextWindow: 10000, maxTokens: 1000, input: [text]}
      another-provider:
        apiKeyEnv: OTHER_REFERENCE
        apiKey: ANOTHER-SYNTHETIC-SECRET
- id: arbitrary-plugin
  config: {danger: !!js 'throw new Error("must never execute")'}
""", encoding="utf-8")

    def test_only_selected_provider_and_whitelist_are_imported(self):
        provider, model, data = dsh._selected_provider(self.home, "", "")
        self.assertEqual((provider, model), ("synthetic", "exact-id"))
        self.assertEqual(list(data["pi"]), ["synthetic"])
        serialized = json.dumps(data)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("ignoredSecret", serialized)
        self.assertNotIn("another-provider", serialized)
        self.assertIn("PANEL_ONLY_REFERENCE", serialized)
        self.assertIn("exact-id", serialized)

    def test_missing_route_or_reference_fails_without_fallback(self):
        with self.assertRaises(ModelError):
            dsh._selected_provider(self.home, "missing-route", "exact-id")
        self.source.write_text("- id: llm-pi-ai\n  config:\n    providers:\n      inline: {apiKey: SYNTHETIC-SECRET}\n", encoding="utf-8")
        with self.assertRaises(ModelError) as error:
            dsh._selected_provider(self.home, "inline", "m")
        self.assertEqual(error.exception.code, "DSH_CREDENTIAL_REFERENCE")

    def test_custom_headers_are_not_imported(self):
        original = self.source.read_text(encoding="utf-8")
        self.source.write_text(original.replace("ignoredSecret:", "headers: {Authorization: 'Bearer SYNTHETIC'}\n        ignoredSecret:"), encoding="utf-8")
        with self.assertRaises(ModelError) as error:
            dsh._selected_provider(self.home, "", "")
        self.assertEqual(error.exception.code, "DSH_HEADERS")

    def test_profile_restricts_all_surfaces_and_private_paths(self):
        rows = dsh._profile_patches("synthetic", "m", {"pi": {"synthetic": {"apiKeyEnv": "REF"}}}, self.root, "safe system", "a" * 32)
        by_id = {x["id"]: x for x in rows if "id" in x}
        for name in ("agent-instructions", "skill-filesystem", "skill", "tool-skill", "mcp-resources", "plan-mode", "session-projection-cache"):
            self.assertTrue(by_id[name]["disabled"])
        self.assertIn("panelNoTools", by_id["acp"]["inject"])
        self.assertEqual(by_id["tools"]["config"], {"mode": "native"})
        self.assertEqual(by_id["session-query-sqlite"]["config"], {"path": ":memory:", "openAt": "never"})
        self.assertEqual(by_id["session-persistence-jsonl"]["config"]["root"], str(self.root / "dsh" / "sessions"))

    def test_fresh_nonce_required_for_readiness(self):
        runtime = self.root / "dsh" / "runtime-home"
        runtime.mkdir(parents=True)
        ready = runtime / "guard-ready.json"
        for data in (None, {"guardVersion": 1, "nonce": "old", "toolsDisabled": True},
                     {"guardVersion": 1, "nonce": "new", "toolsDisabled": False}):
            if data is not None:
                ready.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ModelError) as error:
                DshModel._check_ready(self.root, "new")
            self.assertEqual(error.exception.code, "DSH_GUARD")
        ready.write_text(json.dumps({"guardVersion": 1, "nonce": "new", "toolsDisabled": True}), encoding="utf-8")
        DshModel._check_ready(self.root, "new")

    def test_prepare_has_no_desktop_or_credentials_mutation(self):
        before = self.source.read_bytes()
        model = DshModel({"home": str(self.home), "executable": "synthetic.exe"}, self.root / "panel")
        with patch.object(dsh, "_require_sdk", return_value=object()), patch.object(dsh, "_command", return_value=(["synthetic"], {})), patch.object(dsh, "_probe_version", return_value="0.2.0-rc.2"), patch.object(dsh, "_guarded_command", return_value=["synthetic"]):
            prepared = model._prepare("Preset only")
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.home / ".credentials.yaml").exists())
        self.assertEqual(prepared[2]["DSH_HOME"], str(self.root / "panel" / "dsh" / "runtime-home"))
        document = (self.root / "panel" / "dsh" / "runtime-home" / "profiles" / dsh.PROFILE_NAME / "cordis.patch.yml").read_text(encoding="utf-8")
        self.assertNotIn("SYNTHETIC-SECRET", document)
        self.assertIn(".credentials.yaml", document)

    def test_missing_guard_prevents_boot(self):
        model = DshModel({"home": str(self.home), "executable": "synthetic.exe"}, self.root / "panel")
        with patch.object(dsh, "_require_sdk", return_value=object()), patch.object(dsh, "_command", return_value=(["synthetic"], {})), patch.object(dsh, "_probe_version", return_value="0.2.0-rc.2"), patch.object(dsh, "RESOURCE_ROOT", self.root / "missing"):
            with self.assertRaises(ModelError) as error:
                model._prepare("s")
        self.assertEqual(error.exception.code, "DSH_GUARD")

    def test_unsupported_version_refuses(self):
        result = types.SimpleNamespace(returncode=0, stdout=b"999.0.0\n")
        with patch.object(subprocess, "run", return_value=result), self.assertRaises(ModelError) as error:
            dsh._probe_version(["fake"], {})
        self.assertEqual(error.exception.code, "DSH_VERSION")

    def test_factory_rejects_unknown_provider(self):
        with self.assertRaises(ModelError):
            create_model({"backend": "auto-fallback"}, self.root)


class GuardPluginTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js not available")
    def test_guard_rejects_malicious_tool_and_missing_guard(self):
        # Dynamic import is needed because environment values are not import
        # specifier literals. No DSH or model provider is started by this test.
        script = r"""
const { apply } = await import(process.env.PANEL_GUARD_IMPORT);
let guard, created, restricted, ready = false, executions = 0;
const tools = {guard: fn => { guard = fn; return () => {}; }, restrict: () => {}};
const ctx = {tools, on: (name, fn) => {created = fn}, provide: name => {ready = name === 'panelNoTools'}};
apply(ctx, {nonce: 'a'.repeat(32), readyPath: process.env.PANEL_GUARD_READY});
created({agent: {ctx: {tools: {...tools, restrict: x => {restricted = x}}}}});
const malicious = {name: 'read_private_database', arguments: {path: 'forbidden'}};
if (guard(malicious) === undefined) executions++;
if (!ready || executions !== 0 || restricted.allow.length !== 0) throw Error('guard failed');
let rejected = false;
try {apply({tools: {restrict(){}}, on(){}, provide(){}}, {nonce:'a'.repeat(32),readyPath:process.env.PANEL_GUARD_READY})}
catch {rejected = true}
if (!rejected) throw Error('missing guard accepted');
console.log(JSON.stringify({executions,ready,rejected}));
"""
        with RecycleFixture() as folder:
            env = os.environ.copy()
            env.update({"PANEL_GUARD_IMPORT": (dsh.RESOURCE_ROOT / "no-tools.mjs").as_uri(), "PANEL_GUARD_READY": str(Path(folder) / "ready.json")})
            result = subprocess.run([shutil.which("node"), "--input-type=module", "-e", script], env=env,
                                    capture_output=True, timeout=15, creationflags=dsh.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        self.assertEqual(json.loads(result.stdout), {"executions": 0, "ready": True, "rejected": True})


FAKE_ACP = r"""
import json, sys
def send(v):
 print(json.dumps(v), flush=True)
for line in sys.stdin:
 req=json.loads(line); method=req.get('method'); rid=req.get('id')
 if method=='initialize':
  send({'jsonrpc':'2.0','id':rid,'result':{'protocolVersion':1,'agentCapabilities':{},'agentInfo':{'name':'synthetic','version':'1'}}})
 elif method=='session/new':
  send({'jsonrpc':'2.0','id':rid,'result':{'sessionId':'synthetic'}})
 elif method=='session/prompt':
  send({'jsonrpc':'2.0','method':'session/update','params':{'sessionId':'synthetic','update':{'sessionUpdate':'agent_message_chunk','content':{'type':'text','text':'Synthetic summary'}}}})
  send({'jsonrpc':'2.0','id':rid,'result':{'stopReason':'end_turn'}})
 elif rid is not None:
  send({'jsonrpc':'2.0','id':rid,'result':{}})
"""


class AcpSmokeTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("acp"), "official ACP SDK not installed")
    def test_actual_sdk_synthetic_stdio_without_provider(self):
        acp = dsh._require_sdk()
        with RecycleFixture() as folder:
            root = Path(folder)
            (root / "dsh" / "runtime-home").mkdir(parents=True)
            (root / "dsh" / "runtime-home" / "guard-ready.json").write_text(json.dumps({"guardVersion": 1, "nonce": "synthetic-nonce", "toolsDisabled": True}), encoding="utf-8")
            model = DshModel({}, root)
            seen = []
            prepared = (acp, [sys.executable, "-u", "-c", FAKE_ACP], os.environ.copy(), root, "synthetic-nonce", "synthetic")
            result = asyncio.run(model._generate(prepared, "Synthetic messages only", seen.append, threading.Event()))
            self.assertEqual(result, "Synthetic summary")
            self.assertEqual(seen, ["Synthetic summary"])

    @unittest.skipUnless(importlib.util.find_spec("acp"), "official ACP SDK not installed")
    def test_no_prompt_admitted_without_guard_readiness(self):
        acp = dsh._require_sdk()
        with RecycleFixture() as folder:
            root = Path(folder)
            model = DshModel({}, root)
            prepared = (acp, [sys.executable, "-u", "-c", FAKE_ACP], os.environ.copy(), root, "nonce", "synthetic")
            with self.assertRaises(ModelError) as error:
                asyncio.run(model._generate(prepared, "private body must not be sent", lambda _: None, threading.Event()))
            self.assertEqual(error.exception.code, "DSH_GUARD")


if __name__ == "__main__":
    unittest.main()
