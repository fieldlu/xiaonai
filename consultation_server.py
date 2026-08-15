#!/usr/bin/env python3
"""Consultation Server — thin wrapper: Web UI + session context → OpenClaw Agent
Integrates existing tools: smart_search, score_query, kb_manage, whut-search
"""
import asyncio, json, time, logging, uuid, re as _re, os
from aiohttp import web
from pathlib import Path

log = logging.getLogger("consult")
logging.basicConfig(level=logging.INFO, format="[consult] %(asctime)s %(message)s")

PORT = 8082
sessions = {}
SESSION_TTL = 3600

PROVINCES = ["北京","天津","上海","重庆","河北","山西","辽宁","吉林","黑龙江",
    "江苏","浙江","安徽","福建","江西","山东","河南","湖北","湖南",
    "广东","海南","四川","贵州","云南","陕西","甘肃","青海",
    "内蒙古","广西","西藏","宁夏","新疆"]

def get_session(sid):
    now = time.time()
    for k in list(sessions):
        if now - sessions[k]["last"] > SESSION_TTL:
            del sessions[k]
    if sid not in sessions:
        sessions[sid] = {"created": now, "last": now, "ctx": {}}
    else:
        sessions[sid]["last"] = now
    return sessions[sid]

def update_ctx(msg, ctx):
    for p in PROVINCES:
        if p in msg:
            ctx["province"] = p
            break
    m = _re.search(r"(\d{3})\s*分", msg)
    if m:
        ctx["score"] = m.group(1)
    if "物理" in msg or "理科" in msg:
        ctx["subject"] = "物理类"
    elif "历史" in msg or "文科" in msg:
        ctx["subject"] = "历史类"

def build_msg(user_msg, ctx):
    parts = []
    for k, label in [("province", "省份"), ("score", "分数"), ("subject", "科类")]:
        if ctx.get(k):
            parts.append(f"[{label}: {ctx[k]}]")
    if parts:
        return "[上下文] " + " ".join(parts) + "\n\n" + user_msg
    return user_msg

async def call_agent(session_key, message, timeout=90):
    try:
        # Inject CONSULT.md system prompt
        _cp = os.path.expanduser("~/.openclaw/agents/main/agent/CONSULT.md")
        _pt = open(_cp).read() if os.path.exists(_cp) else ""
        full_msg = f"[系统指令]\n{_pt}\n\n[用户消息] {message}"
        proc = await asyncio.create_subprocess_exec(
            "openclaw", "agent", "--agent", "main",
            "--session-key", session_key,
            "--message", full_msg, "--json", "--timeout", str(timeout),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 10)
        if proc.returncode != 0:
            log.error("Agent: %s", stderr.decode(errors="replace")[:200])
            return None
        d = json.loads(stdout)
        if d.get("status") == "ok":
            for p in d.get("result", {}).get("payloads", []):
                t = p.get("text", "").strip()
                if t:
                    return t
        return None
    except Exception as e:
        log.error("Agent err: %s", str(e)[:200])
        return None

