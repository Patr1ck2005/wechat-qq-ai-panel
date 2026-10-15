/** Offline test against an installed DSH tool registry. No LLM is mounted. */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { apply } from './no-tools.mjs';

const [runtimeModules, readyPath] = process.argv.slice(2);
try {
  if (!runtimeModules || !readyPath) throw Error('SELFTEST_ARGUMENTS');
  const version = JSON.parse(readFileSync(join(runtimeModules, '@deepseek-ai/dsh-tools/package.json'), 'utf8')).version;
  if (version !== '0.2.0-rc.2') throw Error('SELFTEST_VERSION');
  const { Context } = await import(pathToFileURL(join(runtimeModules, '@deepseek-ai/cordis/lib/index.js')).href);
  const { ToolRuntime, defineTool } = await import(pathToFileURL(join(runtimeModules, '@deepseek-ai/dsh-tools/lib/index.js')).href);
  const ctx = new Context();
  ctx.provide('systemPrompt', { tools() {} });
  await ctx.plugin(ToolRuntime, { mode: 'native' });
  let executed = 0;
  apply(ctx, { nonce: 'a'.repeat(32), readyPath });
  // Future registration and an explicit allow hook must not bypass the guard.
  ctx.tools.register(defineTool({
    name: 'malicious_fixture', description: 'Synthetic tool that must never run.',
    parameters: {},
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    execute() { executed++; return 'unsafe'; },
  }));
  ctx.on('tools/pre-execute', () => ({ kind: 'allow' }));
  const result = await ctx.tools.execute({
    callId: 'offline-fixture', name: 'malicious_fixture', arguments: {},
    signal: new AbortController().signal,
  });
  const denied = result.isError === true && result.error.message === 'PANEL_TOOLS_DISABLED';
  if (!denied || executed !== 0 || !ctx.get('panelNoTools')) throw Error('SELFTEST_DENIAL');
  await ctx.fiber.dispose();
  console.log(JSON.stringify({ version, denied, executed, providerMounted: false }));
} catch {
  console.error('PANEL_GUARD_SELFTEST_FAILED');
  process.exitCode = 1;
}
