# WeChat QQ AI Panel · 微信 QQ AI 消息面板

Windows tray panel for your existing WeChat and QQ conversations: fetch new messages, generate AI briefs, and extract follow-ups with editable prompt presets. Conversation permissions are enforced by the companion access layer before any model request.

微信／QQ新消息、AI摘要、待办与待回复，一个小窗口完成。默认按按钮执行，关注列表与允许读取范围分开管理。支持 DeepSeek Harness（DSH）和兼容 Chat Completions 的 API。

## Install / 安装

Requires Windows 10/11 x64, PowerShell 7 and Python 3.11. WebView2 Evergreen Runtime must be installed. Keep the two repositories in sibling directories:

```text
wechat-qq-ai/
  access/    # https://github.com/Patr1ck2005/wechat-qq-access
  panel/     # https://github.com/Patr1ck2005/wechat-qq-ai-panel
```

```powershell
# Fresh deployment: keep both repositories together.
mkdir wechat-qq-ai
cd wechat-qq-ai
git clone --branch v0.2.0 https://github.com/Patr1ck2005/wechat-qq-access.git access
git clone --branch v0.1.0 https://github.com/Patr1ck2005/wechat-qq-ai-panel.git panel
cd panel
# Reuses an existing access deployment when available.
./scripts/install.ps1
./scripts/start.ps1
```

The installer provisions a separate panel Python environment, reuses the access layer's existing runtime and caches, and creates a desktop shortcut. QQ setup retains the access layer's explicit network-exposure acknowledgement and manual login requirements.

## First use / 首次使用

1. Set up available message sources using the [access project](https://github.com/Patr1ck2005/wechat-qq-access).
2. Select allow-list or exclusion-list permissions for each account. Allow-list permits only selected conversations; exclusion-list permits every conversation except selected exclusions, including new conversations. Missing or invalid policy fails closed.
3. Choose watched conversations from the authorized list. Watching never grants permission.
4. Select a model backend and preset. **Fetch** reads without AI; **Summarize** refreshes and analyzes. **Stop** cancels work without advancing successful analysis cursors.

DSH requires an installed desktop/CLI distribution and a configured provider. The panel imports only non-secret provider metadata and environment-variable credential references into its dedicated no-tools profile; ordinary DSH settings are preserved. If its guard cannot load, DSH is unavailable rather than falling back to a normal agent profile. Real model compatibility must be verified with the operator's selected provider.

For API mode, configure a full API base URL (normally ending in `/v1`), exact model ID and an environment-variable key reference or Windows Credential Manager entry. No provider fallback is automatic.

## Privacy boundary / 隐私边界

The access repository owns the policy. Every product message/attachment request checks stable platform, account and conversation IDs. The model receives only the authorized selected text, with no general local tools. Message bodies and results are displayed as escaped text.

This protects this product's data flow. Other applications running with your full Windows account permissions remain outside that boundary. The WeChat reader may decrypt a whole database shard locally before querying an authorized conversation; that cache stays in the trusted access runtime. Authorized text sent for AI processing goes to the provider you selected.

## Storage / 存储

Settings and latest results are under `%LOCALAPPDATA%/WeChatQQAIPanel`. The panel does not create another complete chat archive. DSH context/session logs use a dedicated panel directory and can contain the submitted message context. Storage preview reports these separately and warns at 200 MiB. Cleanup moves owned inactive files to Windows Recycle Bin; it does not free physical disk space until the bin is emptied by the user.

## Development / 开发

```powershell
python -m unittest discover -s tests -v
```

Tests use synthetic messages and fake model transports. No real account or paid model is required. GUI and live DSH acceptance are manual; development does not use CU or GUI automation.

Independent source is MIT. Third-party dependencies and the upstream message readers retain their own licenses, including the fixed NapCat version's non-commercial restrictions. See [third-party notices](THIRD_PARTY.md) and the companion repository's license details.
