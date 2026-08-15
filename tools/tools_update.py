import os, sys
path = os.path.expanduser("~/.openclaw/workspace/TOOLS.md")
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

priority_section = """## 信息检索优先级 —— 最高铁律

当用户提问需要查找资料/信息/规定/通知时，必须按以下顺序检索，前一步找到答案就不再继续：

### 步骤1: 本地知识库 (always first)
python3 /opt/xiaonai/search/kb_search.py "关键词"
  - 知识库位置: /opt/xiaonai/data/knowledge/ (150+ WHUT文档)
  - 如果kb_search找到结果，直接引用，不需要再查WebVPN或网页
  - 未找到时才进入步骤2

### 步骤2: WebVPN校内通知 (仅步骤1未找到时)
python3 /opt/xiaonai/campus/campus_search.py "关键词"
  - 如果失败或超时，先运行 python3 /opt/xiaonai/campus/webvpn_rsa_login.py 刷新ticket
  - 重试 campus_search.py
  - 如果还不通，进入步骤3

### 步骤3: 网页搜索 (最后手段)
  - 使用 web_fetch 或 WebSearch 工具
  - 仅在前两步都未找到时才使用

### 违规自检
- 收到问题先问自己：我搜了本地知识库吗？
- 如果没搜知识库就直接去webvpn/网页搜 → 违规，应立即纠正

"""

# Insert after the first heading line
lines = content.split("\n")
new_lines = []
inserted = False
for i, line in enumerate(lines):
    new_lines.append(line)
    # Insert after "## 核心原则：遇到错误不要放弃，立即尝试自救" section ends (next ##)
    if not inserted and line.startswith("## ") and i > 3:
        new_lines.append("")
        new_lines.append(priority_section.strip())
        inserted = True

new_content = "\n".join(new_lines)
with open(path, "w", encoding="utf-8") as f:
    f.write(new_content)
print("TOOLS.md updated successfully")
print(f"Priority section inserted: {inserted}")
