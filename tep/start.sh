#!/bin/bash
# 测试效能平台 TEP V1.0 启动脚本

echo "================================================"
echo "  测试效能平台 TEP V1.0"
echo "  正在启动服务..."
echo "================================================"

# 切换到脚本所在目录
cd "$(dirname "$0")"

# 检查依赖
if ! python -c "import fastapi" 2>/dev/null; then
    echo "正在安装依赖..."
    pip install -r requirements.txt
fi

# 启动服务
echo ""
echo "访问地址: http://localhost:8000"
echo "API 文档: http://localhost:8000/docs"
echo ""
echo "按 Ctrl+C 停止服务"
echo "================================================"

python main.py
