@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

:: ============================================================
::  VibeMouse for Windows — 一键安装脚本
::  双击运行即可，全自动完成：
::    1. 检测/安装 Miniconda
::    2. 创建 Python 3.11 环境
::    3. 安装全部依赖
::    4. 下载语音识别模型
::    5. 生成启动脚本（自动适配路径）
::    6. 运行 doctor 自检
::    7. 可选：设置开机自启
:: ============================================================

title VibeMouse Installer

:: ---------- 路径变量 ----------
set "PROJECT_DIR=%~dp0"
:: 去掉末尾反斜杠
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "CONDA_DIR=%USERPROFILE%\miniconda3"
set "ENV_NAME=vibemouse"
set "ENV_DIR=%CONDA_DIR%\envs\%ENV_NAME%"
set "PYTHON=%ENV_DIR%\python.exe"
set "CONDA=%CONDA_DIR%\Scripts\conda.exe"
set "PIP=%PYTHON% -m pip"

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   VibeMouse for Windows — 一键安装       ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  项目目录: %PROJECT_DIR%
echo.

:: ============================================================
:: Step 1: 检测 / 安装 Miniconda
:: ============================================================
echo [1/7] 检测 Miniconda ...

if exist "%CONDA%" (
    echo       已找到: %CONDA%
    goto :conda_ready
)

echo       未找到 Miniconda，开始下载安装 ...
echo.

set "MINICONDA_URL=https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"
set "MINICONDA_EXE=%TEMP%\Miniconda3-latest-Windows-x86_64.exe"

:: 优先用 curl（Win10+自带），否则用 PowerShell
where curl >nul 2>&1
if %ERRORLEVEL%==0 (
    echo       正在下载 Miniconda（约 90MB）...
    curl -L -o "%MINICONDA_EXE%" "%MINICONDA_URL%"
) else (
    echo       正在下载 Miniconda（约 90MB，使用 PowerShell）...
    powershell -Command "Invoke-WebRequest -Uri '%MINICONDA_URL%' -OutFile '%MINICONDA_EXE%'"
)

if not exist "%MINICONDA_EXE%" (
    echo [错误] Miniconda 下载失败，请手动安装: https://docs.conda.io/en/latest/miniconda.html
    goto :error_exit
)

echo       正在安装 Miniconda 到 %CONDA_DIR% ...
start /wait "" "%MINICONDA_EXE%" /InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /S /D=%CONDA_DIR%

if not exist "%CONDA%" (
    echo [错误] Miniconda 安装失败
    goto :error_exit
)

echo       Miniconda 安装完成
del "%MINICONDA_EXE%" 2>nul

:conda_ready
echo       [OK]
echo.

:: ============================================================
:: Step 2: 创建 Python 3.11 环境
:: ============================================================
echo [2/7] 创建 Python 3.11 环境 (%ENV_NAME%) ...

if exist "%PYTHON%" (
    echo       环境已存在，跳过创建
    goto :env_ready
)

"%CONDA%" create -n %ENV_NAME% python=3.11 -y
if %ERRORLEVEL% neq 0 (
    echo [错误] 创建 conda 环境失败
    goto :error_exit
)

:env_ready
"%PYTHON%" --version
echo       [OK]
echo.

:: ============================================================
:: Step 3: 升级 pip
:: ============================================================
echo [3/7] 升级 pip ...
%PIP% install --upgrade pip --quiet
echo       [OK]
echo.

:: ============================================================
:: Step 4: 安装依赖
:: ============================================================
echo [4/7] 安装依赖（这一步需要几分钟，请耐心等待）...
echo.

echo       [4a] numpy 1.26.4 ...
%PIP% install "numpy==1.26.4" --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] numpy 安装失败
    goto :error_exit
)

echo       [4b] 基础依赖 ...
%PIP% install sounddevice soundfile pynput pyperclip jieba onnxruntime modelscope sentencepiece kaldi-native-fbank onnx --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] 基础依赖安装失败
    goto :error_exit
)

echo       [4c] librosa ...
%PIP% install librosa --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] librosa 安装失败
    goto :error_exit
)

echo       [4d] funasr-onnx ...
%PIP% install funasr-onnx --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] funasr-onnx 安装失败
    goto :error_exit
)

echo       [4e] PyTorch CPU 版 ...
%PIP% install torch --index-url https://download.pytorch.org/whl/cpu --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] PyTorch 安装失败
    goto :error_exit
)

echo       [4f] 安装 VibeMouse 本体 ...
%PIP% install -e "%PROJECT_DIR%" --no-deps --quiet
if %ERRORLEVEL% neq 0 (
    echo [错误] VibeMouse 安装失败
    goto :error_exit
)

