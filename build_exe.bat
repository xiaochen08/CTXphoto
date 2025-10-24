@echo off
chcp 65001 >nul
title 陈同学影像管理助手 打包工具
color 0a

echo.
echo ===============================================
echo   正在创建虚拟环境并安装依赖...
echo ===============================================
echo.

if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate

pip install --upgrade pip
pip install pyinstaller psutil pillow exifread winshell

echo.
echo ===============================================
echo   开始打包程序...
echo ===============================================
echo.

REM 生成单文件、隐藏控制台窗口、自定义图标
pyinstaller --onefile --windowed -i app.ico --name "影像管理助手" photo_sorter.py

echo.
echo ===============================================
echo   打包完成！
echo   输出文件：dist\影像管理助手.exe
echo ===============================================
echo.
pause
