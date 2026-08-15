# VibeMouse — SenseVoiceSmall 微调任务交接文档

> 给接手微调任务的 AI 助手。你没有本项目的上下文，本文自足。
> 生成时间：2026-08-15

---

## 1. VibeMouse 是什么

Windows 上的**鼠标侧键语音输入工具**。按鼠标侧键 → 录音 → 本地 ASR 转写 → 自动粘贴到当前焦点窗口。
**全程离线**，不联网、不调 API。用户是科研人员，主要用它口述中文（夹杂大量英文专业术语）给 AI 助手下指令、写实验记录。

## 2. 文件位置

| 用途 | 路径 |
|---|---|
| 代码仓库 | `C:\Users\Yuhang\Tools\VibeMouse_for_Windows` |
| GitHub | https://github.com/gongyuhang2023-cpu/VibeMouse_for_Windows |
| 当前工作分支 | `feat/whisper-backend`（已推送；`master` 是微调前的原始状态） |
| **用户配置**（含词库） | `C:\Users\Yuhang\AppData\Roaming\vibemouse\config.json` |
| ASR 后端实现 | `vibemouse/core/transcriber.py` |
| 配置 schema | `vibemouse/config/schema.py` |
| 自检工具 | `vibemouse/ops/doctor.py` |
| 启动器（后台） | `start_vibemouse_silent.vbs` |
| SenseVoice 权重缓存 | `C:\Users\Yuhang\.cache\modelscope\hub\models\iic\SenseVoiceSmall`<br>`...\iic\SenseVoiceSmall-onnx` |

**两个 Python 环境，别搞混：**

| 用途 | 解释器 | 说明 |
|---|---|---|
| 运行 app | `C:\Users\Yuhang\miniconda3\envs\vibemouse\python.exe`（3.11.15） | 有 funasr-onnx / faster-whisper / modelscope，**没有 pytest**，**没有 funasr 训练包** |
| 跑测试 | 系统 `python`（3.13.12） | 有 pytest，无 ASR 依赖 |

从别处执行脚本要 `PYTHONPATH=C:\Users\Yuhang\Tools\VibeMouse_for_Windows`（包没装进 env，靠 cwd 生效）。

**硬件**：RTX 5070（12 GB，Blackwell sm_120，驱动 591.86 / CUDA 13.1）+ Intel Ultra 7 265K（20 核）+ 32 GB RAM。
另有一台共享 Slurm 服务器（**ARM64 + 统一内存**）。

## 3. 微调目标

**微调 `iic/SenseVoiceSmall`（FunAudioLLM/阿里，~234M 参数，Apache-2.0），让它直接在权重里学会用户的领域词汇 + 用户本人的声音。**

许可证注意：ModelScope 元数据标 Apache-2.0，但 FunASR 仓库另有一份 `MODEL_LICENSE` 对权重有附加条款。自用不受影响，**要再分发必须重新核**。详见仓库 `THIRD_PARTY_NOTICES.md:44-62`。

## 4. ⚠️ 最关键的约束（先读这条，它决定成败）

**SenseVoiceSmall 在架构上无法做热词/prompt 偏置。**

已核实：安装包源码 `funasr_onnx/sensevoice_bin.py:149-151`，`__call__` 只读 `language` 和 `textnorm` 两个 kwarg，没有任何文本条件输入位置。它是非自回归模型，结构上就没有 prompt 的位置。

**后果：**

1. 走 SenseVoice 路线，**全部领域词汇必须靠权重学会**，没有运行时兜底。这比 Whisper 路线的门槛高得多——Whisper 用 `initial_prompt` 免费就能拿到偏置。
2. 项目里的**后处理纠正表仍然有效**（`vocabulary.corrections`，与后端无关，见 `transcriber.py` 的 `apply_corrections()`）。可以继续用它兜底稳定的近音错。
3. 用户词汇**每 3-6 个月随课题换一轮**。权重是死的，这意味着每轮都要重训。这是本方案已知的结构性代价，用户已知悉并决定推进。

## 5. 已测数据（别重复劳动）

在本项目自建的合成测试集上实测过，硬件同上。

**各模型对比**（12 段加难音频：语速 +30%，叠加 SNR 10dB/5dB 噪声）：

| 模型 | 精度 | 显存 | 术语召回 | CER | 延迟/7.4s |
|---|---|---|---|---|---|
| SenseVoiceSmall | int8 ONNX (CPU) | 0 | 5/20 | — | ~110 ms |
| whisper large-v3 | float16 | 4077 MB | 29/30 | 2.5% | 612 ms |
| whisper large-v3 | int8_float16 | 2128 MB | 29/30 | 3.1% | 668 ms |
| whisper medium | int8_float16 | 1164 MB | 29/30 | 1.8% | 513 ms |
| whisper large-v3-turbo | int8_float16 | 1264 MB | 21/30 | 5.3% | 243 ms |
| whisper small | int8_float16 | 529 MB | 26/30 | 7.9% | 285 ms |

**SenseVoice 的具体错法**（这就是要微调修掉的东西）：

| 目标词 | SenseVoice 实际输出 |
|---|---|
| `湿实验` | 尸实验 / 失实验（**0/4**） |
| `prophage` | pro H / pro / prop H / **prorop**（0/4） |
| `phage` | 非 / f / 直接吞掉（1/4） |
| `噬菌体` | 湿菌体 / 氏菌体 / 视菌体 |
| `滴度` | 低度 |
| `裂解` | 列解 |
| `菌株` | 军株 / 君珠 |
| `干实验` | ✅ 4/4 正确 |

