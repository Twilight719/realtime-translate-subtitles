@echo off
chcp 65001 >nul
cd /d %~dp0
echo [1/3] 安装 PyInstaller...
.venv\Scripts\python -m pip install pyinstaller
echo.
echo [2/3] 准备构建环境（修复 Qt/原生库导入顺序冲突）...
copy /y tools\sitecustomize_pyi.py .venv\Lib\site-packages\sitecustomize.py >nul
set PYI_SAFE_IMPORT=1
echo.
echo [3/3] 开始打包（约 5~15 分钟）...
.venv\Scripts\python -m PyInstaller --noconfirm --clean subtitle.spec
echo.
echo 构建完成，输出目录: dist\实时翻译字幕\
pause
