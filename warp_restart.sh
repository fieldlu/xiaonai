#!/bin/bash
# warp-svc 每日重启（防 main-loop 卡死内存泄漏）+ 重启后验证 WebVPN 代理
# 由 cron 调用（每日 04:30 低峰）。备份留痕到 /var/log/warp_restart.log
LOG=/var/log/warp_restart.log

echo "=== $(date '+%F %T') warp restart ===" >> "$LOG"
sudo -n systemctl restart warp-svc 2>>"$LOG"

# warp-svc 初始化需要时间，最多重试 5 次、每次间隔 5s
RC=""
for i in 1 2 3 4 5; do
  sleep 5
  RC=$(curl -s --max-time 10 -x http://127.0.0.1:40000 http://www.whut.edu.cn/ -o /dev/null -w '%{http_code}' 2>>"$LOG")
  if [ "$RC" = "200" ]; then
    echo "  OK (retry $i): WebVPN 代理正常" >> "$LOG"
    exit 0
  fi
  echo "  attempt $i: HTTP $RC" >> "$LOG"
done
echo "  WARN: WebVPN 代理异常 (HTTP $RC after 5 tries)" >> "$LOG"
exit 1
