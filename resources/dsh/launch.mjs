/** Official DSH profile boot with sanitized failures, pinned to a tested layout.
 * The ordinary CLI saves raw startup errors to DSH_HOME/logs. Such errors may
 * contain credential-parser details. This launcher never writes those reports.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

try {
  const [scopeRoot, flag, profile] = process.argv.slice(2);
  if (!scopeRoot || flag !== '--profile' || profile !== 'wechat-qq-panel') {
    throw Error('PANEL_BOOT_ARGUMENTS');
  }
  for (const name of ['dsh', 'dsh-tools', 'dsh-acp']) {
    const version = JSON.parse(readFileSync(join(scopeRoot, name, 'package.json'), 'utf8')).version;
    if (version !== '0.2.0-rc.2') throw Error('PANEL_BOOT_VERSION');
  }
  const { runProfile } = await import(pathToFileURL(join(scopeRoot, 'dsh/lib/profile-boot.js')).href);
  const { loadLayeredEnv } = await import(pathToFileURL(join(scopeRoot, 'dsh-app-boot/lib/index.js')).href);
  await runProfile({
    environment: loadLayeredEnv('dsh'), profile, patchFiles: [], args: [],
  });
} catch {
  // No error object, raw provider response, config dump, or credential value.
  console.error('PANEL_DSH_STARTUP_FAILED');
  process.exitCode = 1;
}
