# Security Policy

## 支持范围（Supported Versions）

| 版本 | 支持 |
|------|------|
| 0.x（main 分支） | ✅ 接受安全报告 |
| 更早版本 | ❌ 不维护 |

## 报告漏洞（Reporting a Vulnerability）

**请不要**在公开 issue 中报告安全问题（特别是涉及密钥 / 账号泄露的）。

请通过以下任一渠道**私密**报告：

1. **GitHub Security Advisory**：在仓库页面 → *Security* → *Report a vulnerability*
2. **私信仓库维护者**：通过 QQ / 邮件联系（见仓库主页信息）

报告时请包含：

- 受影响文件与行号（或最小复现片段）
- 漏洞类型与潜在影响
- （如果涉及泄露）泄露的内容类型：API Key / 账号密码 / 个人信息 / 路径信息

我们会在 **72 小时内**回复确认，并尽快修复。

## 密钥泄露应急流程（如误提交）

1. **立即轮换**：去对应平台（和风天气 / OpenCode / DeepSeek…）重置该 Key
2. **清除历史**：用 [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/) 或 `git filter-repo` 从全部历史中移除
3. **强制推送** 清理后的历史
4. 验证旧 Key 已失效

## 安全基线（本项目承诺）

- ✅ 所有密钥通过 `.env` 注入，`.env` / `.env.*` 已 `.gitignore`
- ✅ 源码不含真实 QQ 号 / 群号 / 姓名 / 密码（全部为 `*_PLACEHOLDER`）
- ✅ 运行时数据（数据库 / 记忆 / 日志 / 上传文件）不入库
- ✅ CI 自动执行密钥泄露扫描（`scripts/scan_secrets.sh`）
- ✅ 所有 HTTP 客户端有超时；校园系统凭据加密传输（RSA / CAS）

## 已知非安全问题

以下内容**不是**漏洞，无需报告：

- 学校公开域名（whut.edu.cn）及相关公开接口 URL
- 公开信息（如高校公开的招生办电话）
- WebVPN 编码常量（任何访问者均可从公开网页 JS 获取）
