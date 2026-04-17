# ============================================================
#  VibeMouse for Windows — 一行命令安装
#
#  用法（在 PowerShell 或 cmd 中任选一种）:
#
#  PowerShell:
#    irm https://raw.githubusercontent.com/gongyuhang2023-cpu/VibeMouse_for_Windows/main/install.ps1 | iex
#
#  CMD:
#    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/gongyuhang2023-cpu/VibeMouse_for_Windows/main/install.ps1 | iex"
#
#  全自动完成:
#    1. 下载项目（无需 git）
#    2. 检测/安装 Miniconda
#    3. 创建 Python 3.11 环境 + 安装依赖
#    4. 下载语音识别模型
#    5. 生成启动脚本 + doctor 自检
#    6. 可选开机自启
# ============================================================

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# ---------- 配置 ----------
$REPO_URL   = "https://github.com/gongyuhang2023-cpu/VibeMouse_for_Windows/archive/refs/heads/master.zip"
$INSTALL_DIR = "$env:USERPROFILE\VibeMouse_for_Windows"
$CONDA_DIR   = "$env:USERPROFILE\miniconda3"
$ENV_NAME    = "vibemouse"
$ENV_DIR     = "$CONDA_DIR\envs\$ENV_NAME"
$PYTHON      = "$ENV_DIR\python.exe"
$CONDA       = "$CONDA_DIR\Scripts\conda.exe"
$MINICONDA_URL = "https://repo.anaconda.com/miniconda/Miniconda3-latest-Windows-x86_64.exe"

function Write-Step($num, $total, $msg) {
    Write-Host "`n[$num/$total] $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "       [OK] $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "       [!] $msg" -ForegroundColor Yellow
}

