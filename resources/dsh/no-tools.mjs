/** Execution boundary for the isolated panel profile. No prompt policy required.
 * Uses the public tools.guard API in DSH 0.2.0-rc.2. Unknown versions fail in the
 * Python adapter before this profile can run.
 */
import { writeFileSync } from 'node:fs';

export const name = 'wechat-qq-panel-no-tools';
export const inject = ['tools', 'agents'];

export function apply(ctx, config) {
  if (!ctx.tools || typeof ctx.tools.guard !== 'function' || typeof ctx.tools.restrict !== 'function') {
    throw new Error('PANEL_GUARD_UNAVAILABLE');
  }
  if (!config || !/^[a-f0-9]{32}$/.test(config.nonce) || typeof config.readyPath !== 'string') {
    throw new Error('PANEL_GUARD_CONFIGURATION');
  }
  // Global monotonic denial: later pre-execute hooks cannot override this.
  const disposeGuard = ctx.tools.guard(() => 'PANEL_TOOLS_DISABLED');
  if (typeof disposeGuard !== 'function') throw new Error('PANEL_GUARD_UNAVAILABLE');

  // Restrict visible inherited schemas, including agents created after startup.
  ctx.on('agent/created', ({ agent }) => {
    if (!agent?.ctx?.tools || typeof agent.ctx.tools.restrict !== 'function') {
      throw new Error('PANEL_AGENT_GUARD_UNAVAILABLE');
    }
    agent.ctx.tools.restrict({ allow: [] });
    // Defence in depth for agent-local registrations (which schema restriction
    // intentionally does not hide): all execution still sees a monotonic guard.
    agent.ctx.tools.guard(() => 'PANEL_TOOLS_DISABLED');
  });

  writeFileSync(config.readyPath, JSON.stringify({
    guardVersion: 1, nonce: config.nonce, toolsDisabled: true,
  }), { encoding: 'utf8', mode: 0o600 });
  // ACP's inject list requires this service. Missing/broken plugin => no ACP.
  ctx.provide('panelNoTools', Object.freeze({ guardVersion: 1 }));
}
