# VibeMouse for Windows

鼠标侧键语音输入工具 — 按一下鼠标，说话即输入。

基于 [VibeMouse](https://github.com/vimalinx/VibeMouse) 改造，移除 OpenClaw/Hyprland 依赖，适配 Windows。

## 功能

- **按鼠标前侧键**开始录音，再按一次停止 → 语音自动转文字并粘贴到光标处
- **按鼠标后侧键**发送 Enter
- **5 种语言自动识别**：中文、English、粤语、日本語、한국어，无需手动切换
- **完全离线**：语音识别模型（SenseVoice）在本地运行，不需要网络，隐私安全
- 任何能输入文字的地方都能用 — 记事本、浏览器、微信、IDE、终端等

## 安装

### 方式一：一键安装（推荐）

无需预装 Python、Git 或任何工具，打开 PowerShell 粘贴一行命令即可：

```powershell
irm https://raw.githubusercontent.com/gongyuhang2023-cpu/VibeMouse_for_Windows/master/install.ps1 | iex
```

<details>
<summary>也可以在 CMD 中运行</summary>

```cmd
powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/gongyuhang2023-cpu/VibeMouse_for_Windows/master/install.ps1 | iex"
```

</details>

脚本全自动完成：下载项目 → 安装 Miniconda → 创建 Python 3.11 环境 → 安装依赖 → 下载模型 → 自检 → 可选开机自启。

> **⚠️ Python 版本说明**：本项目需要 **Python 3.10 ~ 3.12**。Python 3.13+ 因 numpy ABI 不兼容会导致模型加载崩溃（segfault）。一键安装脚本已自动使用 Python 3.11，无需手动处理。

### 方式二：手动安装

<details>
<summary>点击展开手动安装步骤</summary>

#### 1. 环境要求

- Windows 10/11
- **Python 3.10 ~ 3.12**（推荐用 [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 管理）
- 带侧键的鼠标

> ⚠️ **不要使用 Python 3.13+**：`funasr-onnx` 的 C 扩展按 numpy 1.x ABI 编译，Python 3.13 上 numpy 1.x 无预编译 wheel，pip 会安装 numpy 2.x，导致模型加载时 segfault。

#### 2. 创建环境

```bash
# 推荐用 conda 创建隔离环境
conda create -n vibemouse python=3.11 -y
conda activate vibemouse
```

#### 3. 克隆项目

```bash
git clone https://github.com/gongyuhang2023-cpu/VibeMouse_for_Windows.git
cd VibeMouse_for_Windows
```

#### 4. 安装依赖

```bash
# 先锁定 numpy 版本（关键！）
pip install "numpy==1.26.4"

# 基础依赖
pip install sounddevice soundfile pynput pyperclip jieba onnxruntime modelscope sentencepiece kaldi-native-fbank onnx

# librosa
pip install librosa

# funasr-onnx
pip install funasr-onnx

# PyTorch（CPU 版本，约 115MB）
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 安装项目本体
pip install -e . --no-deps
```

#### 5. 下载语音识别模型

首次启动会从 ModelScope 自动下载 ONNX 模型（约 230MB）。

如果 tokenizer 文件缺失（日志提示 `chn_jpn_yue_eng_ko_spectok.bpe.model is missing`），运行：

```bash
python -c "from modelscope import snapshot_download; snapshot_download('iic/SenseVoiceSmall')"
```

tokenizer 文件会自动复制到 ONNX 模型目录。

#### 6. 验证安装

```bash
python -m vibemouse.cli.main doctor
```

三项全部 `[OK]` 即可使用。

</details>

## 使用

### 启动

```bash
# 方式一：命令行启动（可看日志）
python -m vibemouse.cli.main run

# 方式二：双击 start_vibemouse.bat（有窗口）

# 方式三：双击 start_vibemouse_silent.vbs（无窗口后台运行）
```

### 操作

| 操作 | 效果 |
|------|------|
| 按**前侧键** | 开始录音（再按一次停止，自动识别并粘贴） |
| 按**后侧键** | 发送 Enter |
| 右键 | 正常使用，不受影响 |

### 关闭

后台运行时，打开任务管理器，结束 `python.exe` 进程即可。

## 开机自启

将 `start_vibemouse_silent.vbs` 复制到 Windows 启动文件夹：

```
%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\
```

或按 `Win+R`，输入 `shell:startup`，将 `start_vibemouse_silent.vbs` 粘贴进去。

下次开机后 VibeMouse 会自动在后台运行，桌面不会弹出窗口。

取消自启：从启动文件夹删除该文件即可。

## 按键映射

默认配置 `front=x2, rear=x1`。如果你的鼠标侧键映射不同，可以用测试脚本确认：

```bash
python test_buttons.py
```

如需交换，修改 `vibemouse/config/schema.py` 中 `build_default_config_document()` 的 `front_button` 和 `rear_button` 值。

## 配置

配置文件路径：`%APPDATA%\vibemouse\config.json`

也可通过环境变量覆盖：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VIBEMOUSE_LANGUAGE` | `auto` | 识别语言（`auto`/`zh`/`en`/`yue`/`ja`/`ko`） |
| `VIBEMOUSE_DEVICE` | `cpu` | 推理设备（`cpu` 或 `cuda:0`） |
| `VIBEMOUSE_ENTER_MODE` | `enter` | 后侧键模式（`enter`/`ctrl_enter`/`shift_enter`/`none`） |
| `VIBEMOUSE_AUTO_PASTE` | `true` | 识别后自动粘贴 |
| `VIBEMOUSE_PREWARM_ON_START` | `true` | 启动时预加载模型（减少首次识别延迟） |
| `VIBEMOUSE_FRONT_BUTTON` | `x2` | 前侧键映射 |
| `VIBEMOUSE_REAR_BUTTON` | `x1` | 后侧键映射 |

## 资源占用

- 内存：约 **660 MB**（主要是 SenseVoice 模型常驻）
- CPU：空闲时几乎为零，仅在语音识别时短暂占用
- 磁盘：模型约 230MB

## 常见问题

### 按侧键没反应

运行 `python test_mouse.py` 确认 pynput 能检测到侧键事件。如果检测不到，可能需要以管理员权限运行。

### 前后键功能反了

运行 `python test_buttons.py`，按提示操作，确认哪个物理键是 x1、哪个是 x2，然后修改配置。

### 识别结果没有粘贴到目标窗口

确保目标窗口的输入框获得了焦点（光标在输入框里闪烁）。VibeMouse 通过剪贴板 + Ctrl+V 粘贴文本。

### 内存占用过高

660MB 是正常值（模型常驻）。如果不可接受，关闭预热：设置 `VIBEMOUSE_PREWARM_ON_START=false`，模型会在首次录音时才加载。

## 致谢

- 原项目：[VibeMouse](https://github.com/vimalinx/VibeMouse)
- 语音识别：[SenseVoice](https://github.com/FunAudioLLM/SenseVoice)（阿里达摩院）
- 推理引擎：[FunASR ONNX](https://github.com/modelscope/FunASR)

## License

Apache-2.0. See `LICENSE`.
