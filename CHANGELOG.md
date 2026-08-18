# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/) 与
[Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.0.6] - 2026-08-18

### 新增
- **第二阶段持续陪伴关系层**：为每个用户增加主动陪伴开关、安静时段、每日额度、20 小时冷却、称呼偏好、讨厌短语和有限关系事件记录。
- **明确的私聊控制命令**：支持“开启陪伴提醒”“关闭陪伴提醒”“陪伴状态”“叫我 X”“别这样叫我 X”“我不喜欢你说 X”，命令在 bridge 层直接处理，不交给 LLM 猜测。
- **时间感和连续性提示**：根据早晨、白天、晚上、深夜调整回复约束；私聊最多自然跟进一个当前用户自己的未完话题。

### 安全与隐私
- 主动陪伴默认关闭；群聊不能修改个人陪伴设置，也不会注入私聊称呼、偏好、事件或开放话题。
- 主动陪伴不使用催促回复、制造愧疚或“为什么不理我”等情感施压话术。
- 关系事件只保存短摘要，最多 20 条，不保存完整聊天原文；旧关系 JSON 缺字段时使用安全默认值迁移。

### 测试
- `python3 -m py_compile bridge.py xiaonai_memory.py src/memory/mood.py src/memory/relationship_state.py test_relationship_state.py test_phase2_relationship.py test_reply_segments.py`
- `python3 -m unittest -v test_relationship_state.py test_phase2_relationship.py test_reply_segments.py`
## [0.0.5] - 2026-08-18

### 新增
- **全用户真实女友式关系层**：为每个 QQ 用户独立保存关系阶段、互动温度、信任、亲密度、开放话题和修复状态，让称呼、记忆与共同经历不串台。
- **按场景调整表达**：新增温暖问候、日常陪伴、轻松打趣、安慰、害羞回应、边界修复和低能量等行为模式，并把情绪状态转换为可执行的表达约束。

### 修复
- **群聊隐私隔离**：群聊不再注入私聊昵称、QQ 号、私聊事实、关系阶段、私聊记忆或排他性表达；未完话题只在对应用户私聊中使用。
- **NapCat 重连稳定性**：HTTP API 8081 改为单实例生命周期，避免重连时重复绑定；旧 WebSocket 断开不会清空新连接状态。
- **关系状态数据健壮性**：增加文本清洗、异常情绪值容错、关系状态回归测试和群聊隐私回归断言。

### 测试
- `python3 -m py_compile ...`
- `python3 -m unittest -v test_relationship_state.py test_reply_segments.py`

## [0.0.4] - 2026-08-16

### 修复
- **识图后追问误注入知识库结果**（图片追问「详细解释一下」→ agent 反问「详细解释啥呀？」）：工具注入/路由原来基于带记忆/性格前缀的完整消息做正则判断，前缀里的「什么」「吗」等词命中 legacy `is_q` 正则，把追问误判为知识库查询，smart_search 注入无关结果（曾注入「校园网管理规定」775 chars）→ agent 被干扰。改为基于用户原始文字 `_user_raw_text` 判断（与 #43 识图描述污染提醒判断同型：系统注入文本不得参与用户意图判断）。已实测：前缀拼接后 is_q=True 误触发注入、用原始文字 is_q=False 不注入；正常工具路由（score/资源/知识库）零回归

## [0.0.3] - 2026-08-15

### 修复
- **群分类/群管理描述与行为对齐**（对照 bridge.py 真实行为全面校对）：
  - personality.py 群冒泡：CLASS_GROUP 变量取值与注释互相矛盾（变量名 CLASS 却取 CHAT 占位符、注释说闲聊群不冒泡）→ 改为 BUBBLE_GROUP = CHAT_GROUP_PLACEHOLDER，与 FEATURES-GUIDE「只发 chat_groups」一致
  - ai_handler.py 群管理 action：原 add_class_group/normal/mute/chat 四个动作全写进 class_groups、remove_* 全写进 chat_groups → 改为每个动作各归各键
  - ai_handler.py 黑名单：原按 session_id（群消息=群号）判断 → 改为按用户 QQ 判断（与 bridge 一致，文档明示按用户拉黑）
  - ai_handler.py 未配置群：原「被动观察+条件回复」→ 完全忽略（与 bridge 主链路一致）
  - client.py 群配置提示词：测试群描述修正、黑名单传参改为 QQ 号
  - SOUL.md 群清单：移除真实群名（敏感信息），描述对齐回复策略
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
