# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.0.3] - 2026-08-15

### 修复
- **群分类/群管理描述与行为对齐**（对照 bridge.py 真实行为全面校对）：
  - personality.py 群冒泡：CLASS_GROUP 变量取值与注释互相矛盾（变量名 CLASS 却取 CHAT 占位符、注释说闲聊群不冒泡）→ 改为 BUBBLE_GROUP = CHAT_GROUP_PLACEHOLDER，与 FEATURES-GUIDE「只发 chat_groups」一致
  - ai_handler.py 群管理 action：原 add_class_group/normal/mute/chat 四个动作全写进 class_groups、remove_* 全写进 chat_groups → 改为每个动作各归各键
  - ai_handler.py 黑名单：原按 session_id（群消息=群号）判断 → 改为按用户 QQ 判断（与 bridge 一致，文档明示按用户拉黑）
  - ai_handler.py 未配置群：原「被动观察+条件回复」→ 完全忽略（与 bridge 主链路一致）
  - client.py 群配置提示词：测试群描述修正、黑名单传参改为 QQ 号
  - SOUL.md 群清单：移除真实群名「」（敏感信息），描述对齐回复策略
  - TOOLS.md 测试群描述：明确 test_group 是默认发送目标、运维告警走 admin 私信
  - scheduler_v5.py 默认订阅：news 默认关闭（原默认开启会向班级群推送）、补 daily_greetings 键

## [0.0.2] - 2026-08-15

### 新增
- 开源发布准备：统一部署路径为 `/opt/xiaonai`，移除硬编码密钥与个人信息
- 新增 CI（GitHub Actions）：语法检查 + Ruff + 密钥泄露扫描
- 新增社区文件：CONTRIBUTING / SECURITY / CODE_OF_CONDUCT / issue & PR 模板
- 新增密钥扫描脚本 `scripts/scan_secrets.sh`
- **识图回复相关性兜底**：用 LLM 判断回复是否与识图描述相关，检测服务端缓存串台导致的跑题回复并自动重试（`_reply_relevance_check`）

### 修复
- 识图描述误触发定时提醒：`parse_reminder` 命中识图描述里的「定时」字样 → 新增 `_strip_vision_desc` 剥离识图描述块
- 识图偶发空返回：MiMo 返回空 content → vision 空返回自动重试一次
- 消息断句：引号被换行劈开 → `_has_unclosed_quote` 检测并合并
- 死循环防护：SOUL/AGENTS 禁止 exec 反复搜索知识库 + call_openclaw 三层防御（降超时/换内容/英文推理检测）
- router unparseable 分支补熔断

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
