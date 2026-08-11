@echo off
chcp 65001 >nul
title VisionPower 视觉模型管理器
echo ============================================
echo   VisionPower 视觉模型管理器
echo   地址: http://127.0.0.1:17910
echo   按 Ctrl+C 退出
echo ============================================
python "%~dp0server.py"
pause
