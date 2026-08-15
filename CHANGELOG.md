# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增
- 开源发布准备：统一部署路径为 `/opt/xiaonai`，移除硬编码密钥与个人信息
- 新增 CI（GitHub Actions）：语法检查 + Ruff + 密钥泄露扫描
- 新增社区文件：CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / issue & PR 模板
- 新增密钥扫描脚本 `scripts/scan_secrets.sh`

### 安全
- 移除硬编码的和风天气 API Key（改用 `.env` 注入，`QW_API_KEY` / `QW_API_HOST`）
- 移除真实同学姓名与 QQ 群号（替换为占位符）
- `.gitignore` 补充 `.webvpn_ticket` / `.resource_token` / `exports/`
- 删除独立 WebVPN 编码工具脚本（功能内联，降低被关注风险）

## [0.0.1] - 2026-08-15

首个公开版本基线（开源首发）。

### 核心能力
- 消息桥接：BATCH 合并、去重、安全过滤、分段发送
- 工具路由：9 种工具（成绩 / 招生计划 / 校园通知 / 资源 / 知识库 / 考试 / 论文 / 提醒 / 天气）
- 知识库：BM25 + 字符语义 TF-IDF 多路检索 + MiMo 查询改写
- 三层记忆：会话 / resume 摘要 / 长期笔记（SQLite）
- 好感度引擎：六维情感模型 + 雷达图
- 定时推送：天气 / 地震预警 / 校园通知 / 考试倒计时（零 LLM 依赖）
- 图片识图：MiMo 多模态
- 健康自愈：服务重启、会话锁清理、内存/磁盘监控、熔断器

### 运维
- systemd 单元文件（bridge / scheduler）
- `health_check.sh` cron 巡检
- `admin_cli.py` 运维 CLI
