# Local Desktop Entry · 本机桌面入口

主要入口是仓库根目录的 `start-panel.cmd`，与 `scripts/start.ps1` 启动同一面板。先按 [README](README.md) 完成安装；启动器使用本仓库 `.venv` 中的 `pythonw.exe`。重复打开由单实例逻辑唤起现有窗口，关闭窗口收起到托盘，完全退出使用面板或托盘的“退出”。

## Project Hub 登记

这是一项桌面 `desktop` 入口，只提供打开。无需 `PROJECT_WEB.json`、监听端口、HTTP 健康检查或受管服务，也不登记 Hub 的停止／重启按钮。要退出程序，使用面板自身入口。

本机登记采用稳定项目 ID `wechat-qq-ai-panel`，以 `panel` 仓库为主入口；配套 `access` 仓库与母文件夹归入同一管理身份，不另建重复卡片。登记和绝对路径由各机器的 Project Hub `projects.json` 维护，应用不自动修改其他机器的登记。

桌面入口应检查 `start-panel.cmd`、`.venv/Scripts/pythonw.exe`、`wq_panel/__main__.py`、`wq_panel/ui.html`、`panel_models/__init__.py`，以及虚拟环境中的 pywebview、pystray、Pillow。缺少依赖时保持不可用，先运行本项目安装器。WebView2 与消息底座的安装和诊断仍按 README 执行。

登记变更在 Project Hub 正常重启后加载；网页刷新不会替代重启。登记维护本身不停止或重启 Hub、面板及消息接入。

## 验证记录

2026-10-15 用户人工确认主窗口可打开，并在部署路径修复后确认账号和会话列表能正常加载。本次 Project Hub 接入只核实登记格式、入口路径与依赖存在，没有由 Agent 启动 GUI、调用模型或读取真实消息。托盘交互、整理体验及真实 DSH 模型测试仍由使用者人工验收。
