# data/ 目录说明

本目录存放运行时数据，**已加入 .gitignore**，不会提交到仓库。

## 各子目录用途

| 路径 | 用途 |
|------|------|
| `knowledge/` | 知识库 markdown 文件（自建，见 docs/KNOWLEDGE-BASE-GUIDE.md） |
| `uploads/` | 上传文件临时目录（运行时生成） |
| `memory/` | 用户记忆文件（运行时生成，含隐私，不提交） |
| `*.json` | 各种状态/配置（group_config / scheduler_config / timed_msg 等） |
| `*.db` | SQLite 数据库（exams / xiaonai_memory 等） |

## 初始化

```bash
# 创建目录结构
mkdir -p data/knowledge data/uploads data/memory

# 放置你的知识库文件到 data/knowledge/
# 然后重建索引：
python3 rebuild_kb_index.py
```

> 知识库自建方法见 [docs/KNOWLEDGE-BASE-GUIDE.md](../docs/KNOWLEDGE-BASE-GUIDE.md)。