echo       [OK] 全部依赖安装完成
echo.

:: ============================================================
:: Step 5: 下载语音识别模型
:: ============================================================
echo [5/7] 下载语音识别模型（首次约 230MB + 900MB）...

set "ONNX_DIR=%USERPROFILE%\.cache\modelscope\hub\models\iic\SenseVoiceSmall-onnx"
set "ORIG_DIR=%USERPROFILE%\.cache\modelscope\hub\models\iic\SenseVoiceSmall"
set "TOKENIZER=chn_jpn_yue_eng_ko_spectok.bpe.model"

:: 下载 ONNX 模型
if exist "%ONNX_DIR%\model_quant.onnx" (
    echo       ONNX 模型已存在，跳过
) else (
    echo       正在下载 ONNX 模型 ...
    "%PYTHON%" -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall-onnx')"
    if %ERRORLEVEL% neq 0 (
        echo [警告] ONNX 模型下载失败，首次运行时会自动重试
    )
)

:: 检查 tokenizer
if exist "%ONNX_DIR%\%TOKENIZER%" (
    echo       Tokenizer 已就位，跳过
    goto :model_ready
)

:: tokenizer 不在 ONNX 目录，尝试从原始模型复制或下载
if exist "%ORIG_DIR%\%TOKENIZER%" (
    echo       从原始模型复制 tokenizer ...
    copy "%ORIG_DIR%\%TOKENIZER%" "%ONNX_DIR%\%TOKENIZER%" >nul
    goto :model_ready
)

echo       正在下载原始模型以获取 tokenizer（约 900MB）...
"%PYTHON%" -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"

if exist "%ORIG_DIR%\%TOKENIZER%" (
    copy "%ORIG_DIR%\%TOKENIZER%" "%ONNX_DIR%\%TOKENIZER%" >nul
    echo       Tokenizer 已复制到 ONNX 目录
) else (
    echo [警告] Tokenizer 下载失败，可能需要手动处理
)

:model_ready
echo       [OK]
echo.

:: ============================================================
:: Step 6: 生成启动脚本（自动适配路径）
:: ============================================================
echo [6/7] 生成启动脚本 ...

:: start_vibemouse.bat
(
    echo @echo off
    echo title VibeMouse Voice Input
    echo echo Starting VibeMouse ...
    echo cd /d "%PROJECT_DIR%"
    echo "%PYTHON%" -m vibemouse.cli.main run
    echo pause
) > "%PROJECT_DIR%\start_vibemouse.bat"

:: start_vibemouse_silent.vbs
(
    echo Set WshShell = CreateObject^("WScript.Shell"^)
    echo WshShell.CurrentDirectory = "%PROJECT_DIR%"
    echo WshShell.Run """%PYTHON%"" -m vibemouse.cli.main run", 0, False
) > "%PROJECT_DIR%\start_vibemouse_silent.vbs"

echo       start_vibemouse.bat      — 有窗口启动（调试用）
echo       start_vibemouse_silent.vbs — 无窗口后台启动
echo       [OK]
echo.

:: ============================================================
:: Step 7: Doctor 自检
:: ============================================================
echo [7/7] 运行 doctor 自检 ...
echo.
"%PYTHON%" -m vibemouse.cli.main doctor
echo.

if %ERRORLEVEL% neq 0 (
    echo [警告] doctor 检测到问题，请检查上面的输出
) else (
    echo ══════════════════════════════════════════
    echo   安装完成！
    echo ══════════════════════════════════════════
)

:: ============================================================
:: 可选：开机自启
:: ============================================================
echo.
set /p "AUTOSTART=是否设置开机自启？(Y/N): "
if /i "%AUTOSTART%"=="Y" (
    set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
    copy "%PROJECT_DIR%\start_vibemouse_silent.vbs" "!STARTUP_DIR!\start_vibemouse_silent.vbs" >nul
    echo       已复制到启动文件夹，下次开机自动运行
    echo.
)

:: ============================================================
:: 启动
:: ============================================================
set /p "RUNNOW=现在启动 VibeMouse？(Y/N): "
if /i "%RUNNOW%"=="Y" (
    echo 正在启动 ...
    start "" wscript "%PROJECT_DIR%\start_vibemouse_silent.vbs"
    echo VibeMouse 已在后台运行
)

echo.
echo 按任意键退出 ...
pause >nul
exit /b 0

:error_exit
echo.
echo 安装失败，请检查上面的错误信息。
echo 如需帮助，请到 GitHub 提 Issue。
echo.
pause
exit /b 1
