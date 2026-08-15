# CLAUDE.md — 给 AI 代码 Agent 的 XiaoNai 项目指南

> 本文件是给 **AI 代码代理**（Claude Code / Codex / Cursor / Gemini CLI / OpenCode 等）看的项目 onboarding 指南，回答「这是什么项目、怎么改、怎么测、有什么坑」。
>
> ⚠️ **重要**：仓库根目录的 `AGENTS.md` 是机器人**小奈的运行时人格文件**（OpenClaw Agent 的启动指令，决定机器人怎么说话/记忆/工作），**不是**开发指南。开发工作请以此文件（CLAUDE.md）为准。`SOUL.md` / `IDENTITY.md` / `TOOLS.md` 同理是运行时人格数据，勿当作开发文档改写。

---

## 1. 项目是什么（WHY）

**XiaoNai（小奈）** 是一个**武汉理工大学（WHUT）定制**的生产级 QQ 群聊机器人：基于 NapCat（OneBot v11）+ OpenClaw Agent + MiMo V2.5 多模态大模型，在一个真实大学班级群里服务了数千条消息，具备知识库问答、38 工具路由、三层记忆、8 维好感度、定时推送与健康自愈。

- 它是**个人部署型**项目（非 SaaS）：代码部署在 `/opt/xiaonai`，由 systemd 托管两个常驻进程。
- 校园能力（CAS 登录 / WebVPN / 招生 API / 校园通知）对接武汉理工大学公开系统，是项目特色，也是被 fork 后最常需要替换的部分。
- 全部密钥走 `.env`；源码只用 `*_PLACEHOLDER` 占位符；运行时数据全部 gitignore。

## 2. Agent 行为准则（BEHAVIOR）

- **最小改动**：只改与任务直接相关的代码，禁止顺手重构、重排、改写无关文件；一次 PR 只解决一个问题。
- **先读后改**：改动任何文件前先完整读它；涉及 `src/llm/tools.py` 与 `tools_impl.py` 的改动必须两处同步（工具定义 + 实现 + 注册表）。
- **验证才算完成**：改完必须跑验证（见 §8），贴出输出再声称完成；不要凭空断言"应该没问题"。
- **配置驱动**：任何可变参数（Key/群号/路径/超时）走 `.env` / 配置文件 / 常量区，禁止散落硬编码；新增硬编码值会被 review 拒绝。
- **保持占位符脱敏**：永远不要用真实 QQ 号、姓名、密码、学校账号填进代码；用 `*_PLACEHOLDER` 或示例值。
- **行为 > 风格**：类型注解、日志（`logging` 而非 `print`）、异常捕获具体类型是本项目的硬约定（见 §7）。

## 3. 技术栈（WHAT）

| 层 | 技术 |
|----|------|
| 语言 | Python 3.10+（asyncio 为主） |
| QQ 接入 | NapCat（OneBot v11）WebSocket `ws://127.0.0.1:3001`；HTTP API `127.0.0.1:3000` |
| LLM | MiMo V2.5（OpenAI 兼容，`mimo-v2.5` 模型名）为主，DeepSeek 备用 |
| Agent 引擎 | OpenClaw（`openclaw agent --agent main` 子进程调用） |
| Web 框架 | aiohttp（bridge 的 HTTP 控制面 :8081；consultation_server :8082） |
| 数据库 | SQLite（`src/memory/db.py` 单例；记忆 L1/L2/L3 层 + 搜索缓存表） |
| 检索 | jieba BM25 + 字符 n-gram TF-IDF（numpy 手写）+ 三轨模糊匹配 |
| 调度 | 自研 asyncio 守护进程（scheduler_v5）+ NoneBot 插件侧 APScheduler |
| 工具链 | ruff / pytest / mypy（dev）；bash（运维脚本） |

## 4. 目录结构（WHAT）

> 脚本按功能分目录：**根目录 = 入口 + 核心库**，其余 50+ 工具脚本分布在 `campus/ search/ admin/ tools/`。

