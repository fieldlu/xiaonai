#!/usr/bin/env bash
# ============================================================
# scan_secrets.sh — 发布前敏感信息扫描
#
# 用途:
#   1. 本地发布前自检:   bash scripts/scan_secrets.sh
#   2. CI 密钥门禁:      由 .github/workflows/ci.yml 调用
#
# 检查项:
#   - 常见 API Key / Token 格式（OpenAI / GitHub / AWS / Google / Slack）
#   - 私钥文件与硬编码 32 位十六进制 Key
#   - 真实 .env / 凭据文件
#   - 手机号 / 用户目录路径残留
#
# 退出码: 0 = 干净，1 = 发现可疑内容
# ============================================================
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

# 排除自身与运行时目录
EXCLUDE=(
  --exclude-dir=.git
  --exclude-dir=data
  --exclude-dir=logs
  --exclude-dir=venv
  --exclude-dir=.venv
  --exclude-dir=node_modules
  --exclude-dir=__pycache__
  --exclude=*.db
  --exclude=*.log
  --exclude=*.pkl
  --exclude=*.pyc
  --exclude=scan_secrets.sh
)

INCLUDES=(
  --include='*.py' --include='*.sh' --include='*.md'
  --include='*.toml' --include='*.json' --include='*.yaml'
  --include='*.yml' --include='*.txt'
)

FOUND=0

# 引号字符（避免在 grep ERE 中使用不可移植的 \x27 转义）
DQ='"'
SQ="'"

check() {
  local pattern="$1" label="$2"
  local hits
  hits="$(grep -rInE --color=never "${EXCLUDE[@]}" "${INCLUDES[@]}" "$pattern" . 2>/dev/null)"
  if [ -n "$hits" ]; then
    echo "❌ [$label] 发现可疑内容："
    echo "$hits"
    FOUND=1
  else
    echo "✅ [$label] 通过"
  fi
}

echo "===== XiaoNai 密钥/敏感信息扫描 ====="
echo

check 'sk-[A-Za-z0-9_\-]{16,}'               'OpenAI 风格 API Key'
check 'ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{20,}' 'GitHub Token'
check 'AKIA[0-9A-Z]{16}'                       'AWS Access Key'
check 'AIza[0-9A-Za-z_-]{30,}'                 'Google API Key'
check 'xox[baprs]-[A-Za-z0-9-]{10,}'           'Slack Token'
check '-----BEGIN [A-Z ]*PRIVATE KEY-----'     '私钥块'
check '1[3-9][0-9]{9}'                         '手机号'
check '/home/[a-z][a-z0-9_-]*/'                '用户目录路径'
check '(KEY|SECRET|TOKEN|PASSWORD|PASS)[^A-Za-z0-9_][^'"$DQ"']*'"$DQ"'[0-9a-f]{32}'"$DQ"'' '硬编码 32 位十六进制 Key'
check '(KEY|SECRET|TOKEN|PASSWORD|PASS)[^A-Za-z0-9_][^'"$SQ"']*'"$SQ"'[0-9a-f]{32}'"$SQ"'' '硬编码 32 位十六进制 Key (单引号)'
check 'MIMO_API_KEY[^A-Za-z0-9_][^'"$DQ"']*'"$DQ"'[^'"$DQ"']{6,}'"$DQ"'' 'MiMo API Key'
check 'DEEPSEEK_API_KEY[^A-Za-z0-9_][^'"$DQ"']*'"$DQ"'[^'"$DQ"']{6,}'"$DQ"'' 'DeepSeek API Key'

echo
echo "----- 凭据文件检查 -----"
CRED_FILES="$(find . -type f \( -name '.env' -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' -o -name 'credentials.json' -o -name 'exec-approvals.json' \) \
  -not -path './.git/*' -not -path './venv/*' -not -path './.venv/*' -not -name '.env.example' 2>/dev/null)"
if [ -n "$CRED_FILES" ]; then
  echo "❌ [凭据文件] 发现："
  echo "$CRED_FILES"
  FOUND=1
else
  echo "✅ [凭据文件] 通过"
fi

echo
if [ "$FOUND" -eq 0 ]; then
  echo "🎉 扫描完成：未发现敏感信息，可以发布！"
else
  echo "🚨 扫描完成：发现可疑内容，请在发布前处理（API Key 请立即轮换）。"
fi
exit "$FOUND"
