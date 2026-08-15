"""DeepSeek function-calling tool definitions (OpenAI 格式)。"""

TOOLS = [
    # ---- 管理员工具 ----
    {
        "type": "function",
        "function": {
            "name": "admin_check_user",
            "description": "【管理员专用】查看指定 QQ 号用户的所有数据：记忆、好感度、昵称。当班长说'查一下xxx的好感度''看看xxx的数据'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "integer", "description": "要查询的 QQ 号"},
                },
                "required": ["qq"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "admin_set_affection",
            "description": "【管理员专用】直接设置指定用户的某个维度分数。当班长说'把xxx的好感度设为xx''把xxx的信任度调成xx'时调用。默认修改affection维度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "integer", "description": "QQ 号"},
                    "score": {"type": "integer", "description": "目标分值 0-100"},
                    "dimension": {
                        "type": "string",
                        "description": "维度key，默认affection。可选：affection/closeness/trust/tacit/dependency/understanding/protectiveness/sharing",
                    },
                },
                "required": ["qq", "score"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "admin_add_memory",
            "description": "【管理员专用】为指定用户手动添加一条记忆。当班长说'给xxx记住一件事'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "integer", "description": "QQ 号"},
                    "fact": {"type": "string", "description": "要记住的事实"},
                },
                "required": ["qq", "fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "admin_news_control",
            "description": "【管理员专用】控制推送。\n- push_campus=推送校园早报（校内通知+汽车学院新闻）。\n- push_now=推送普通新闻（163/人民网）。\n- add_group=把群加入早报推送列表。\ntarget_type: private=私聊推给某人, group=推到群里。用户说'发给我'→private, '发到群里'→group。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["enable", "disable", "add_recipient", "remove_recipient", "add_group", "remove_group", "set_time", "set_count", "show_config", "push_now", "push_campus", "remind", "set_custom_message"],
                        "description": "push_campus=校园早报(校内通知+学院新闻)，push_now=普通新闻",
                    },
                    "value": {
                        "type": "string",
                        "description": "目标QQ号或群号（push_campus/push_now时必填！）",
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["private", "group"],
                        "description": "private=私聊发给个人, group=发到群里。用户说'只发给我''私发'→private, 说'发到群里''推送到群'→group。默认根据上下文判断。",
                    },
                },
                "required": ["action"],
            },
        },
    },    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询任意城市的天气预报。当同学问天气时优先使用此工具。支持今天/明天/后天。返回温度、天气状况、风力、穿衣建议、是否带伞等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "城市名，如武汉、北京。默认武汉"
                    },
                    "day_offset": {
                        "type": "integer",
                        "description": "-1=近三天(推荐), 0=今天, 1=明天, 2=后天。默认-1"
                    }
                },
                "required": ["city"]
            }
        }
    },


    {
        "type": "function",
        "function": {
            "name": "admin_weather_control",
            "description": "【管理员专用】控制天气推送系统。仅班长用于开启/关闭每日天气推送、设置城市、管理推送对象。action: enable/disable/set_city/add_user/remove_user/add_group/remove_group/show_config。普通同学查天气请用 get_weather 工具，不要用此工具。action: push_now=推送天气, show_config=查看配置, set_city=改默认城市, enable/disable=开关。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["enable", "disable", "set_city", "show_config", "push_now"],
                        "description": "push_now=立即推送天气到当前群/用户",
                    },
                    "value": {
                        "type": "string",
                        "description": "城市名（set_city时必填），或目标QQ号/群号（push_now可选）",
                    },
                    "target_type": {
                        "type": "string",
                        "enum": ["private", "group"],
                        "description": "private=私聊发给个人, group=发到群里。默认根据上下文判断。",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "admin_send_message",
            "description": "【群通知/群发】发消息到指定QQ群。用户说群名对照：班级通知群=CLASS_GROUP_PLACEHOLDER，班级闲聊群=CHAT_GROUP_PLACEHOLDER，资料共享群=RESOURCE_GROUP_PLACEHOLDER。如果没指定群，先问发到哪个群。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "integer",
                        "description": "目标群QQ号。班级通知群=CLASS_GROUP_PLACEHOLDER，班级闲聊群=CHAT_GROUP_PLACEHOLDER，资料共享群=RESOURCE_GROUP_PLACEHOLDER。必须填具体群号！",
                    },
                    "message": {
                        "type": "string",
                        "description": "要发送的消息内容，会自动用小奈的语气发送",
                    },
                    "is_group": {
                        "type": "boolean",
                        "description": "是否是群消息，默认 false 表示私聊",
                    },
                },
                "required": ["target", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_alarm",
            "description": "设置闹钟/提醒。当用户说'明天8点叫我''10分钟后提醒我''下午3点提醒我开会'时调用。time_str 是时间，如'08:00'或'2026-05-16 14:30'。",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_str": {"type": "string", "description": "时间，格式 HH:MM 或 YYYY-MM-DD HH:MM"},
                    "message": {"type": "string", "description": "提醒内容，如'该吃药了''要开会了哦'"},
                },
                "required": ["time_str", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_alarms",
            "description": "查看当前所有闹钟。当用户问'我有几个闹钟''查看闹钟'时调用。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_alarm",
            "description": "取消闹钟。当用户说'取消闹钟''把8点的闹钟删了'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "alarm_id": {"type": "string", "description": "要取消的闹钟 ID，从 list_alarms 获取"},
                },
                "required": ["alarm_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_campus_notice",
            "description": "搜索YOUR_SCHOOL校内通知。当用户说'查校内通知''本科生院有什么通知''最近有什么通知'时调用。会自动搜索关键词并返回通知标题+链接。",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如'本科生院''考试''奖学金'，留空则返回最新通知",
                    },
                },
                "required": [],
            },
        },
    },
    # ---- 传话筒 ----
    {
        "type": "function",
        "function": {
            "name": "relay_message",
            "description": "【任何人可用】代用户传话给另一个人。隐私传话筒。如果用户没说是匿名还是实名，先问清楚再调用。anonymous=true=匿名(对方不知道谁说的), anonymous=false=实名(告知对方是谁说的)。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {
                        "type": "integer",
                        "description": "接收者的QQ号",
                    },
                    "message": {
                        "type": "string",
                        "description": "要转达的消息内容",
                    },
                    "anonymous": {
                        "type": "boolean",
                        "description": "true=匿名(对方不知道是谁说的), false=实名(告诉对方是谁说的)",
                    },
                },
                "required": ["qq", "message", "anonymous"],
            },
        },
    },
    # ---- 记忆工具 ----
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "记住用户告诉你的一件事。当用户说'记住...'、'帮我记一下...'或者分享了关于自己的信息时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "要记住的事实，用简洁的第三人称表述，如'喜欢喝奶茶'、'是计算机专业的学生'",
                    },
                },
                "required": ["fact"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "回忆关于当前用户的所有记忆。在对话开始时或需要了解用户背景时调用。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_affection",
            "description": "查看好感度和关系数据。默认查看当前对话者，也可以指定QQ号查看别人（任何人都可以查任何人的好感度）。当有人说'好感度''你喜不喜欢我''我们的关系''查一下xxx的好感度''看看xxx的数据'时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {
                        "type": "integer",
                        "description": "要查询的QQ号。如果用户说'看看xxx的好感度'且你知道xxx的QQ号就填，否则留0查当前用户。任何人都可以查任何人的好感度。",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_affection",
            "description": "调整对当前用户的某个维度分数。系统会自动微调，LLM在感知到特别事件时手动调整。delta范围-5到+5。dimension可选：affection(好感)/closeness(亲近)/trust(信任)/tacit(默契)/dependency(依赖)/understanding(了解)/protectiveness(守护)/sharing(分享)。默认affection。",
            "parameters": {
                "type": "object",
                "properties": {
                    "delta": {
                        "type": "integer",
                        "description": "变化值，范围 -5 到 +5",
                    },
                    "reason": {
                        "type": "string",
                        "description": "为什么调整，如'同学记得我的生日好感动'",
                    },
                    "dimension": {
                        "type": "string",
                        "description": "维度key，默认affection。可选：affection/closeness/trust/tacit/dependency/understanding/protectiveness/sharing",
                    },
                },
                "required": ["delta", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "group_lucky_draw",
            "description": "在群里随机抽签。同学说'抽几个人''帮我抽签''随机抽'时调用。count=抽几人(默认1)，exclude=用户指定的额外排除关键词(逗号分隔)。仅群聊可用。抽签完成后只说结果已发送，绝对不要提排除规则。",
            "parameters": {
                "type": "object",
                "properties": {
                    "count": {"type": "integer", "description": "抽几人，默认1，最多20"},
                    "exclude": {"type": "string", "description": "额外排除的关键词，逗号分隔，如'学委,支书'。默认已排除辅导员/班主任/班长无需再写。"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search your injected knowledge base. When asked about course content, exam topics, teacher info, or any topic that may have been injected into your knowledge base, you MUST call this tool first before using web_search. Only use web_search if this tool returns no results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query in Chinese, e.g. exam topics, course name, teacher name"
                    }
                },
                "required": ["query"]
            }
        }
    },

    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for current information. Use when knowledge is insufficient, unsure, or user explicitly asks to search. Works for news, facts, real-time data, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keywords"},
                    "num": {"type": "integer", "description": "Number of results, default 5, max 8"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_news",
            "description": "[ARTICLES+DESC] 获取今日新闻(含文章摘要)。当同学说查看新闻/有什么新闻/热点/重新发一遍时调用。返回新闻的标题和内容摘要。你必须按以下模板输出，每条都要写：\n大家下午好呀~小奈来播报今天的热点新闻啦(｡･ω･｡)\n1. [两个emoji] [标题]，小奈觉得[1-2句评论]~\n2. [两个emoji] [标题]，小奈希望[1-2句评论]~\n3. [两个emoji] [标题]，小奈觉得[1-2句评论]~\n4. [两个emoji] [标题]，小奈[动词][1-2句评论]~\n5. [两个emoji] [标题]，小奈相信[1-2句评论]~\n大家周一加油呀~\n这是新闻报道，可以写长一点，不受短聊规则限制。不要发到别处。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "fetch_url",
            "description": "Fetch and read the content of a URL/webpage. Use when a user sends a link and asks you to read it, summarize it, or tell them what's inside. Supports HTML pages, WeChat articles, news articles, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The URL to fetch and read"},
                },
                "required": ["url"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "deep_search",
            "description": "Deep multi-keyword search for complex questions. Automatically decomposes a question into multiple search queries, searches in parallel, deduplicates and ranks results. Use this INSTEAD OF web_search when the user asks a complex, multi-faceted, or nuanced question. Also use when web_search returns poor results. Works for research questions, comparisons, analysis, and topics requiring multiple perspectives.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The FULL original question or search topic, in natural language. Do NOT extract keywords - pass the complete question."},
                    "num": {"type": "integer", "description": "Number of results, default 8, max 10"},
                },
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "admin_inject_knowledge",
            "description": "将知识点注入知识库。管理员说「记住这些」「把这个加入知识库」时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "知识主题"},
                    "content": {"type": "string", "description": "知识内容"},
                },
                "required": ["topic", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_knowledge",
            "description": "列出知识库中已有的知识主题。",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_knowledge",
            "description": "删除知识库中的某个知识主题。",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "要删除的知识主题名称"},
                },
                "required": ["topic"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "ocr_image",
            "description": "OCR extract text from an image. When a user sends a picture, photo, screenshot, or any image containing text, use this tool to read the text from it. Supports Chinese and English. The image_url is the URL from the QQ [image:] or [CQ:image] message segment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "image_url": {"type": "string", "description": "The full URL of the image to OCR"},
                    "lang": {"type": "string", "description": "OCR language: chi_sim (Chinese), eng (English), chi_sim+eng (both). Default chi_sim+eng"},
                },
                "required": ["image_url"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "scrape_page",
            "description": "使用高级爬虫抓取网页。支持CSS选择器、Markdown转换、链接提取。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页URL"},
                    "selector": {"type": "string", "description": "CSS选择器，留空返回整页"},
                    "extract_mode": {"type": "string", "enum": ["text", "html", "markdown", "links"], "description": "提取模式"},
                },
                "required": ["url"],
            },
        },
    },


    {
        "type": "function",
        "function": {
            "name": "course_advisor",
            "description": "智能选课助手。同学询问选课建议、课程安排、学分规划、先修课检查、毕业进度等问题时调用。可以回答：某学期有哪些课、某门课的先修课是什么、某个方向要修多少学分、推荐选哪些选修课、已修了X课接下来该选什么等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "同学的选课相关问题，保持原话"},
                    "semester": {"type": "integer", "description": "同学当前所在的学期（1-8），不明确可不填"},
                    "direction": {"type": "string", "enum": ["智能网联汽车运用", "现代汽车智能服务", "未确定"], "description": "专业方向，不明确可不填"},
                    "completed_courses": {"type": "string", "description": "同学提到已修完的课程，逗号分隔，不明确可不填"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "disaster_control",
            "description": "灾害预警总控。用户说开启灾害预警/灾害订阅/打开灾害预警时调用，一次操作同时控制地震预警+气象预警。subscribe=同时开启地震和气象, unsubscribe=同时关闭, status=查看全部状态",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["subscribe", "unsubscribe", "status"],
                        "description": "subscribe=开启全部灾害预警, unsubscribe=关闭, status=状态",
                    },
                },
                "required": ["action"],
            },
        },
    },
                {
        "type": "function",
        "function": {
            "name": "earthquake_control",
            "description": "地震预警专用工具。用户说打开地震预警/开启地震预警/订阅地震/关闭地震预警/地震状态时，直接调用本工具即可，本工具本身完成全部操作，不需要再调用任何发消息工具。subscribe=开启, unsubscribe=关闭, status=查询",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["subscribe", "unsubscribe", "status"],
                        "description": "subscribe=开启地震预警, unsubscribe=关闭, status=查询状态",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "weather_control",
            "description": "气象预警专用工具。用户说打开气象预警/开启气象预警/订阅气象/关闭气象预警/气象状态时，直接调用本工具即可，本工具本身完成全部操作，不需要再调用任何发消息工具。subscribe=开启, unsubscribe=关闭, status=查询。注意：如果需要同时控制地震+气象，请用disaster_control",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["subscribe", "unsubscribe", "status"],
                        "description": "subscribe=开启气象预警, unsubscribe=关闭, status=查询状态",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "teacher_advisor",
            "description": "智能教师查询助手。同学询问老师的研究方向、职称、邮箱、个人简介、教育背景等。可回答：某老师研究什么、某方向有哪些老师、找导师建议等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "同学的教师相关问题，保持原话"},
                    "teacher_name": {"type": "string", "description": "具体老师姓名，不明确可不填"},
                    "research_interest": {"type": "string", "description": "感兴趣的研究方向，不明确可不填"},
                },
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_classmate",
            "description": "【私聊通知】按姓名查找同学并发送私聊通知。当有人说通知某人/告诉某人/转告某人时调用（默认走私聊）。只有用户说发到群里/在群里通知时，才用admin_send_message发班级群。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "要通知的同学姓名，必须与通讯录中的姓名完全一致（如张三、李四）",
                    },
                    "message": {
                        "type": "string",
                        "description": "要发送的通知/转告内容，会以班长的口吻发送",
                    },
                },
                "required": ["name", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "notify_all",
            "description": "【分别群发】给通讯录里每个人逐个发送私聊通知。只有当用户明确说分别通知所有人/逐个私聊时才调用。如果只是说通知全体同学/群发通知，用admin_send_message发到群里。",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "要群发的通知内容",
                    },
                },
                "required": ["message"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "admin_group_control",
            "description": "【管理员专用】群配置管理。管理小奈在哪些群回复、哪些群拉黑。add_class_group=设为班级群(静默，仅@回复), remove_class_group=取消班级群, add_chat_group=设为闲聊群(主动聊天), remove_chat_group=取消闲聊群, add_blacklist=拉黑群(完全不回), remove_blacklist=取消拉黑, show_config=查看当前配置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add_class_group", "remove_class_group", "add_chat_group", "remove_chat_group", "add_normal_group", "remove_normal_group", "add_mute_group", "remove_mute_group", "add_blacklist", "remove_blacklist", "show_config"],
                        "description": "操作类型：add_class_group=静默模式(仅@才回), add_chat_group=正常聊天, add_blacklist=拉黑, show_config=查看配置",
                    },
                    "value": {
                        "type": "string",
                        "description": "操作目标群号。add/remove操作必填群号，show_config可不填。",
                    },
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "news_control",
            "description": "新闻订阅管理。用户说订阅新闻/退订新闻/新闻状态时调用。subscribe=订阅, unsubscribe=退订, status=查询状态。本工具完成全部操作，不需要再调用发消息工具。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["subscribe", "unsubscribe", "status"],
                        "description": "subscribe=订阅, unsubscribe=退订, status=查询状态",
                    },
                },
                "required": ["action"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "sing_song",
            "description": "唱一首歌。当同学要求'唱歌''唱首歌''唱一首XX''来一首歌'时调用此工具。如果曲库有这首歌就播放，没有的话会返回可选歌曲列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "song_query": {"type": "string", "description": "歌曲名称或描述，如'小幸运''周杰伦的歌''一首开心的歌'"},
                },
                "required": ["song_query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
        "type": "function",
        "function": {
            "name": "say_voice",
            "description": "用语音朗读一段文字并发送给指定用户。当同学要求'读出来'、'念给我听'、'说一遍'、'给某人发语音'时使用。target_qq为0则发送到当前对话。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要朗读的文字内容"},
                    "target_qq": {"type": "integer", "description": "接收语音的QQ号，私聊用。填0则发送到当前对话"},
                    "voice": {"type": "string", "description": "音色选择: xiaoxiao(温柔女声,默认), yunyang(专业男声), yunxi(阳光男声), xiaoyi(活泼女声), yunjian(激情男声), yunxia(可爱男声), liaoning(东北话), shaanxi(陕西话)"},
                    "style": {"type": "string", "description": "情绪风格: general(默认), cheerful(开心), sad(悲伤), angry(愤怒), excited(兴奋), gentle(温柔), fearful(害怕), calm(平静)"},
                },
                "required": ["text"],
            },
        },
    },
    },
]