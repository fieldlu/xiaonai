# 工具路由机制

小奈的核心能力之一是 **MiMo 工具路由器**：每条消息先由 LLM 判断意图，再选择对应工具执行，把结果注入 prompt 让 Agent 回答。

---

## 一、工作流程

```
用户消息
  │
  ▼
MiMo 路由器（_route_tool_with_mimo）
  │  根据消息内容从 9 种工具中选一个
  │  输出 JSON: {"tool": "工具名", "query": "关键词"}
  ▼
执行对应工具 → 得到结果
  │
  ▼
注入 prompt（[SYSTEM OVERRIDE] 包裹）
  │
  ▼
Agent 基于注入数据 + 人格生成回答
```

## 二、9 种工具

| 工具 | 触发场景 | 执行函数 | 数据源 |
|------|---------|---------|--------|
| `score` | 录取分数/位次/能不能上 | `_exec_score` | `score_query.py` |
| `plan` | 招生计划/选科/名额 | `_exec_plan` | `zs_plan_query.py` |
| `campus` | 校园通知/教务通知 | `_exec_campus` | `campus_search.py` |
| `resource` | 课件/题库/复习资料 | `_exec_resource` | `resource_search.py` |
| `kb` | 知识库综合查询 | `_exec_kb` | `smart_search.py` |
| `exam` | 考试倒计时/还有几天 | `_exec_exam` | `exam_countdown.py` |
| `paper` | 论文/文献搜索 | `_exec_paper` | `scholar_search.py` |
| `remind` | 定时提醒 | `_exec_reminder` | `reminder_parser.py` |
| `none` | 闲聊/问候/无关 | 不注入 | — |

## 三、自定义工具

### 3.1 在 `bridge.py` 添加工具

1. **注册工具描述**（`_MIMO_TOOL_DESC` 数组）：

```python
_MIMO_TOOL_DESC = [
    # ... 现有工具 ...
    ("my_tool", "你的工具描述：什么场景触发"),
]
```

2. **写执行函数**（返回注入文本）：

```python
def _exec_my_tool(q, out):
    """你的工具：查询数据并注入。"""
    import subprocess, os as _os
    qqbot_dir = _os.path.dirname(__file__)
    try:
        r = subprocess.run(
            ["python3", _os.path.join(qqbot_dir, "my_data.py"), q[:80]],
            capture_output=True, text=True, timeout=15)
        if r.stdout and len(r.stdout.strip()) > 10:
            out.append("[我的工具结果]\n" + r.stdout.strip()[:2000])
    except Exception:
        pass
```

3. **加入路由分发**：

```python
elif tool == "my_tool": _exec_my_tool(q, out)
```

4. **更新 router prompt 选择规则**：

```python
system = (
    # ...
    "7. 你的工具触发条件 → my_tool\n"
)
```

### 3.2 工具设计原则

- **确定性优先**：能用脚本算的不要靠 LLM 猜
- **注入要标注来源**：`[SYSTEM OVERRIDE]` 包裹，让 Agent 知道数据可信
- **失败静默降级**：`try/except` 包裹，失败不阻塞对话
- **熔断保护**：高频失败的工具加熔断器

---

## 四、知识库工具的改写层

`kb` 工具特有 **MiMo 查询改写**：

```
口语问题「体育分是谁打的」
  → MiMo 改写为「体育成绩,评分标准,任课教师」
  → smart_search 用改写词检索 → 命中《体质健康标准》
```

**设计要点**：
- 只作用于 `kb` 工具（其他工具不需改写）
- 精确术语（培养方案/选课手册）跳过改写省 LLM
- 独立熔断 + 300s 缓存

---

## 五、故障处理

| 现象 | 原因 | 处理 |
|------|------|------|
| 工具不触发 | 路由分类错误 | 检查 `_MIMO_TOOL_DESC` 描述是否清晰 |
| 注入内容为空 | 底层脚本失败 | 看 `journalctl -u xiaonai-bridge` 的 `INJECT` 日志 |
| Agent 答非所问 | 注入数据未用 | 检查 `[SYSTEM OVERRIDE]` 包裹是否完整 |
| 工具反复失败 | 熔断触发 | 等 5 分钟冷却或修底层脚本 |
