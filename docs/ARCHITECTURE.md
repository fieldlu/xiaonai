# XiaoNai 架构文档

## 一、总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                        QQ 群 / 私聊                           │
└───────────────────────────┬─────────────────────────────────┘
                            │ OneBot WS
                            ▼
                    ┌───────────────┐
                    │   NapCat      │  QQ 客户端（登录 + OneBot 协议）
                    │  (127.0.0.1:3001)│
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
    ┌─────────────────┐ ┌──────────┐ ┌────────────────┐
    │   bridge.py     │ │ scheduler │ │  onebot_http   │
    │  (消息桥接 :8080)│ │ _v5.py    │ │  _proxy        │
    │                 │ │ (订阅推送) │ │  (HTTP 代理)   │
    └────────┬────────┘ └────┬─────┘ └────────────────┘
             │               │
             ▼               ▼
    ┌─────────────────┐ ┌──────────┐
    │   OpenClaw      │ │  NapCat  │
    │   Agent 引擎    │ │  → 群    │
    │   (mimo-v2.5)   │ │          │
    └────────┬────────┘ └──────────┘
             │
             ▼
    ┌─────────────────┐
    │  mimo-proxy     │  MiMo 推理代理（缓存/thinking 控制）
    │  (127.0.0.1:8898)│
    └────────┬────────┘
             ▼
    ┌─────────────────┐
    │ OpenCode Go API │  或任意 OpenAI 兼容端点
    └─────────────────┘
```

## 二、模块职责

### 2.1 顶层模块

| 模块 | 职责 |
|------|------|
| `bridge.py` | **核心消息桥接**：WS 收消息 → 批量合并 → 识图 → 工具路由 → Agent 生成 → 分段发送 |
| `scheduler_v5.py` | **定时推送**：天气/地震/校园/考试倒计时，独立于对话，零 LLM 依赖 |
| `smart_search.py` | **多路知识检索**：BM25 + 语义 TF-IDF + 分数/计划/校园 API 聚合 |
| `kb_manage.py` | 知识库 CRUD + BM25 索引构建/搜索 |
| `kb_semantic.py` | 字符 n-gram TF-IDF 语义索引（无外部依赖） |
| `exam_countdown.py` | 考试倒计时（add/delete/list/days/push） |
| `reminder_parser.py` | 自然语言定时提醒解析 |
| `strip_md.py` | 回复清洗链（markdown/链接/敏感/思考泄漏） |
| `sanitizer.py` | 输入安全过滤（注入/攻击模式） |
| `health_check.sh` | 健康巡检 + 自愈（systemd/cron） |
| `self_test.py` | 全链路诊断探针 |

### 2.2 src/ 包

```
src/
├── core/          # 推理清洗、反射器、性能分析
├── llm/           # LLM 客户端、工具调用实现
├── memory/        # 记忆系统（情绪/好感/分层存储）
├── plugins/       # 功能插件（天气/地震/抽签/搜索/识图/人格）
├── search/        # 搜索抽象（解析器/引擎）
└── whut/          # 校园网访问客户端（可选）
```

## 三、消息处理流水线

```
1. NapCat WS 收到消息（直连 :3001）
2. BATCH 合并（0.5s 去抖 + 晚加入合并）
3. MiMo Vision 识图（多模态，后台任务 + 占位符）
4. 消息去重（120s 窗口）
5. 群静默检测（class_group 需 @）
6. sanitize_message（过滤注入/攻击）
7. MiMo 工具路由 → 选工具 → 执行注入
   ├ 微信链接 → wechat_fetch.py（确定性）
   ├ 培养方案 → _exec_course（按学期切块）
   ├ 知识库 → MiMo 查询改写 → smart_search
   └ 工具失败 → 回退正则
8. call_openclaw（重试 4 次，90s 超时，重试换内容避缓存）
9. 回复清洗链（strip_markdown → ... → strip_thinking_leak）
10. 分段发送（引号未闭合自动合并）
```

## 四、工具路由

MiMo 根据用户消息选择工具（`_MIMO_TOOL_DESC`）：

| 工具 | 触发 | 执行 |
|------|------|------|
| `score` | 录取分数/位次/稳不稳 | `_exec_score` → score_query |
| `plan` | 招生计划/选科/名额 | `_exec_plan` → zs_plan_query |
| `campus` | 校园通知/教务通知 | `_exec_campus` → campus_search |
| `resource` | 课件/题库/资料 | `_exec_resource` → resource_search |
| `kb` | 知识库综合查询 | `_exec_kb` → smart_search（+改写） |
| `exam` | 考试倒计时/还有几天 | `_exec_exam` → exam_countdown |
| `paper` | 论文/文献搜索 | `_exec_paper` → scholar_search |
| `remind` | 定时提醒 | parse_reminder → _exec_reminder |
| `none` | 闲聊/问候 | 不注入 |

**熔断机制**：每类工具调用有独立熔断器（3 次失败禁 5 分钟），防 LLM 故障雪崩。

## 五、知识库检索

```
用户口语问题
    │
    ▼
MiMo 查询改写（口语→检索关键词）
    │
    ▼
smart_search.py 多路聚合
    ├─ BM25 关键词层（jieba 分词）
    ├─ 字符 n-gram TF-IDF 语义层
    ├─ 分数 API / 招生计划 API / 校园通知 API
    └─ 置信度加权 + 去重
    │
    ▼
注入 prompt → Agent 生成回答
```

**关键设计**：
- 改写层只作用于 `kb` 工具；精确术语（培养方案/选课手册）跳过改写省 LLM
- 改写有独立熔断 + 300s 缓存
- 索引由 `rebuild_kb_index.py` 统一重建（BM25 + semantic）

## 六、记忆系统（三层）

| 层 | 位置 | 生命周期 | 谁读它 |
|----|------|---------|--------|
| ① 会话 session | `sessions/<uuid>.*` | 短，cron 每 5 分钟清 idle | OpenClaw |
| ② resume 摘要 | `agent/resume_<key>.json` | 长期，7 天 | bridge 每消息注入 |
| ③ 长期笔记 | `workspace/memory/YYYY-MM-DD.md` | 长期 | agent 自己 |

## 七、订阅推送（scheduler）

```
scheduler_v5.py（asyncio 主循环）
  ├─ weather_forecast()   每天 07:00 → QWeather
  ├─ check_weather_warning 每 10 分钟 → QWeather alert
  ├─ fetch_campus_daily()  每 2 分钟 → 校园通知
  ├─ 地震预警              每 30 秒 → api.wolfx.jp
  └─ 定时消息              循环 → timed_msg.json
        │
        ▼
   send_with_retry → NapCat → 目标群
        ├─ GONE 群降级单次尝试（成功自动恢复）
        ├─ 错误预算（失败上限，超限 skip）
        └─ 状态记录 scheduler_state.json
```

## 八、健康自愈

- **health_check.sh**（cron 每 15 分钟）：服务重启、会话锁清理、磁盘/内存监控、admin 通知
- **熔断体系**：router / kb_rewrite / vision 三类独立熔断
- **GONE 群容错**：失效群单次尝试 + 自动恢复
- **进程保活**：systemd `Restart=always`
