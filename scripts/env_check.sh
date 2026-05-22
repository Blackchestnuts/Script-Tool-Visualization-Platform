#!/bin/bash
# 环境健康检查脚本 - 检测各服务连通性
# 用法: bash env_check.sh [--env=test_env|staging_env]

ENV=${1:-test_env}

echo "========================================"
echo "  环境健康检查"
echo "  环境: $ENV"
echo "  时间: $(date '+%Y-%m-%d %H:%M:%S')"
echo "========================================"
echo ""

# 检查项
check_http() {
    local url=$1
    local name=$2
    local status=$(curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 "$url" 2>/dev/null)
    if [ "$status" = "200" ] || [ "$status" = "301" ]; then
        echo "  [PASS] $name - HTTP $status"
    else
        echo "  [FAIL] $name - HTTP $status (预期 200)"
    fi
}

echo "--- HTTP 服务检查 ---"
check_http "https://www.baidu.com" "百度(外网)"
check_http "https://github.com" "GitHub"
echo ""

echo "--- 系统信息 ---"
echo "  主机名: $(hostname)"
echo "  当前用户: $(whoami)"
echo "  系统时间: $(date)"
echo "  磁盘使用:"
df -h / | tail -1 | awk '{print "    / 分区: 已用 "$3" / 总计 "$2" ("$5")"}'
echo ""

echo "========================================"
echo "  检查完成！"
echo "========================================"