function Exit-WithError($msg) {
    Write-Host "`n[ERROR] $msg" -ForegroundColor Red
    Write-Host "`nPress any key to exit ..."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# ============================================================

Write-Host ""
Write-Host "  ============================================" -ForegroundColor Magenta
Write-Host "   VibeMouse for Windows  —  One-Line Install" -ForegroundColor Magenta
Write-Host "  ============================================" -ForegroundColor Magenta
Write-Host ""

$totalSteps = 7

# ============================================================
# Step 1: 下载项目
# ============================================================
Write-Step 1 $totalSteps "Download project files ..."

if (Test-Path "$INSTALL_DIR\vibemouse\__init__.py") {
    Write-Ok "Already exists at $INSTALL_DIR, skip download"
} else {
    $zipPath = "$env:TEMP\vibemouse_download.zip"
    $extractPath = "$env:TEMP\vibemouse_extract"

    Write-Host "       Downloading from GitHub ..."
    Invoke-WebRequest -Uri $REPO_URL -OutFile $zipPath -UseBasicParsing

    if (-not (Test-Path $zipPath)) {
        Exit-WithError "Download failed"
    }

    Write-Host "       Extracting ..."
    if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

    # GitHub ZIP extracts to a subfolder like VibeMouse_for_Windows-main
    $innerDir = Get-ChildItem $extractPath -Directory | Select-Object -First 1
    if (-not $innerDir) {
        Exit-WithError "ZIP extraction failed — no inner directory found"
    }

    if (Test-Path $INSTALL_DIR) { Remove-Item $INSTALL_DIR -Recurse -Force }
    Move-Item $innerDir.FullName $INSTALL_DIR

    # Cleanup
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
    Remove-Item $extractPath -Recurse -Force -ErrorAction SilentlyContinue

    Write-Ok "Installed to $INSTALL_DIR"
}

# ============================================================
# Step 2: Miniconda
# ============================================================
Write-Step 2 $totalSteps "Check / install Miniconda ..."

if (Test-Path $CONDA) {
    Write-Ok "Found $CONDA"
} else {
    Write-Host "       Miniconda not found, downloading (~90MB) ..."
    $condaExe = "$env:TEMP\Miniconda3-installer.exe"
    Invoke-WebRequest -Uri $MINICONDA_URL -OutFile $condaExe -UseBasicParsing

    if (-not (Test-Path $condaExe)) {
        Exit-WithError "Miniconda download failed"
    }

    Write-Host "       Installing Miniconda to $CONDA_DIR (this may take a minute) ..."
    Start-Process -FilePath $condaExe -ArgumentList "/InstallationType=JustMe","/RegisterPython=0","/AddToPath=0","/S","/D=$CONDA_DIR" -Wait -NoNewWindow

    if (-not (Test-Path $CONDA)) {
        Exit-WithError "Miniconda install failed"
    }

    Remove-Item $condaExe -Force -ErrorAction SilentlyContinue
    Write-Ok "Miniconda installed"
}

# ============================================================
# Step 3: Conda environment
# ============================================================
Write-Step 3 $totalSteps "Create Python 3.11 environment ($ENV_NAME) ..."

if (Test-Path $PYTHON) {
    $pyVer = & $PYTHON --version 2>&1
    Write-Ok "Environment exists: $pyVer"
} else {
    & $CONDA create -n $ENV_NAME python=3.11 -y
    if ($LASTEXITCODE -ne 0) { Exit-WithError "Failed to create conda environment" }
    Write-Ok "Environment created"
}

# ============================================================
# Step 4: Install dependencies
# ============================================================
Write-Step 4 $totalSteps "Install dependencies (this takes a few minutes) ..."

function Pip-Install($desc, $pkgArgs) {
    Write-Host "       $desc ..."
    $pipArgs = @("-m", "pip", "install") + $pkgArgs + @("--quiet")
    & $PYTHON @pipArgs
    if ($LASTEXITCODE -ne 0) { Exit-WithError "Failed: $desc" }
}

Pip-Install "pip upgrade"      @("--upgrade", "pip")
Pip-Install "numpy 1.26.4"    @("numpy==1.26.4")
Pip-Install "core deps"       @("sounddevice", "soundfile", "pynput", "pyperclip", "jieba",
                                 "onnxruntime", "modelscope", "sentencepiece",
                                 "kaldi-native-fbank", "onnx")
Pip-Install "librosa"         @("librosa")
Pip-Install "funasr-onnx"     @("funasr-onnx")
Pip-Install "PyTorch CPU"     @("torch", "--index-url", "https://download.pytorch.org/whl/cpu")
Pip-Install "VibeMouse"       @("-e", $INSTALL_DIR, "--no-deps")

Write-Ok "All dependencies installed"

# ============================================================
# Step 5: Download model
# ============================================================
Write-Step 5 $totalSteps "Download speech recognition model ..."

$onnxDir   = "$env:USERPROFILE\.cache\modelscope\hub\models\iic\SenseVoiceSmall-onnx"
$origDir   = "$env:USERPROFILE\.cache\modelscope\hub\models\iic\SenseVoiceSmall"
$tokenizer = "chn_jpn_yue_eng_ko_spectok.bpe.model"

# ONNX model
if (Test-Path "$onnxDir\model_quant.onnx") {
    Write-Host "       ONNX model exists, skip"
} else {
    Write-Host "       Downloading ONNX model (~230MB) ..."
    & $PYTHON -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall-onnx')"
}

# Tokenizer
if (Test-Path "$onnxDir\$tokenizer") {
    Write-Host "       Tokenizer ready"
} elseif (Test-Path "$origDir\$tokenizer") {
    Write-Host "       Copying tokenizer from original model ..."
    Copy-Item "$origDir\$tokenizer" "$onnxDir\$tokenizer"
} else {
    Write-Host "       Downloading original model for tokenizer (~900MB) ..."
    & $PYTHON -c "from modelscope.hub.snapshot_download import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"
    if (Test-Path "$origDir\$tokenizer") {
        Copy-Item "$origDir\$tokenizer" "$onnxDir\$tokenizer"
    } else {
        Write-Warn "Tokenizer download failed, may need manual fix"
    }
}

Write-Ok "Model ready"

# ============================================================
# Step 6: Generate launcher scripts
# ============================================================
Write-Step 6 $totalSteps "Generate launcher scripts ..."

# Write without BOM — VBScript rejects UTF-8 BOM with error 800A0408 ("invalid character")
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

# .bat
$batContent = @"
@echo off
title VibeMouse Voice Input
echo Starting VibeMouse ...
cd /d "$INSTALL_DIR"
"$PYTHON" -m vibemouse.cli.main run
pause
"@
[System.IO.File]::WriteAllText("$INSTALL_DIR\start_vibemouse.bat", $batContent, $utf8NoBom)

# .vbs
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$INSTALL_DIR"
WshShell.Run """$PYTHON"" -m vibemouse.cli.main run", 0, False
"@
[System.IO.File]::WriteAllText("$INSTALL_DIR\start_vibemouse_silent.vbs", $vbsContent, $utf8NoBom)

Write-Ok "start_vibemouse.bat (windowed) + start_vibemouse_silent.vbs (silent)"

# ============================================================
# Step 7: Doctor check
# ============================================================
Write-Step 7 $totalSteps "Doctor self-check ..."
Write-Host ""
& $PYTHON -m vibemouse.cli.main doctor

# ============================================================
# Done!
# ============================================================
Write-Host ""
Write-Host "  ============================================" -ForegroundColor Green
Write-Host "       Installation complete!" -ForegroundColor Green
Write-Host "  ============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Location:  $INSTALL_DIR" -ForegroundColor White
Write-Host "  Start:     double-click start_vibemouse.bat" -ForegroundColor White
Write-Host "  Silent:    double-click start_vibemouse_silent.vbs" -ForegroundColor White
Write-Host ""

# Auto-start?
$autostart = Read-Host "  Set up auto-start on boot? (Y/N)"
if ($autostart -eq "Y" -or $autostart -eq "y") {
    $startupDir = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
    Copy-Item "$INSTALL_DIR\start_vibemouse_silent.vbs" "$startupDir\start_vibemouse_silent.vbs" -Force
    Write-Ok "Added to Windows Startup folder"
}

# Run now?
$runnow = Read-Host "  Launch VibeMouse now? (Y/N)"
if ($runnow -eq "Y" -or $runnow -eq "y") {
    Start-Process "wscript.exe" -ArgumentList "`"$INSTALL_DIR\start_vibemouse_silent.vbs`""
    Write-Ok "VibeMouse is running in background"
}

Write-Host ""
Write-Host "  Press any key to exit ..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
