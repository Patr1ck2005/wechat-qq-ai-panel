# WeChat QQ AI Panel · 微信 QQ AI 面板

**为已有会话提供按需桌面速览。** 小型 Windows 托盘面板支持获取消息、摘要和待办提取，可编辑提示词，选择 DSH 或兼容 API 后端。

[English](README.md) · [读取底座](https://github.com/Patr1ck2005/wechat-qq-access) · [视觉来源](docs/visual-assets.md) · [历史](docs/README-history.md)

![面板产品流程](docs/assets/product-overview.svg)

## 界面示意

![合成面板预览，包含独立会话权限设置](docs/assets/interface-preview.svg)

*矢量合成图，不是真实账号截图或真实模型运行回执。名字、条数、消息和结果均为虚构。相对时间标注用于解释排序，应用本身不显示这些时间戳。当前安装界面为中文。*

| 读取 | 整理 | 控制 |
|---|---|---|
| 获取消息不调用模型 | 速览、待办、待回复、今日回顾 | 每账号白名单或排除名单 |
| 群聊／私聊／设备分区 | 编辑保存提示词预设 | 关注不会授予权限 |

## 安装

需要 Windows 10/11 x64、PowerShell 7、Python 3.11、WebView2 Evergreen Runtime。两个仓库保持同级：

```powershell
mkdir wechat-qq-ai
cd wechat-qq-ai
git clone --branch v0.3.0 https://github.com/Patr1ck2005/wechat-qq-access.git access
git clone --branch v0.2.3 https://github.com/Patr1ck2005/wechat-qq-ai-panel.git panel
cd panel
./scripts/install.ps1
./scripts/start.ps1
```

安装器创建独立面板环境，复用读取部署，并创建带内置图标的快捷方式。QQ 仍需明确网络暴露确认及本人登录。读取私有数据归属于选中部署，新安装通常为 `%USERPROFILE%/.local/share/wechat-qq-access`。见 [桌面入口](WEB_ENTRY.md) 和 [集成合同](INTEGRATION.md)。

已有安装只刷新快捷方式和图标：

```powershell
./scripts/update-shortcut.ps1
```

完全退出后重开，载入更新的窗口／托盘图标，保留原配置选择。

## 首次使用

1. 通过读取底座准备消息源。
2. 设置每个账号的会话权限。白名单只准选中会话；排除名单允许未排除会话，包括新增会话。策略缺失／损坏时拒绝读取。
3. 从已授权范围选择关注会话。
4. 选择后端和预设。**获取新消息**不调用模型；**摘要**先刷新再分析；**停止**取消工作且不推进成功分析游标。

本地 AI 客户端也可经共享 skill 定向发现并授权命名会话，无需先打开面板。面板保存采用版本检查，保留期间 Agent 已完成的权限修改。同名目标需消歧，“只读已授权”不会扩权。

DSH 需要已安装发行版与配置好的服务商；面板使用专属无工具配置及私有会话，不回退到普通无限制 Agent。API 模式需要完整基址、准确模型 ID 和环境变量／Windows 凭据管理器引用。不会自动切换服务商，真实兼容性按所选后端验收。

## 隐私与存储

底座在产品读取和模型提交前检查稳定平台／账号／会话身份。获准正文会发给所选服务商；同一 Windows 用户下其他程序不在产品保护范围内。微信可能先在本机解密整个数据库分片再过滤，其缓存留在读取底座。见 [第三方说明](THIRD_PARTY.md)。

面板设置和最新结果位于 `%LOCALAPPDATA%/WeChatQQAIPanel`。DSH 会话可能包含提交正文，存储预览单独统计；清理将本产品非活动文件移入 Windows 回收站。面板不建立第二份完整聊天存档。连接部署失败时可写入有界诊断，不含账号 ID、正文或凭据。

## 开发与许可

```powershell
python -m unittest discover -s tests -v
```

测试使用合成消息及模拟传输；真实 GUI／DSH 验收由本人运行，分别记录。本次没有读取聊天、启动模型或执行采集。发送、自动回复、持续采集及 GUI 自动化不在范围内。

独立源码和原创画作适用 [MIT](LICENSE)；上游读取器及依赖许可分别适用，包括固定 NapCat 的非商业限制。[视觉资源说明](docs/visual-assets.md) 记录图标与合成预览的来源。