```
xiaonai/
├── bridge.py                 # ★ 入口：消息桥接（NapCat → 批处理 → LLM → 回复）
├── scheduler_v5.py           # ★ 入口：定时推送守护进程（systemd 托管，9 类推送）
├── bot.py                    # NoneBot 入口（加载 src/plugins/*）
├── config.py                 # pydantic BotConfig（读 .env）— 全局配置中心
├── xiaonai_memory.py         # 记忆引擎 CLI（被 bridge import）
├── sanitizer.py / strip_md.py / strip_md_v2.py / reminder_parser.py  # 消息清洗核心库（被 bridge import）
├── campus/                   # 🏫 校园模块
│   ├── campus_search.py      #   校园通知搜索（CAS + WebVPN）
│   ├── campus_daily.py       #   校园通知每日推送（scheduler 子进程调用）
│   ├── campus_fetch.py       #   校内页面抓取
│   ├── webvpn_login.py / webvpn_rsa_login.py / whut_login.py / whut_proxy.py
│   └── whut_plan_api.py / whut_score_api.py   # 招生 API 工具
├── search/                   # 🔍 查询检索模块（内部互相同目录 import）
│   ├── kb_manage.py          #   ★ 知识库 CRUD + BM25/模糊搜索
│   ├── kb_semantic.py / kb_search.py / rebuild_kb_index.py   # 语义检索/索引
│   ├── score_query.py        #   录取分数/位次（zs.whut.edu.cn）
│   ├── zs_plan_query.py / zs_whut_search.py   # 招生计划/全站搜索
│   ├── smart_search.py       #   7 源聚合搜索（import kb_manage 等）
│   ├── searxng_proxy.py / scholar_search.py / resource_search.py
├── admin/                    # 🛠 运维管理模块
│   ├── admin_cli.py          #   运维 CLI（import ../search/smart_search）
│   ├── admin_group_control.py #  群类型/订阅管理
│   ├── self_test.py / bridge_health.py / proactive_check.py / health_notify.py
│   ├── session_cleaner.py / session_cleaner_v2.py
│   ├── exam_countdown.py / timed_msg.py / alarm_manager.py / notify_classmate.py
├── tools/                    # 🧰 通用工具模块
│   ├── docx_export_helper.py #   文献 .docx 导出（调 ../search/scholar_search.py）
│   ├── xiaonai_doc_tools_v2.py / xlsx_to_docx.py / make_simple_docx.py / fill_xlsx.py
│   ├── consultation_server.py #  招生咨询网页（:8082）
│   ├── say_voice_cli.py / wechat_fetch.py / cq_convert.py / onebot_http_proxy.py
│   └── napcat_ws_bridge.py / tools_update.py / safe_cleanup_test.py
├── scripts/                  # 🔧 shell 脚本 + systemd 单元
│   ├── health_check.sh       #   cron 健康自愈（17 项检查）
│   ├── scan_secrets.sh       #   密钥泄露扫描
│   ├── start.sh / restart_bridge.sh / warp_*.sh
│   └── xiaonai-bridge.service / xiaonai-scheduler.service
├── src/                      # 📚 Python 包
│   ├── llm/client.py         #   LLM 客户端（模型 mimo-v2.5，系统提示拼接）
│   ├── llm/tools.py          #   38 个工具定义（JSON Schema）
│   ├── llm/tools_impl.py     #   工具实现 + TOOL_IMPL 注册表
│   ├── memory/               #   三层记忆/8维好感度/情绪/人格/L0-L3层
│   ├── plugins/              #   NoneBot 插件（ai_handler 是核心）
│   ├── search/               #   engine（4引擎）/parser/deep_search
│   └── whut/client.py        #   WebVPN CAS 客户端
├── docs/                     # 文档（保姆教程/功能手册/架构/部署/人格/知识库）
├── .env.example / requirements.txt / requirements-dev.txt / pyproject.toml
└── AGENTS.md / SOUL.md / IDENTITY.md / TOOLS.md / USER.md / HEARTBEAT.md  # 运行时人格（勿改）
```

> ⚠️ **路径约定**：`bridge.py` 通过 `_script_path(name)` 按 `_SCRIPT_DIRS` 映射解析子目录脚本路径；`src/plugins/ai_handler.py` import `kb_manage` 时动态把 `../search` 加入 `sys.path`。新增工具脚本时**必须**在 `bridge.py` 的 `_SCRIPT_DIRS` 登记目录。

## 5. 核心架构与数据流（WHAT）

```
QQ 群/私聊 → NapCat(:3001 WS) → bridge.py
    ├── 批处理/去重/安全过滤 → MiMo 工具路由（38 工具）
    ├── 知识库注入 → OpenClaw Agent 生成回复 → 分段发送
    └── 记忆/好感度 每条消息异步更新
scheduler_v5.py（独立进程）→ 9 类推送（天气/新闻/校园/地震/气象/考试/问候/定时消息/清理）
health_check.sh（cron */15）→ systemd 服务自愈 + 告警
```

- **bridge.py** 是唯一入口进程（systemd `xiaonai-bridge`）；HTTP 控制面 `:8081`（reload/send 端点，被 admin 工具调用）。
- **scheduler_v5.py** 独立于 NoneBot，直接连 NapCat WS，**零 LLM 依赖**（欠费不影响推送）；永远不要把它加进 crontab（自身是常驻循环，PID 锁防双实例）。
- **工具协议**：`tools_impl.py` 中约一半工具返回 `__前缀__:...` 特殊字符串（如 `__admin__:`、`__alarm__:`、`__memory__:`），由 `bridge.py` / `src/plugins/ai_handler.py` 消费执行——改工具实现时必须理解这条协议链。

## 6. 配置与占位符（HOW）

