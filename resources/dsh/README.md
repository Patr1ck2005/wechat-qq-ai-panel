# DSH text-only execution profile

The panel uses the official `agent-client-protocol==0.12.1` Python SDK over
stdio, with DSH `0.2.0-rc.2`. Unsupported versions fail closed until tested.

`no-tools.mjs` installs the official monotonic `ctx.tools.guard` execution
denial and an empty per-agent inherited tool allowlist. The ACP row requires
its `panelNoTools` service. A fresh per-run nonce confirms readiness before
any message content is admitted. ACP client filesystem, terminal and permission
requests also have no approval or execution implementation.

Runtime configuration is generated under the panel's private `dsh/runtime-home`
directory. It imports only the selected provider's whitelisted model metadata
and `apiKeyEnv` reference from the existing desktop profile. Custom request
headers and inline credentials are not imported. DSH's official credentials
service references the original `.credentials.yaml` path; Python never opens,
copies or serializes that document. The desktop profile and default selection
are never edited. A new isolated `DSH_HOME` avoids inherited global plugins,
desktop history and global startup diagnostics. Session logs use the sibling
private `dsh/sessions` directory and remain visible to the panel's disk controls.
`launch.mjs` calls the installed DSH package's exported profile boot function,
with its runtime layout and package versions checked first. It suppresses the
ordinary CLI's raw startup-error reports; the panel returns fixed error codes.
Those safe diagnostics are distinct from DSH session context records: session
records can contain the authorized input messages and model output, stay inside
the panel-owned directory, and are included in its storage preview and cleanup.

The dedicated profile disables workspace instructions, skills, MCP resources,
tool plugins, subagents, plan mode, model-generated session titles, telemetry,
hot reload and persisted projection caching. Tools use native presentation;
SQLite search is `:memory:` with `openAt: never`. Every new ACP session passes
`mcp_servers=[]`. There is no unrestricted profile or provider fallback.

Official contracts:

- [DSH tools guard and restrictions](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/core/tools/README.md)
- [DSH ACP interface](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/acp/acp/README.md)
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk)

Model tests use synthetic data. Real DSH/provider acceptance is performed by the
operator; a passing fake transport test does not establish paid-route success.
