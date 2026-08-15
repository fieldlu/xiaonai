# 小奈工具手册 — 命令速查

**测试群**: TEST_GROUP_PLACEHOLDER — 所有测试消息、诊断输出、运行日志都发到这个群。
生产消息（天气/新闻/校园通知）仍走原有配置群（CLASS_GROUP_PLACEHOLDER）。

---

## 工具选择速查表（回答前先看这里）

| 用户问... | 用这个工具 |
|-----------|-----------|
| 录取分数/专业/位次 | score_query.py |
| 学校政策/通知/机构 | kb_manage.py search |
| **学术论文/文献/研究/综述/最新进展/前沿/技术资料** | **scholar_search.py search** |
| 找文献/查论文/搜研究/关于XXX的研究 | scholar_search.py search |
| 歌词/歌名 | smart_search（自动触发） |
| 车辆/VIN/车型 | smart_search（自动触发） |
| 天气 | 内置天气API |
| 新闻 | 内置新闻API |
| 校园通知 | campus_search.py |
| 校内网页内容 | campus_fetch.py |
| 资料/课件/试卷 | resource_search.py |
| 通用搜索/不确定 | smart_search（自动） |
| 管理员/运维 | admin_cli.py |
| 群配置 | admin_group_control.py |

**速查表没覆盖的** -> 往下翻找到对应工具，或用 smart_search。

---

## 架构铁律（不可违反）

### scheduler_v5.py 是 systemd 守护进程
- scheduler_v5.py 是长驻守护进程，**永远不要加进 crontab**
- 它自己有一个 while True + asyncio.sleep(10) 主循环
- 加到 crontab 每分钟启动一次，会导致多个实例堆积 -> 内存爆 -> 服务器卡死
- 检查 scheduler 状态: systemctl status xiaonai-scheduler
- 重启 scheduler: sudo systemctl restart xiaonai-scheduler

### campus_daily 故障处理
- campus_daily failed: 没有错误信息 -> 检查 campus_search.py 的 proxy 配置
- 手动跑 python3 /opt/xiaonai/campus_daily.py 看真实报错

---

## 工具详细说明

### 0. 录取分数 score_query
python3 /opt/xiaonai/score_query.py list
python3 /opt/xiaonai/score_query.py 广西 材料 2025 --score 595
问分数/录取/专业时，**必须**先用这个工具。

### 1. 学术论文搜索 scholar_search（9源并发）
python3 /opt/xiaonai/scholar_search.py search 关键词 --rows 5
覆盖: Semantic Scholar, OpenAlex, CrossRef, PubMed, arXiv, CORE, Europe PMC, DOAJ, dblp
**问论文/文献/研究时必须用这个工具，禁止凭训练语料编造论文**

### 2. 知识库 kb_manage
python3 /opt/xiaonai/kb_manage.py search 关键词
python3 /opt/xiaonai/kb_manage.py add 主题 内容
python3 /opt/xiaonai/kb_manage.py view 主题

### 3. 校园通知 campus_search
python3 /opt/xiaonai/campus_search.py 关键词

### 4. 校内链接 campus_fetch
python3 /opt/xiaonai/campus_fetch.py http://i.whut.edu.cn/...

### 5. 资源站 resource_search
python3 /opt/xiaonai/resource_search.py 关键词

### 6. 网页搜索 searxng
内置在 smart_search 中自动触发。通过 localhost:8899 代理。

### 7. 天气/新闻/地震（直接调 API，没有封装工具）
天气: curl -s "https://$QW_API_HOST/weather/7d?key=$QW_API_KEY&location=101200101"（host/key 在 .env 的 QW_API_HOST / QW_API_KEY）
新闻: curl -s https://news.nowind.cn/api/hot?type=all
地震: curl -s https://api.wolfx.jp/cenc_eqlist.json
注意: get_weather / get_news 是旧架构留下的工具名，现在已经不存在了，别去调，直接用上面的 curl。

### 8. 群配置 admin_group_control
查看配置（群类型 + 全部订阅状态；订阅相关问题一律先跑这条）:
python3 /opt/xiaonai/admin_group_control.py show_config
群类型增删（5 类：class_group 需被@ / chat_group 不需@ / normal_group / mute_group 禁言 / blacklist 黑名单）:
python3 /opt/xiaonai/admin_group_control.py add_class_group 群号
python3 /opt/xiaonai/admin_group_control.py remove_class_group 群号
（add_ / remove_ 后面换成 chat_group、normal_group、mute_group、blacklist 用法相同）
订阅增删（必须写明确的群号，不能写"当前群"）:
python3 /opt/xiaonai/admin_group_control.py subscribe 群号 weather|news|earthquake|weather_warning|campus_daily|exam_countdown|all
python3 /opt/xiaonai/admin_group_control.py unsubscribe 群号 同上

