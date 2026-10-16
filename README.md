# WeChat QQ AI Panel · 微信 QQ AI 消息面板

![WeChat QQ AI Panel product overview: on-demand message briefs, separate conversation permissions, DSH or compatible API](docs/assets/product-overview.svg)

Windows tray panel for your existing WeChat and QQ conversations: fetch new messages, generate AI briefs, and extract follow-ups with editable prompt presets. Conversation permissions are enforced by the companion access layer before any model request.

微信／QQ新消息、AI摘要、待办与待回复，一个小窗口完成。默认按按钮执行，关注列表与允许读取范围分开管理。支持 DeepSeek Harness（DSH）和兼容 Chat Completions 的 API。

Conversation selection separates QQ groups, private chats and device/other sessions by account and source type. Within each section, recent activity comes first; unknown timestamps stay last, with stable ties. The default window is 600 px wide, with a compact, high-contrast neutral interface. Page loads and asynchronous actions show loading feedback with reduced-motion support.

QQ 群聊、私聊和设备／其他会话分区展示，各分区内部按最近活跃优先，未知时间稳定后置。默认窗口宽 600 px，采用紧凑、高对比的中性灰阶界面；页面载入和异步操作提供加载动画，并尊重系统减少动态效果设置。

| Read / 读取 | Organize / 整理 | Control / 控制 |
|---|---|---|
| Fetch without a model / 获取新消息不调用模型 | Quick brief, to-dos & replies, daily review / 速览、待办与待回复、今日回顾 | Per-account conversation permissions / 逐账号设置会话权限 |
| Separate QQ groups, private chats and devices/other / QQ 群聊、私聊、设备／其他分区 | Edit and save prompt presets / 编辑保存提示词预设 | Watching never grants access / 关注不会扩大授权 |

## Interface preview / 界面示意

![Synthetic panel interface showing message actions and separate QQ group, private, device/other permission controls](docs/assets/interface-preview.svg)

**Synthetic demo / 合成数据示意。** These are vector illustrations of the current interface, with English labels for this preview. All names, counts, messages and results are invented. The relative times in the sorting example are explanatory annotations; the app does not display these timestamps. These are not live-account screenshots or evidence of a real model run. The installed interface currently uses Chinese labels.

以上展示当前界面的功能结构，预览采用英文标签；账号、名字、条数和结果均为合成数据。桌面、窗口与托盘使用同一套随安装包提供的图标。

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
git clone --branch v0.3.0 https://github.com/Patr1ck2005/wechat-qq-access.git access
git clone --branch v0.2.3 https://github.com/Patr1ck2005/wechat-qq-ai-panel.git panel
cd panel
# Reuses an existing access deployment when available.
./scripts/install.ps1
./scripts/start.ps1
```

The installer provisions a separate panel Python environment, reuses the access layer's existing runtime and caches, and creates a desktop shortcut with the bundled product icon. QQ setup retains the access layer's explicit network-exposure acknowledgement and manual login requirements.

New access deployments keep their private data under `%USERPROFILE%/.local/share/wechat-qq-access`, outside AppData virtualization. The desktop shortcut pins the selected configuration explicitly; existing custom and legacy configurations remain supported.

本机桌面入口及可选的 Project Hub 登记见 [Local Desktop Entry](WEB_ENTRY.md)。

Existing installation / 已安装用户：refresh only the desktop launcher and icon without reinstalling dependencies or launching the app:

```powershell
./scripts/update-shortcut.ps1
```

The selected access configuration is preserved. Fully quit and reopen the panel to load the new window and tray icons. 图标来源、重建与合成展示说明见 [Visual assets](docs/visual-assets.md)。

## First use / 首次使用

1. Set up available message sources using the [access project](https://github.com/Patr1ck2005/wechat-qq-access).
2. Select allow-list or exclusion-list permissions for each account. Allow-list permits only selected conversations; exclusion-list permits every conversation except selected exclusions, including new conversations. Missing or invalid policy fails closed.
3. Choose watched conversations from the authorized list. Watching never grants permission.
4. Select a model backend and preset. **Fetch** reads without AI; **Summarize** refreshes and analyzes. **Stop** cancels work without advancing successful analysis cursors.

You can also ask a local AI client using the shared `messaging-access` skill to read a named conversation. It can discover and grant that exact conversation through the access CLI, including first use; opening this panel is optional. Existing modes and unrelated permissions remain intact. Ambiguous names are resolved in the conversation, and a request limited to already-authorized chats never expands access.

也可以直接对 Agent 说“读取微信某某群”：Agent 会查找目标、按请求精准授权并读取，无需先手动打开面板配置。同名群在对话中确认；原有模式及其他会话权限保留。面板保存使用版本检查，避免覆盖 Agent 刚完成的权限修改。

DSH requires an installed desktop/CLI distribution and a configured provider. The panel imports only non-secret provider metadata and environment-variable credential references into its dedicated no-tools profile; ordinary DSH settings are preserved. If its guard cannot load, DSH is unavailable rather than falling back to a normal agent profile. Real model compatibility must be verified with the operator's selected provider.

For API mode, configure a full API base URL (normally ending in `/v1`), exact model ID and an environment-variable key reference or Windows Credential Manager entry. No provider fallback is automatic.

## Privacy boundary / 隐私边界

The access repository owns the policy. Every product message/attachment request checks stable platform, account and conversation IDs. The model receives only the authorized selected text, with no general local tools. Message bodies and results are displayed as escaped text.

This protects this product's data flow. Other applications running with your full Windows account permissions remain outside that boundary. The WeChat reader may decrypt a whole database shard locally before querying an authorized conversation; that cache stays in the trusted access runtime. Authorized text sent for AI processing goes to the provider you selected.

## Storage / 存储

Settings and latest results are under `%LOCALAPPDATA%/WeChatQQAIPanel`. The panel does not create another complete chat archive. DSH context/session logs use a dedicated panel directory and can contain the submitted message context. Storage preview reports these separately and warns at 200 MiB. Cleanup moves owned inactive files to Windows Recycle Bin; it does not free physical disk space until the bin is emptied by the user.

If the panel cannot find its access deployment, a bounded `connection-diagnostic.json` in that same private directory records the failure stage, configuration source and existence checks. It contains no paths, account identifiers, message text or credentials.

## Development / 开发

```powershell
python -m unittest discover -s tests -v
```

Tests use synthetic messages and fake model transports. No real account or paid model is required. GUI and live DSH acceptance are manual; development does not use CU or GUI automation.

Independent source is MIT. Third-party dependencies and the upstream message readers retain their own licenses, including the fixed NapCat version's non-commercial restrictions. See [third-party notices](THIRD_PARTY.md) and the companion repository's license details.
