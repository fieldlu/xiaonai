# XiaoNai 部署指南

## 一、环境要求

| 项 | 要求 |
|----|------|
| OS | Linux（推荐 Ubuntu 22.04+） |
| Python | 3.10+ |
| 内存 | ≥1GB（含 NapCat 需 2GB+） |
| QQ 客户端 | NapCat（提供 OneBot WebSocket） |
| LLM API | OpenAI 兼容端点（默认 MiMo/OpenCode Go） |

## 二、安装步骤

> ⚠️ **部署目录约定**：本项目所有路径（数据文件、子脚本调用、cron、systemd）已统一为 `/opt/xiaonai`，请将代码部署到该目录：

```bash
sudo mkdir -p /opt/xiaonai
sudo cp -r . /opt/xiaonai/     # 或直接 git clone 到该目录
```

> 旧部署迁移：把原部署目录移到约定位置，旧引用保持可用：
>
> ```bash
> sudo mv <旧部署目录> /opt/xiaonai
> sudo ln -s /opt/xiaonai <旧部署目录>
> ```

### 1. 系统依赖

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv
```

### 2. 克隆项目

```bash
git clone https://github.com/fieldlu/xiaonai.git
cd xiaonai
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 安装 NapCat

按照 [NapCat 官方文档](https://napneko.github.io/) 安装。核心配置：

- OneBot WebSocket 监听：`127.0.0.1:3001`
- 协议版本：OneBot v11

### 4. 安装 OpenClaw（Agent 引擎）

```bash
# 安装（详见 https://openclaw.ai）
npm install -g openclaw
openclaw doctor
```

配置模型 provider（OpenClaw 的 `openclaw.json`）：

```json
{
  "models": {
    "providers": {
      "mimo": {
        "baseUrl": "http://127.0.0.1:8898",
        "apiKey": "YOUR_API_KEY",
        "api": "openai-completions",
        "models": [{ "id": "mimo-v2.5", "input": ["text", "image"] }]
      }
    }
  }
}
```

### 5. 配置 .env

```bash
cp .env.example .env
vim .env   # 填入 API key / QQ 号
```

### 6. 配置人格文件

```bash
# 把 SOUL.md / IDENTITY.md / TOOLS.md 等放到 OpenClaw workspace
# 详细见 docs/PERSONA-GUIDE.md
```

### 7. 构建知识库

```bash
# 把你的知识文档放入 data/knowledge/ 目录（.md 格式）
# 详细见 docs/KNOWLEDGE-BASE-GUIDE.md

python3 search/rebuild_kb_index.py   # 构建 BM25 + 语义索引
python3 search/smart_search.py "测试查询"  # 验证
```

### 8. 启动

```bash
python3 bridge.py          # 消息桥接（前台，或见下 systemd）
python3 scheduler_v5.py    # 定时推送（可选）
```

---

## 三、生产部署（systemd）

### bridge.service

```ini
[Unit]
Description=XiaoNai Bridge
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/xiaonai
ExecStart=/opt/xiaonai/venv/bin/python3 /opt/xiaonai/bridge.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### scheduler.service

```ini
[Unit]
Description=XiaoNai Scheduler
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/xiaonai
ExecStart=/opt/xiaonai/venv/bin/python3 /opt/xiaonai/scheduler_v5.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo cp *.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiaonai-bridge xiaonai-scheduler
```

---

## 四、健康自愈

`health_check.sh` 提供自动化巡检（cron 每 15 分钟）：

```bash
# 加入 crontab
*/15 * * * * /opt/xiaonai/scripts/health_check.sh >> /var/log/health_check.log 2>&1
```

**能力**：
- 重启死掉的服务（systemctl）
- 清理会话锁（PID 校验，防误杀）
- 内存/磁盘监控
- admin 私信通知

---

## 五、常见问题

### NapCat 收不到消息

- 确认 OneBot WS 端口正确（默认 3001）
- 检查 `bridge.py` 的 `WS_HOST/WS_PORT` 是否与 NapCat 一致

### LLM 回复「没组织好」

- 检查 API key / base_url 是否可用
- 看日志 `journalctl -u xiaonai-bridge` 里 `MiMo router` 是否正常路由

### 知识库检索不到

- 确认 `data/knowledge/` 有 `.md` 文件
- 重新 `python3 search/rebuild_kb_index.py`

### 定时推送没发

- 确认 `data/scheduler_config.json` 的 `groups` 填了群号
- 检查 `logs/scheduler.log`