# --- Web UI ---
UI_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YOUR_SCHOOL招生咨询</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f0f4f8; min-height: 100vh; }
.header { background: linear-gradient(135deg, #1a5276, #2980b9); color: white; padding: 16px 24px; text-align: center; }
.header h1 { font-size: 1.3em; }
.header p { font-size: 0.85em; opacity: 0.85; margin-top: 4px; }
.container { max-width: 720px; margin: 0 auto; padding: 16px; }
.chat-box { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); min-height: 400px; max-height: 60vh; overflow-y: auto; padding: 20px; margin-bottom: 16px; }
.msg { margin-bottom: 16px; display: flex; gap: 10px; }
.msg.user { flex-direction: row-reverse; }
.msg .avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.1em; flex-shrink: 0; }
.msg.assistant .avatar { background: #2980b9; color: white; }
.msg.user .avatar { background: #27ae60; color: white; }
.msg .bubble { max-width: 80%; padding: 12px 16px; border-radius: 14px; line-height: 1.6; font-size: 0.95em; word-break: break-word; }
.msg.assistant .bubble { background: #f1f5f9; color: #1a202c; border-bottom-left-radius: 4px; }
.msg.user .bubble { background: #2980b9; color: white; border-bottom-right-radius: 4px; }
.input-area { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,0.06); padding: 16px; }
.quick-info { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.quick-info input, .quick-info select { flex: 1; min-width: 80px; padding: 8px 12px; border: 1px solid #e2e8f0; border-radius: 8px; font-size: 0.9em; }
.quick-info input:focus, .quick-info select:focus { outline: none; border-color: #2980b9; }
.input-row { display: flex; gap: 8px; }
.input-row textarea { flex: 1; padding: 10px 14px; border: 1px solid #e2e8f0; border-radius: 10px; font-size: 0.95em; resize: none; height: 48px; font-family: inherit; }
.input-row textarea:focus { outline: none; border-color: #2980b9; }
.input-row button { background: #2980b9; color: white; border: none; border-radius: 10px; padding: 0 20px; font-size: 0.95em; cursor: pointer; font-weight: 500; }
.input-row button:hover { background: #2471a3; }
.input-row button:disabled { opacity: 0.5; cursor: not-allowed; }
.info-bar { background: #fef3c7; border: 1px solid #fcd34d; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px; font-size: 0.85em; color: #92400e; }
</style>
</head>
<body>
<div class="header"><h1>YOUR_SCHOOL招生咨询</h1><p>AI 智能分析 · 历年数据参考 · 请以官方公布为准</p></div>
<div class="container">
<div class="info-bar">本助手基于历年招生数据提供分析参考，最终请以广西教育考试院和YOUR_SCHOOL本科招生网(zs.whut.edu.cn)为准。招办电话：027-87859017</div>
<div class="chat-box" id="chat"></div>
<div class="input-area">
<div class="quick-info">
<input type="text" id="province" placeholder="省份（如广西）">
<input type="text" id="score" placeholder="分数（如600）">
<select id="subject"><option value="">科类</option><option value="物理类">物理类</option><option value="历史类">历史类</option><option value="艺术类">艺术类</option></select>
</div>
<div class="input-row">
<textarea id="msg" placeholder="输入你的问题..." rows="1"></textarea>
<button id="send" onclick="sendMsg()">发送</button>
</div></div></div>
<script>
const SID = "web-"+Date.now()+"-"+Math.random().toString(36).slice(2,8);
let waiting = false;
document.getElementById("msg").addEventListener("keydown", function(e) {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMsg(); }
});
function addMsg(role, text) {
  const c = document.getElementById("chat");
  const d = document.createElement("div");
  d.className = "msg "+role;
  d.innerHTML = '<div class="avatar">'+(role==="user"?"&#x1F464;":"&#x1F393;")+'</div><div class="bubble">'+text.replace(/\n/g,"<br>")+'</div>';
  c.appendChild(d);
  c.scrollTop = c.scrollHeight;
}
async function sendMsg() {
  const m = document.getElementById("msg");
  const msg = m.value.trim();
  if (!msg || waiting) return;
  m.value = ""; waiting = true;
  document.getElementById("send").disabled = true;
  addMsg("user", msg);
  const ty = document.createElement("div");
  ty.id = "typing"; ty.style.cssText = "color:#94a3b8;font-style:italic;padding:12px";
  ty.textContent = "正在查询...";
  document.getElementById("chat").appendChild(ty);
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        session_id: SID,
        message: msg,
        province: document.getElementById("province").value.trim(),
        score: document.getElementById("score").value.trim(),
        subject: document.getElementById("subject").value
      })
    });
    const d = await r.json();
    document.getElementById("typing")?.remove();
    addMsg("assistant", d.ok ? d.response : "查询超时，请稍后再试~");
  } catch(e) {
    document.getElementById("typing")?.remove();
    addMsg("assistant", "网络错误，请重试~");
  }
  waiting = false;
  document.getElementById("send").disabled = false;
}
</script>
</body>
</html>"""

async def index(request):
    return web.Response(text=UI_HTML, content_type="text/html", charset="utf-8")

async def api_chat(request):
    try:
        body = await request.json()
        sid = body.get("session_id", str(uuid.uuid4()))
        msg = body.get("message", "").strip()
        if not msg:
            return web.json_response({"ok": False, "error": "empty"}, status=400)
        s = get_session(sid)
        ctx = s["ctx"]
        for k in ("province", "score", "subject"):
            v = body.get(k, "").strip()
            if v:
                ctx[k] = v
        update_ctx(msg, ctx)
        full_msg = build_msg(msg, ctx)
        agent_key = f"agent:main:consult-{sid}"
        log.info("Chat: sid=%s msg=%s ctx=%s", sid[:12], msg[:50], str(ctx))
        resp = await call_agent(agent_key, full_msg)
        if resp:
            return web.json_response({"ok": True, "response": resp})
        return web.json_response({"ok": False, "error": "timeout"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)[:200]}, status=500)

async def health(request):
    return web.json_response({"ok": True, "sessions": len(sessions)})

async def main():
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_post("/api/chat", api_chat)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Consult server on :%d", PORT)
    await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