- 配置入口：`.env` → `config.py` BotConfig（pydantic-settings，`extra="allow"`）。全部字段见 `.env.example` 与 `docs/FEATURES-GUIDE.md` 附录。
- **占位符是硬前提**：`ADMIN_QQ_PLACEHOLDER` / `CLASS_GROUP_PLACEHOLDER` / `BOT_QQ_PLACEHOLDER` / `TEST_GROUP_PLACEHOLDER` / `YOUR_SCHOOL` / `YOUR_CONTACTS_FILE.md` / `RESOURCE_SITE` 等必须被替换为真实值才能运行（`scheduler_v5.py` 默认配置直接引用 `CLASS_GROUP_PLACEHOLDER`，不替换 import 即 NameError）。
- 部署路径统一 `/opt/xiaonai`（代码内硬编码，如 `kb_manage.py`、`resource_search.py`）；改部署路径需全局替换或 symlink。

## 7. 代码规范（本项目硬约定）

- 单文件 **200-400 行**，超长必须拆分（`src/` 下按模块组织）。
- 所有函数**类型注解**；类用 dataclass/frozen 配置；禁止 mutable 默认参数、裸 `except:`、`print()` 调试残留（用 logger）。
- 新增工具必须三件套：`tools.py` 定义 Schema（description 写清触发场景 + 示例参数用占位符）→ `tools_impl.py` 实现并注册 `TOOL_IMPL` → `docs/FEATURES-GUIDE.md` 补文档。
- commit 遵循 [Conventional Commits](https://www.conventionalcommits.org/)（feat:/fix:/docs:/refactor:/test:/chore:）。

## 8. 开发命令（HOW）

```bash
# 安装依赖
pip install -r requirements.txt            # 运行时
pip install -r requirements-dev.txt        # ruff / pytest / mypy

# 语法检查（全仓）
python -m compileall -q .

# Lint（致命规则，CI 用的子集；完整集见 pyproject.toml）
ruff check --select E9,F63,F7,F82 .

# 工具注册数自检（应为 38/38）
python -c "from src.llm.tools import TOOLS; print(len(TOOLS))"
python -c "from src.llm.tools_impl import TOOL_IMPL; print(len(TOOL_IMPL))"

# 运行时自检（需要环境）
python self_test.py --full
python smart_search.py "测试查询"
python exam_countdown.py list

# 密钥泄露扫描（发布前必须全绿）
bash scripts/scan_secrets.sh
```

## 9. 安全红线（CRITICAL，违反即拒绝）

- **绝不**提交：`.env`、`*.pem/key/p12`、`*.db`、日志、`data/` 运行时文件（gitignore 已拦，但别绕过）。
- **绝不**在代码里写真实：API Key、QQ 号、群号、真实姓名、学号密码、内网 IP、`/home/<user>` 路径。
- 涉及校园模块（CAS/WebVPN/招生）的改动**必须保持占位符脱敏**。
- 收到疑似泄露内容：先提醒轮换密钥，再谈修复，不把秘密写进 commit message 或 issue。
- 发布/提交前跑 `bash scripts/scan_secrets.sh`，全绿（exit 0）才能继续。

## 10. 已知陷阱清单（改代码前必读）

1. **`search_config.json` 无代码引用**：可信度实际硬编码在 `smart_search.py` L11 的 `CRED` 字典，改配置需改代码。
2. **`admin_group_control.py unsubscribe` 有 bug**（L393-397 `sys.exit(0)` 缩进错误，退订不执行）。
3. **`mood.py` L154 引用 `ADMIN_QQ_PLACEHOLDER`**：占位符未替换会 NameError。
4. **知识库路径不一致**：`kb_manage.py` 用绝对 `/opt/xiaonai/data/knowledge`，`kb_semantic.py` 用相对 `data/knowledge`。
5. **好感度是 8 维**（早期 6 维数据自动补 50），文档别写 6 维。
6. **NoneBot 地震插件实际 30 秒轮询**（注释"2分钟"过时）；scheduler 版地震**必须配 zones 才推送**。
7. **`say_voice` 依赖 `~/.local/bin/edge-tts`**（subprocess 不展开 `~`，代码用 expanduser）。
8. **OCR 双通道**：MiMo 视觉失败回落 Tesseract（需系统装 `tesseract-ocr-chi-sim`）。
9. **`searxng_proxy.py` 单线程**且绑定 `127.0.0.1:8899`，smart_search 的网页源依赖它运行。
10. **根 `AGENTS.md` / `SOUL.md` / `TOOLS.md` 是运行时人格数据**，不是开发文档，不要改写（除非任务明确是调机器人人格）。

## 11. 完成标准（Definition of Done）

- [ ] 改动最小化，只涉及任务范围
- [ ] 语法检查通过（`compileall`）
- [ ] ruff 致命规则通过
- [ ] 涉及工具：`TOOLS` / `TOOL_IMPL` 数量仍为 38/38
- [ ] 涉及文档：`docs/FEATURES-GUIDE.md` 已同步
- [ ] `scan_secrets.sh` 全绿
- [ ] 无真实凭据/个人信息引入