### 9. 管理命令 admin_cli
python3 /opt/xiaonai/admin_cli.py status
python3 /opt/xiaonai/admin_cli.py diag
python3 /opt/xiaonai/admin_cli.py restart qq|bridge|scheduler|searxng|openclaw|all
python3 /opt/xiaonai/admin_cli.py cron list|add|rm|run
也可以直接用 systemd 重启（xiaonai-* 是 root 系统单元，必须 sudo）:
sudo systemctl restart xiaonai-bridge  （另有 xiaonai-qq / xiaonai-scheduler / xiaonai-consult / xiaonai-http-proxy）
systemctl --user restart openclaw-gateway  （openclaw-gateway 和 mimo-proxy 是用户单元，不要加 sudo）
会话清理（cron 每 5 分钟自动跑，一般不用手动）:
python3 /opt/xiaonai/session_cleaner_v2.py --force
注意: session_cleaner.py（v1）是 13 行空壳，已废弃，别用。

### 10. 考试倒计时 exam_countdown
python3 /opt/xiaonai/exam_countdown.py add 考试名 YYYY-MM-DD
python3 /opt/xiaonai/exam_countdown.py days 考试名

### 11. 闹钟 alarm_manager
python3 /opt/xiaonai/alarm_manager.py set 08:00 内容

### 12. 抽签 lucky_draw
python3 /opt/xiaonai/lucky_draw_cli.py 群号 [人数]

### 13. 文件读写 xiaonai_doc_tools
python3 /opt/xiaonai/xiaonai_doc_tools_v2.py read 路径

### 14. QQ消息发送 send_qq_msg
python3 /opt/xiaonai/send_qq_msg.py --group 群号 --message 内容

---

## 新集成工具（2026-06-05 新增）

### 学术论文搜索（OpenAlex）
scholar_search.py 直连 OpenAlex API（全球2.44亿+论文），支持中文搜索、摘要、引用数、期刊名。
用法: scholar_search.py search <关键词> --rows 10
| 导出文献为 .docx / 导出报告 / 生成文档 | docx_export_helper.py search（需先搜索文献，再询问用户确认后执行） |
| 通用AI搜索/帮我查一下/搜索网络 | ai_search.py search（360/搜狗/Bing三引擎） |

## 学术论文搜索 — Scholar MCP（9源并发）


覆盖 **9 个学术数据库**，一次搜索自动去重排序：
- ✅ **Semantic Scholar** — 语义搜索，引用数据
- ✅ **OpenAlex** — 开放学术图谱
- ✅ **CrossRef** — 正规期刊论文
- ✅ **PubMed** — 生物医学
- ✅ **arXiv** — 预印本
- ✅ **CORE** — 开放获取论文
- ✅ **Europe PMC** — 生命科学
- ✅ **DOAJ** — 开放获取期刊
- ✅ **dblp** — 计算机科学

每条返回：标题、作者、年份、来源、DOI

注意：**别再调 kb_search 查论文了**，学术相关的问题一律用 Scholar MCP。

### 示例
用户问帮我查一下深度强化学习的最新论文
→ 你跑 
→ 把返回的论文标题+作者+年份读给用户

### 中文文献搜索（重要）
查询**中文论文/中文文献**，同样用 Scholar MCP：



Scholar MCP 的 **OpenAlex** 和 **CORE** 数据库收录了大量中文期刊论文（包括中英文双语元数据），
搜索中文关键词即可返回结果。例如搜自动驾驶会返回中文论文标题+作者。

注意：**知网(CNKI)从本服务器无法直接访问**（CAPTCHA拦截），但 OpenAlex 覆盖了大部分正规中文期刊。
如果需要知网独家收录的文献，建议通过学校图书馆网站手动检索。

---

## YOUR_SCHOOL网站速查（2024-07-20 admin 提供）

### 校内系统
| 名称 | 地址 |
|------|------|
| 图书馆 | http://lib.whut.edu.cn/ |
| 综合教务系统 | http://sso.jwc.whut.edu.cn/Certification/toIndex.do |
| 理工智课 | https://whut.ai-augmented.com/home |
| 财务处 | http://jcc.whut.edu.cn/ |
| 体育学院 | http://sports.whut.edu.cn/ |
| 信息化办公室 | http://xxhb.whut.edu.cn/ |
| 网络信息中心 | https://nic.whut.edu.cn/ |
| 邮件系统 | https://mail.whut.edu.cn |
| VPN | https://webvpn.whut.edu.cn/ |
| 后勤集团 | http://pub.whut.edu.cn/hqjt/ |
| 一卡通指南 | https://nic.whut.edu.cn/fwzn/202311/t20231108_948576.shtml |

### 常用网站
| 名称 | 地址 |
|------|------|
| 智慧理工大 | https://zhlgd.whut.edu.cn |
| 教务系统 | jwxt.whut.edu.cn |
| 学校信息网站（需校园网） | http://i.whut.edu.cn/xxtg/ |
| 本科生院 | http://jwc.whut.edu.cn/ |