注意英文术语被**音译成随机碎片**（"prorop"、"f"），这是后处理替换表接不住的——碎片不稳定。**这是微调必须解决的核心问题。**

**词库消融**（whisper medium，说明偏置的价值量级）：

| 词库 | 噬菌体音频 | 工具链音频 |
|---|---|---|
| 无词库 | 8/42, CER 20.4% | 20/38, CER 13.7% |
| 只有噬菌体词（8 条） | 41/42, CER 1.8% | 20/38, CER 16.5% |
| 只有工具词（23 条） | 23/42, CER 7.4% | 38/38, CER 2.7% |
| 全部 29 条 | 37/42, CER 2.8% | 38/38, CER 2.7% |

**微调后的 SenseVoice 至少要打平"全部 29 条"那一行**，否则不如现状。

## 6. 要学会的词汇

来自用户配置 `%APPDATA%\vibemouse\config.json`。

**领域术语（29 条）** —— 分两块：

```
干实验 / 工具链（23）：
Zotero, ingest, pathway, vault, qmd, MinerU, Boltz, ADMET, ChEMBL,
docking, SMILES, prophage, phage, HsdR, methylome, ANCOM-BC, virome,
CagA, Mucispirillum, Slurm, sbatch, spark, 酶活性

湿实验（6）：
湿实验, 干实验, 噬菌体, 菌株, 滴度, 裂解
```

**后处理纠正表（31 条，微调后仍可保留）**：见配置文件 `vocabulary.corrections`。

用户课题背景：幽门螺杆菌（H. pylori）防御/抗防御系统筛选、噬菌体、原噬菌体、甲基化组、微生物组差异分析。可据此扩充语料的话术。

## 7. 数据 —— 真正的瓶颈

**算力不是问题**（234M 参数，5070 全量微调绰绰有余）。**成对的（音频, 正确转写）数据才是。**

需要明确回答的问题：
- 用什么数据？用户本人录音？合成 TTS？公开中文语料 + 领域文本拼接？
- 要多少？领域词汇适配通常 10 小时量级；只做窄词汇注入可能几百条起效
- **灾难性遗忘**怎么防？小样本窄数据集微调很容易把通用中文能力搞坏。建议混入通用语料、低学习率、早停、或只调部分层
- 每个术语要多少条不同语境的样本？

**一个几乎免费的数据来源（建议优先考虑）**：VibeMouse 本来就在录音、出文本，用户会顺手改错。把「音频 → 用户最终采用的文本」成对留存，正常使用几个月就是一份分布完全匹配的真实数据集。当前项目**尚未实现**这个留存功能，需要的话要新加（`vibemouse/core/app.py` 的转写 worker 里挂钩）。

## 8. 评测协议（务必做，否则无法判断是否有效）

**⚠️ 一个未解决的矛盾，请先处理：**

合成 TTS 测试集上，当前 whisper 方案对 `湿实验` 的召回很高；但**用户实际使用中报告 `湿实验` 识别不出来**。说明**合成语音与用户真实语音存在系统性差距，现有测试集乐观**。

**因此第一步应该是：让用户用 VibeMouse 实录 20-50 句真实语料（含上述术语），人工校对成参考文本，作为真正的评测集。** 在此之前的任何数值都不足以支撑决策。

已有的合成评测方法（可复用，脚本在临时目录，需要的话让主项目 Claude 重新生成或提交进仓库）：
- 用 Windows SAPI 中文语音（Huihui / Kangkang）合成含术语的中英混说句子
- 变体：正常语速 / 语速 +30% / 叠加 SNR 10dB / 5dB 粉噪
- 指标：**术语召回**（目标词是否出现）+ **CER**（去标点后字级编辑距离 / 参考字数）
- 两个指标都要报——只看术语召回会漏掉"靠偏置硬拉对术语但整句更差"的情况，这个坑踩过

**成功判据建议**：微调后的 SenseVoice 在**真实录音**评测集上，术语召回和 CER 都不劣于当前 whisper medium + 29 词库方案；否则应放弃微调路线，回到 whisper。

## 9. 训练环境提醒

- 训练需要 `funasr`（完整包，含训练代码），当前运行环境**只装了 `funasr-onnx`（推理）**。别装进 `vibemouse` 这个 env，另开一个，避免搞坏正在用的推理环境。
- 微调产出是 PyTorch 权重；VibeMouse 的 `funasr_onnx` 后端要的是 **ONNX**。需要导出转换，`transcriber.py` 的 `_resolve_onnx_model_dir()` 支持指向本地目录（要求目录内有 `model_quant.onnx` 或 `model.onnx`，外加 `chn_jpn_yue_eng_ko_spectok.bpe.model` 分词器文件）。**这条链路要打通，否则训出来也用不上。**
- 那台 Slurm 服务器是 **ARM64 + 统一内存**：`bitsandbytes`、部分 CUDA 扩展、CTranslate2 对 ARM64 支持都不完整，依赖坑可能比训练本身更费时间（置信度：中，未在该机验证）。**建议先在本地 5070 上跑通全流程再上服务器。**

## 10. 交付物

1. 数据方案（来源、规模、构造方式、防遗忘策略）
2. 训练脚本 + 超参，可在 5070（12 GB）上跑通
3. PyTorch → ONNX 导出流程，产物能被 `transcriber.py` 的 `funasr_onnx` 后端直接加载
4. 真实录音评测集 + 评测脚本 + 对比数据（微调前 / 微调后 / whisper 基线）
5. 明确结论：**微调后是否真的优于现状**。如果不优，如实说，别硬推。
