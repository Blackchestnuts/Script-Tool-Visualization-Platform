@echo off
REM Windows 环境信息采集脚本
REM 用法: bat env_info.bat

echo ========================================
echo   Windows 环境信息采集
echo ========================================
echo.

echo --- 系统信息 ---
echo   计算机名: %COMPUTERNAME%
echo   用户名: %USERNAME%
echo   系统目录: %SystemRoot%
echo   当前时间: %date% %time%
echo.

echo --- 网络信息 ---
ipconfig | findstr /i "IPv4"
echo.

echo --- 磁盘信息 ---
wmic logicaldisk get caption,freespace,size /format:list 2>nul
echo.

echo --- Python 环境 ---
python --version 2>nul || echo   Python 未安装
pip --version 2>nul || echo   pip 未安装
echo.

echo ========================================
echo   信息采集完成！
echo ========================================
