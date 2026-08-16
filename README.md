<div align="center">

# 🤖 XiaoNai（小奈）

**一个在班级群长大的 AI 群助手** —— 基于 NapCat + OpenClaw + MiMo 的多功能 QQ 群聊机器人

**🏫 武汉理工大学（WHUT）定制版** —— 深度对接 whut.edu.cn 校园系统（CAS 登录 / WebVPN / 招生 API / 校园通知）

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Release](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fgitee.com%2Fapi%2Fv5%2Frepos%2Ffieldlu%2Fxiaonai%2Freleases%2Flatest&query=tag_name&label=Release&style=flat-square)](https://gitee.com/fieldlu/xiaonai/releases)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=flat-square)](LICENSE)
[![NapCat](https://img.shields.io/badge/NapCat-OneBot%20v11-3E8E7E?style=flat-square)](https://napneko.github.io/)
[![OpenClaw](https://img.shields.io/badge/OpenClaw-Agent%20Engine-6C5CE7?style=flat-square)](https://openclaw.ai)
[![MiMo](https://img.shields.io/badge/MiMo-V2.5%20Multimodal-FF6B6B?style=flat-square)](https://opencode.ai)
[![WHUT](https://img.shields.io/badge/🏫-WHUT%20Customized-1a5276?style=flat-square)](#-学校接入说明)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](CONTRIBUTING.md)

**知识库问答 · 工具路由 · 定时推送 · 记忆系统 · 健康自愈**

[快速开始](#-快速开始) · [架构](#-架构) · [文档](docs/) · [贡献](CONTRIBUTING.md) · [报告 Bug](https://github.com/fieldlu/xiaonai/issues/new?template=bug_report.md) · [申请功能](https://github.com/fieldlu/xiaonai/issues/new?template=feature_request.md)

</div>

---

## ✨ 特性

XiaoNai 诞生于一个真实的大学班级群，在数千条真实消息中迭代成长——选课规划、老师评价、校园通知、考试倒计时……它不是一个 demo，而是一个**生产级、久经考验**的群聊机器人。

| 能力 | 说明 |
|------|------|
| 🧠 **知识库问答** | 多路检索（BM25 + 字符语义 TF-IDF）+ MiMo 查询改写，口语化问题也能命中正确文档 |
| 🛠 **工具路由** | MiMo 意图识别 → 9 类对话路由（招生计划 / 录取分数 / 校园通知 / 资源 / 知识库 / 考试倒计时 / 论文 / 定时提醒 / 无需工具），另有 38 个 function-calling 工具定义 |
| 📅 **定时推送** | 天气、地震预警、校园通知、考试倒计时（scheduler 独立进程，**零 LLM 依赖**，欠费不影响） |
| 🖼 **图片识图** | MiMo 原生多模态，自然口语转述，空返回自动重试 |
| 💾 **三层记忆** | 会话记忆 / resume 摘要 / 长期笔记，跨 session 记得每个用户 |
| ❤️ **好感度引擎** | 亲密度随互动动态变化（六维雷达图），影响回复语气，像真人一样有温度 |
| ⏰ **定时提醒** | 自然语言设置提醒（"明早9点提醒我开会"），班级群/私聊均可 |
| 🩺 **健康自愈** | 服务崩溃自动重启、会话锁清理、内存/磁盘监控、熔断器防 LLM 故障雪崩、GONE 群自动恢复、admin 私信告警 |
| 🔒 **隐私安全** | 所有密钥走 `.env`，运行时数据（记忆/数据库/日志）全部 `.gitignore` 隔离 |

---

## 🏗 架构

```
QQ 群 / 私聊
    │
    ▼
NapCat (QQ 客户端, OneBot v11, WS :3001)
    │
    ▼
┌─────────────────────────────────────────────────────┐
│                bridge.py (消息桥接)                    │
│                                                      │
│  BATCH 合并 → 去重 → 安全过滤 → 识图                  │
│    → MiMo 工具路由 → 知识库注入 → 执行工具              │
│    → OpenClaw Agent 生成回复 → 分段发送               │
└──────────────┬──────────────────┬───────────────────┘
               │                  │
               ▼                  ▼
     OpenClaw Agent         scheduler_v5.py (独立进程)
     (mimo-v2.5 人格)       ├ 天气 / 地震 / 校园通知
               │            ├ 考试倒计时 / 定时消息
               ▼            └ GONE 容错 + 失败预算
     MiMo Proxy (:8898)
               │
               ▼
   OpenCode Go / 任意 OpenAI 兼容 API
```

**核心数据流**：

1. **对话**：消息 → 工具路由 → 知识库注入 → LLM 生成 → 分段发送
2. **订阅推送**：scheduler 独立循环 → 抓取外部数据 → 推送，**零 LLM 依赖**
3. **记忆**：每消息写入 session + resume 摘要 + 长期笔记（SQLite，`data/` 下运行时生成）

### 模块职责

| 模块 | 职责 |
|------|------|
| `bridge.py` | ★ 消息桥接主进程：批处理、安全过滤、LLM 调用、回复发送 |
| `scheduler_v5.py` | ★ 定时推送守护进程：天气 / 地震 / 校园通知 / 考试倒计时 / 定时消息 |
| `campus/` | 🏫 校园模块：CAS 登录、WebVPN 抓取、通知搜索与推送、招生 API |
| `search/` | 🔍 查询检索：知识库（BM25+语义）、分数、招生计划、论文、资源、网页搜索 |
| `admin/` | 🛠 运维管理：群配置、订阅、考试、定时消息、闹钟、健康检查、会话清理 |
| `tools/` | 🧰 通用工具：文档导出、文档转换、咨询网页、语音等 |
| `scripts/` | 🔧 shell 脚本（健康自愈 / 密钥扫描 / 启动）+ systemd 单元 |
| `src/llm/` | LLM 客户端、38 个 function-calling 工具定义与实现 |
| `src/memory/` | 三层记忆 + 8 维好感度引擎 |
| `src/plugins/` | NoneBot 插件：识图、抽签、新闻、人格、地震等 |
| `src/whut/` | WebVPN 客户端（CAS 自动登录） |
| `src/search/` | 多引擎网页搜索核心（百度/搜狗/必应/DDG） |

---

## 📦 项目结构

```
xiaonai/
├── bridge.py                 # ★ 消息桥接主进程（入口）
├── scheduler_v5.py           # ★ 定时推送守护进程（入口）
├── bot.py                    # NoneBot 入口（可选）
├── config.py                 # pydantic 配置（读取 .env）
├── campus/                   # 🏫 校园模块（CAS/WebVPN/招生/通知）
│   ├── campus_search.py      #   校园通知搜索
│   ├── campus_daily.py       #   校园通知每日推送
│   ├── webvpn_login.py       #   WebVPN 登录
│   └── ...
├── search/                   # 🔍 查询检索模块
│   ├── kb_manage.py          #   知识库管理（BM25+模糊）
│   ├── kb_semantic.py        #   语义搜索
│   ├── score_query.py        #   录取分数查询
│   ├── smart_search.py       #   7 源聚合搜索
│   ├── scholar_search.py     #   学术论文搜索
│   └── ...
├── admin/                    # 🛠 运维管理模块
│   ├── admin_cli.py          #   运维 CLI
│   ├── admin_group_control.py #  群配置管理
│   ├── health_check.sh 由 scripts/ 管理
│   ├── exam_countdown.py     #   考试倒计时
│   ├── timed_msg.py          #   定时消息
│   └── ...
├── tools/                    # 🧰 通用工具模块
│   ├── docx_export_helper.py #   文献 .docx 导出
│   ├── xiaonai_doc_tools_v2.py # 通用文档工具
│   ├── consultation_server.py #  招生咨询网页
│   └── ...
├── scripts/                  # 🔧 shell 脚本 + systemd 单元
│   ├── health_check.sh       #   健康自愈（cron）
│   ├── scan_secrets.sh       #   密钥泄露扫描
│   └── *.service             #   systemd 单元
├── src/                      # 📚 Python 包
│   ├── core/                 #   推理 / 反思 / 性能分析
│   ├── llm/                  #   LLM 客户端 + 38 工具定义（对话路由 9 类）
│   ├── memory/               #   记忆 + 8 维好感度引擎
│   ├── plugins/              #   NoneBot 插件
│   ├── search/               #   多引擎搜索核心
│   └── whut/                 #   WebVPN 客户端
├── docs/                     # 📖 文档（保姆教程/功能手册/架构/部署）
├── data/                     # 运行时数据（gitignored）
├── .env.example              # 环境变量模板
├── requirements.txt          # Python 依赖
└── CLAUDE.md                 # 给 AI 代码 Agent 的项目指南
```

---

## 🚀 快速开始

> 🍼 **完全没学过？一点不会？别怕！**
> 请先看 [**保姆级新手教程**](docs/BEGINNER-GUIDE.md) —— 从安装 Python 到机器人跑起来，每一步手把手教，附「怎么确认成功」和「失败了怎么办」。
> 下面是为有基础的同学准备的速查版。

### 前置要求

| 依赖 | 版本 |
|------|------|
| Python | 3.10+ |
| [NapCat](https://napneko.github.io/) | 最新（OneBot v11 WebSocket） |
| LLM API | OpenAI 兼容端点（默认 MiMo V2.5，任意提供商可用） |
| [OpenClaw](https://openclaw.ai)（可选） | Agent 引擎，驱动人格回复 |

### 1. 安装

```bash
git clone https://github.com/fieldlu/xiaonai.git
cd xiaonai
python3 -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置

```bash
cp .env.example .env
# 编辑 .env，填入：
#   MIMO_API_KEY        —— LLM API Key（必填）
#   BOT_ADMINS          —— 管理员 QQ 号（必填）
#   QW_API_KEY / QW_API_HOST —— 和风天气（可选，天气/预警推送用）
#   WHUT_USERNAME / WHUT_PASSWORD —— 校内系统（可选）
```

### 3. 启动 NapCat

按 [NapCat 文档](https://napneko.github.io/) 配置，确保 OneBot WS 监听 `127.0.0.1:3001`。

### 4. 启动机器人

```bash
python3 bridge.py          # 消息桥接（主进程）
python3 scheduler_v5.py    # 定时推送（可选，独立进程）
```

### 5. 自检

```bash
python3 admin/self_test.py --full      # 全链路自检（NapCat + Agent）
python3 search/smart_search.py "问题"   # 知识库检索测试
```

---

## 🔑 占位符替换（fork 后必做）

源码已把真实 QQ / 群号 / 密码替换为占位符。发布你自己的实例前，搜索并替换：

| 占位符 | 替换为 |
|--------|--------|
| `BOT_QQ_PLACEHOLDER` | 机器人自己的 QQ 号 |
| `ADMIN_QQ_PLACEHOLDER` | 管理员 QQ 号 |
| `CLASS_GROUP_PLACEHOLDER` | 需 @ 才回复的群号（class_groups，如班级正式群） |
| `CHAT_GROUP_PLACEHOLDER` | 无需 @ 主动聊天的群号（chat_groups，如日常交流群） |
| `TEST_GROUP_PLACEHOLDER` | 测试群号（test_group） |
| `WHUT_ACCOUNT_PLACEHOLDER` | (可选) 校内系统账号 |
| `WHUT_PASSWORD_PLACEHOLDER` | (可选) 校内系统密码 |
| `RESOURCE_EMAIL_PLACEHOLDER` | (可选) 资源站邮箱 |
| `RESOURCE_PASSWORD_PLACEHOLDER` | (可选) 资源站密码 |
| `YOUR_SCHOOL` / `YOUR_MAJOR` / `YOUR_CAMPUS` | 你的学校 / 专业 / 校区 |

```bash
# 示例：全局替换你的 QQ 号
grep -rl "ADMIN_QQ_PLACEHOLDER" . | xargs sed -i 's/ADMIN_QQ_PLACEHOLDER/你的QQ号/g'
```

> ⚠️ **安全提醒**：发布前请运行 `scripts/scan_secrets.sh`（或 CI 中的 secret 扫描），确认无 API Key / 真实账号信息入库。

## 👥 群配置（回复策略）

小奈在群里的回复行为按**群类型**区分（不是按群的"身份"，而是按小奈在群里的行为）。配置双写 `~/.openclaw/agents/main/agent/group_config.json` 与 `data/group_config.json`，改后热加载 bridge（`POST :8081/reload`）：

| 配置键 | 小奈的回复策略 | 管理命令 |
|--------|---------------|---------|
| `class_groups` | **需 @ 才回复**（被 @ / 被叫"小奈" / 发图片）——正式群/班级群 | `add_class_group 群号` |
| `normal_groups` | **需 @ 才回复**，与 class_groups 行为完全一致 | `add_normal_group 群号` |
| `chat_groups` | **无需 @，主动聊天**——日常交流群 | `add_chat_group 群号` |
| `blacklist` | **按用户 QQ 拉黑**（不是群），被拉黑者私聊/群聊一律不回 | `add_blacklist QQ号` |
| `mute_groups` | ⚠️ **不生效**：bridge 不读取此键，勿用 | `add_mute_group 群号` |

> ⚠️ **未配置的群：小奈完全忽略**（不回复，连 @ 也不回）。机器人被拉入新群会自动加入 `normal_groups`。
> 订阅推送不受群类型影响；推送目标在 `data/scheduler_config.json` 单独配置。

```bash
python3 admin/admin_group_control.py show_config        # 查看全部群类型 + 订阅状态（订阅问题先跑这条）
python3 admin/admin_group_control.py add_class_group 群号  # add_/remove_ 可换 chat/normal/blacklist
python3 admin/admin_group_control.py subscribe 群号 weather|news|earthquake|weather_warning|campus_daily|exam_countdown|all
```

数据存储（`data/group_config.json`，5 键）：
```json
{
  "class_groups": [123456789],
  "chat_groups": [123456790],
  "normal_groups": [],
  "mute_groups": [],
  "blacklist": []
}
```

---

## 🗄 部署

### systemd 生产部署

仓库自带 systemd 单元文件（`scripts/`），部署路径统一为 `/opt/xiaonai`：

```bash
sudo mkdir -p /opt/xiaonai
sudo cp -r . /opt/xiaonai/
sudo cp scripts/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiaonai-bridge xiaonai-scheduler
```

**健康自愈**：`health_check.sh` 提供 15 分钟粒度的自动巡检（服务重启、会话锁清理、内存/磁盘监控、admin 告警）：

```bash
# crontab
*/15 * * * * /opt/xiaonai/scripts/health_check.sh >> /var/log/health_check.log 2>&1
```

完整部署指南见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

---

## 📚 文档

| 文档 | 内容 |
|------|------|
| [docs/BEGINNER-GUIDE.md](docs/BEGINNER-GUIDE.md) | 🍼 保姆级新手教程（零基础从安装到跑起来） |
| [docs/FEATURES-GUIDE.md](docs/FEATURES-GUIDE.md) | 🧰 功能全览与配置手册（**40 个功能超详细版**：功能详解/配置/命令/数据存储） |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 完整架构、模块职责、数据流 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 生产部署（systemd）、健康自愈、监控 |
| [docs/KNOWLEDGE-BASE-GUIDE.md](docs/KNOWLEDGE-BASE-GUIDE.md) | 自建知识库（格式、检索、维护） |
| [docs/PERSONA-GUIDE.md](docs/PERSONA-GUIDE.md) | 人格配置（SOUL.md 体系） |
| [docs/TOOL-ROUTING.md](docs/TOOL-ROUTING.md) | 工具路由机制与自定义 |

## 🧪 测试

```bash
python3 admin/self_test.py --full       # 全链路自检（L1 NapCat + L3 Agent）
python3 search/smart_search.py "问题"     # 知识库检索测试
python3 admin/exam_countdown.py list     # 考试倒计时测试
python3 campus/campus_search.py "通知"    # 校园通知搜索测试
```

CI（GitHub Actions）自动执行：Ruff 代码检查 + 全量语法编译 + 密钥泄露扫描。

---

## 🤝 贡献

欢迎任何形式的贡献 —— Bug 修复、新工具、文档改进、人格调教经验分享！

1. Fork 本仓库
2. 新建分支 `feat/your-feature` 或 `fix/your-bugfix`
3. 提交改动（遵循 [Conventional Commits](https://www.conventionalcommits.org/)）
4. 发起 Pull Request

详细规范见 [CONTRIBUTING.md](CONTRIBUTING.md)。参与即代表同意 [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)。

---

## 🏫 学校接入说明

> **本项目是武汉理工大学（WHUT）定制版**，诞生于 WHUT 真实班级群，深度对接学校公开系统：
>
> | 校园模块 | 对接内容 | 相关文件 |
> |---------|---------|---------|
> | 统一身份认证 | CAS 登录 + WebVPN（RSA 加密密码、cookie 双兜底） | `src/whut/client.py`、`campus_search.py`、`webvpn_login.py` |
> | 招生数据 | 历年录取分数 / 位次 / 招生计划（官方 API） | `score_query.py`、`whut_score_api.py`、`zs_plan_query.py` |
> | 校园通知 | 本科生院 / 教务处 / 学院通知抓取与推送 | `campus_search.py`、`campus_daily.py` |
> | 校内页面 | WebVPN 编码抓取与正文解析 | `campus_fetch.py`、`src/whut/client.py` |

> 以上均为学校**公开官网域名**（whut.edu.cn），不含个人敏感信息。账号凭据一律走 `.env`，源码只有占位符。

**用于其他学校**：请替换相关模块——

- `campus_search.py` / `src/whut/client.py`：CAS 登录流程 → 改为你学校的统一身份认证
- `score_query.py` / `zs_plan_query.py`：招生数据 API → 改为你省/校的数据源
- `docs/KNOWLEDGE-BASE-GUIDE.md`：构建你自己的知识库

若不使用校园功能，忽略即可（相关模块不会被触发）。

若不使用校园功能，忽略即可（相关模块不会被触发）。

---

## ⚠️ 免责声明

- 本项目的知识库**不含任何真实学校 / 班级 / 个人信息**，仅提供格式示例。请勿上传他人隐私数据。
- 本项目仅用于学习交流。使用 NapCat / QQ 自动回复请遵守平台规则。
- 各外部 API（OpenCode / DeepSeek / QWeather 等）由使用者自行申请与计费。

---

## 📄 License

[GNU GPL v3.0](LICENSE) © 2026 XiaoNai contributors

> 本项目采用 **GPL-3.0** 开源协议：你可以自由使用、修改、分发，但**修改后的衍生作品也必须以 GPL-3.0 开源**（Copyleft）。详见 [LICENSE](LICENSE)。

---

<div align="center">

**如果你喜欢这个项目，给个 ⭐ Star 吧！**

[![GitHub stars](https://img.shields.io/github/stars/fieldlu/xiaonai?style=social)](https://github.com/fieldlu/xiaonai)

</div>
