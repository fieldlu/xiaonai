# Contributing to XiaoNai

首先，感谢你愿意为 XiaoNai（小奈）贡献代码！🎉

XiaoNai 从一个大学班级群里的实验性机器人成长为生产级项目，靠的是真实使用场景的打磨。你的每一个 PR 都在让这个项目更好。

## 目录

- [开发环境](#开发环境)
- [项目约定](#项目约定)
- [代码风格](#代码风格)
- [提交规范](#提交规范)
- [PR 流程](#pr-流程)
- [新增工具（Tool）](#新增工具tool)
- [安全](#安全)

## 开发环境

```bash
# 1. 克隆并安装依赖
git clone https://github.com/fieldlu/xiaonai.git
cd xiaonai
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt   # ruff / pytest / mypy

# 2. 配置环境变量
cp .env.example .env

# 3. 运行自检确认环境正常
python3 self_test.py --full
```

## 项目约定

- **单文件 200–400 行**：超出请拆分模块（`src/` 下的目录结构已按此组织）
- **配置驱动**：所有可变参数走 `.env` / `config.py`，禁止硬编码（API Key、群号、路径、超时）
- **类型注解**：所有函数必须有类型提示
- **日志**：用 `logging.getLogger(__name__)`，禁止 `print()` 调试残留
- **异常处理**：捕获具体异常类型，禁止裸 `except:`
- **依赖注入**：工具实现集中在 `src/llm/tools_impl.py`，定义在 `src/llm/tools.py`，新增工具两处都要改

## 代码风格

```bash
ruff check .          # Lint
ruff format --check . # Format
python3 -m compileall -q .  # 语法检查
```

提交前请确保以上命令全部通过。

## 提交规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/)：

```
feat: add exam archive command
fix: resolve weather API timeout retry loop
docs: update deployment guide for systemd
refactor: extract memory store from bridge.py
test: add parser unit tests
chore: bump requirements
```

## PR 流程

1. Fork 本仓库并创建分支：`feat/xxx`、`fix/xxx`、`docs/xxx`
2. 提交改动（保持每个 commit 小而聚焦）
3. 跑一遍本地验证（`ruff` + `compileall` + `self_test.py`）
4. 发起 PR，描述清楚：
   - 解决了什么问题
   - 改动如何工作（一句话）
   - 测试/验证情况
5. 等待 review。CI 会自动运行：语法检查 + Ruff + 密钥泄露扫描

**PR 大小**：建议单 PR < 400 行改动，方便 review。大改动请先开 issue 讨论。

## 新增工具（Tool）

工具系统是 XiaoNai 的核心。新增一个工具需要：

1. **`src/llm/tools.py`**：定义 JSON Schema（name / description / parameters）
   - description 写清楚**何时触发**和**调用示例**，LLM 靠它做意图路由
   - 示例参数用占位符（如 `张三`），不要用真实姓名/QQ
2. **`src/llm/tools_impl.py`**：实现函数并注册到 `TOOL_IMPL`
   - 保持幂等、可重试、有超时
3. **`docs/TOOL-ROUTING.md`**：补充路由说明
4. **`TOOLS.md`**（可选）：如果班长需要手动调用，补充 CLI 用法

## 安全

- **绝不提交** `.env`、`*.key`、`*.pem`、`*.db`、日志文件（已由 `.gitignore` 拦截）
- API Key 一律走环境变量，代码中只留 `.env.example` 占位符
- 真实 QQ 号 / 群号 / 姓名 / 密码 → 用 `*_PLACEHOLDER` 占位符
- 涉及校园系统的改动请特别谨慎：保持占位符脱敏，不要引入真实账号
- 发现敏感信息泄露，见 [SECURITY.md](SECURITY.md)

---

有任何问题，开 issue 或直接提 PR 讨论。感谢贡献！🌟
