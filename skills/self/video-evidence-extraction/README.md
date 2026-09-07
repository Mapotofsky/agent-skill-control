# video-evidence-extraction

将本地视频或音频转换为可核查、带时间对齐的证据包，再用于总结、讲解、评价、科普或信息提取。

这个仓库提供一个面向 Codex/Agent 工作流的 Skill，以及一个统一的证据提取脚本。它把媒体处理、转写、抽帧和产物校验固定在一条可复现的流程中，帮助后续分析明确区分：媒体直接说了什么、基于媒体证据可以作出什么解释，以及哪些事实仍需要外部来源确认。

## 能做什么

- 使用 `ffprobe` 探测媒体元数据、音视频流和字幕流，并选择合适的音轨。
- 使用 `ffmpeg` 规范化音频，使用 Whisper 生成带时间戳的转写。
- 提取可转换的内嵌文本字幕，作为转写之外的辅助证据。
- 使用 OpenCV 结合覆盖采样和场景变化启发式提取关键帧。
- 在 OpenCV 不可用时，使用可选的 Playwright 浏览器采样作为视觉后备。
- 生成 JSON、TXT、SRT、VTT、关键帧索引和联系表，便于人工检查或程序继续处理。
- 在分析前验证证据目录，报告缺失产物、警告和不适用的分支。

适用内容包括播客、新闻、课程/幻灯片、产品演示，以及无法预先分类的混合媒体。

## 工作流

每一轮媒体分析都建议使用一个新的证据输出目录，并按以下顺序执行：

1. `init-config`：生成默认 JSON 配置。
2. `preflight`：检查运行环境和输入媒体；只有 `preflight.json` 的 `status` 为 `ready` 时才继续。
3. `run`：执行元数据探测、音轨处理、转写、字幕提取和关键帧提取。
4. `validate`：确认产物完整后，再开始阅读和解释媒体内容。

脚本拥有底层 `ffprobe`、`ffmpeg`、OpenCV、Whisper 和可选 Playwright 的调用。使用者只需要选择输入、输出目录和高层配置，不需要在外部重新拼接底层媒体命令。

## 环境要求

运行前请准备一个 Python 3.10 或更高版本的环境，并确保该环境可以导入：

- `cv2`（OpenCV）
- `whisper`（通常由 OpenAI Whisper 包提供）
- `torch`（PyTorch）

此外还需要：

- `ffprobe`
- `ffmpeg`

二者应位于 `PATH` 中，也可以在配置的 `tool_paths` 字段中指定路径。

当 OpenCV 不可用时，视觉后备需要 Node.js、Playwright 及可用的浏览器。相关路径可通过 `playwright_node` 和 `playwright_node_modules` 配置，或通过以下环境变量提供：

- `VIDEO_EVIDENCE_NODE`
- `VIDEO_EVIDENCE_PLAYWRIGHT_NODE_MODULES`

本仓库不在运行时自动安装依赖，也不包含 `requirements.txt`。请在 Skill 目录之外准备并管理运行环境；Whisper 模型文件也由运行环境负责缓存和管理。

## 快速开始

下面的命令适用于 PowerShell、macOS/Linux shell 等常见环境；请将占位符替换为实际路径。

```text
<python> <skill-dir>/scripts/video_evidence.py init-config \
  --output <config.json>

<python> <skill-dir>/scripts/video_evidence.py preflight \
  --input <media> \
  --output <evidence-dir> \
  --config <config.json>

<python> <skill-dir>/scripts/video_evidence.py run \
  --input <media> \
  --output <evidence-dir> \
  --config <config.json>

<python> <skill-dir>/scripts/video_evidence.py validate \
  --output <evidence-dir>
```

在 PowerShell 中，反斜杠不是续行符；可以写成单行，或使用反引号续行。例如：

```powershell
$Python = "C:\path\to\python.exe"
$SkillDir = "C:\path\to\video-evidence-extraction"
$Media = "C:\path\to\input.mp4"
$EvidenceDir = "C:\path\to\evidence\run-001"
$Config = "C:\path\to\video-evidence-config.json"

& $Python "$SkillDir\scripts\video_evidence.py" init-config --output $Config
& $Python "$SkillDir\scripts\video_evidence.py" preflight --input $Media --output $EvidenceDir --config $Config
& $Python "$SkillDir\scripts\video_evidence.py" run --input $Media --output $EvidenceDir --config $Config
& $Python "$SkillDir\scripts\video_evidence.py" validate --output $EvidenceDir
```

如果预检不是 `ready`，先阅读 `preflight.json` 中的 `errors` 和 `warnings`，修正运行环境或配置后，使用新的证据目录重新执行。不要把一次失败的输出目录直接当作下一轮运行目录。

## 配置

推荐先运行 `init-config`，再只修改高层选择。脚本会用默认配置补齐省略字段，并拒绝未知字段。

| 字段 | 可选值/范围 | 作用 |
| --- | --- | --- |
| `language` | `auto` 或 Whisper 语言代码 | 控制转写语言；已知语言时再覆盖自动检测。 |
| `whisper_model` | Whisper 可用模型名 | 在转写速度、资源消耗和准确率之间选择。默认 `small`。 |
| `device` | `auto`、`cpu`、`cuda` | `auto` 会在可用时优先使用 CUDA。 |
| `audio_stream` | `auto` 或数字流索引 | 选择用于转写的音轨。默认自动选择。 |
| `extract_embedded_subtitles` | `true` / `false` | 是否保留可转换的内嵌文本字幕。 |
| `content_profile` | `podcast`、`news`、`lecture-slides`、`product-demo`、`mixed` | 调整覆盖采样密度和场景变化敏感度。 |
| `max_frames` | `1`–`240` 的整数 | 限制最终导出的关键帧数量；默认 `60`。 |
| `keep_intermediates` | `true` / `false` | 是否保留规范化 WAV 中间文件。 |
| `tool_paths` | `ffprobe`、`ffmpeg` 路径 | 在工具不在 `PATH` 时指定可执行文件。 |
| `playwright_node` | 路径或 `null` | 指定 Playwright 后备使用的 Node 可执行文件。 |
| `playwright_node_modules` | 路径或 `null` | 指定无法自动解析 Playwright 时使用的 `node_modules` 目录。 |

Profile 只表达抽帧策略，不保证识别出语义上最重要的画面：

| Profile | 适合内容 | 默认倾向 |
| --- | --- | --- |
| `podcast` | 以语音为主、画面变化少的内容 | 转写优先，低密度覆盖画面。 |
| `news` | 新闻、采访、直播切片 | 更密集地保留画面切换和字幕条变化。 |
| `lecture-slides` | 课程、演讲、幻灯片 | 保留幻灯片变化并覆盖课程时间线。 |
| `product-demo` | 软件或产品操作演示 | 更密集地保留界面和操作变化。 |
| `mixed` | 内容类型未知或混合 | 使用保守的通用策略。 |

## 输出目录

成功运行后，证据目录大致如下：

```text
evidence-dir/
├── preflight.json
├── media.json
├── evidence-index.json
├── run-report.json
├── validation.json                 # 执行 validate 后生成
├── subtitles/
│   └── embedded.srt                # 存在可转换内嵌字幕时生成
├── transcript/
│   ├── transcript.json              # Whisper 分段和时间戳
│   ├── transcript.txt              # 便于阅读的纯文本
│   ├── transcript.srt
│   └── transcript.vtt
└── frames/
    ├── index.json                  # 帧的时间戳、理由、质量信息和相对路径
    ├── contact-sheet.jpg           # OpenCV 可用时生成
    ├── contact-sheet.html          # 可浏览的帧总览
    └── *.jpg                       # 导出的关键帧
```

`evidence-index.json` 是分析阶段的入口索引。`preflight.json` 记录环境和输入检查，`run-report.json` 记录各提取分支、命令结果、跳过项和错误，`validation.json` 记录产物完整性、覆盖率以及警告/错误。设置 `keep_intermediates: true` 时，还会保留中间音频文件。

程序化使用时应读取 JSON 中的状态和 `errors`/`warnings`，不要只依赖进程返回码：

| 状态 | 含义 |
| --- | --- |
| `ready` | 预检满足提取要求，可以运行完整流程。 |
| `warning` | 已完成可用工作，但存在需要披露的限制。 |
| `skipped` | 输入没有对应类型的流，例如纯音频没有视频分支。 |
| `failed` | 应存在的核心产物无法生成，不能据此开始分析。 |
| `pass` / `review` / `fail` | `validate` 的结果；`review` 表示可以继续，但必须处理警告。 |

## 分析时的证据规则

建议按以下顺序消费输出：

1. 先读 `validation.json`；`fail` 表示不能开始内容分析，`review` 表示可以继续但必须披露警告。
2. 再读 `evidence-index.json`、`transcript/transcript.txt` 或 `transcript/transcript.json`，浏览 `frames/contact-sheet.*`。
3. 只有在某个具体论点需要时，才打开对应时间戳的原始关键帧。
4. 在最终输出中分别标记：媒体直接说出/展示的内容、基于这些证据的解释、需要外部来源确认的事实。

媒体证据可以证明“视频提出了什么主张”，不能单独证明该主张为真。评价、事实核查或涉及外部世界的结论，应另行检索并引用可靠来源。

## 局限性

- Whisper 可能误识别人名、术语、数字和混合语言；关键结论应回看音频或原始画面。
- OpenCV 的场景变化、清晰度和去重判断是启发式，不是语义理解。
- 没有 OCR 依赖时，幻灯片或界面中的文字主要依靠模型查看关键帧，不会被脚本当作完整文本抽取。
- 本 Skill 不承诺理解音乐、环境音或其他非语音音频的语义；这类任务需要额外的音频特征或事件识别工具。
- 纯音频输入会跳过视频帧分支；纯视频输入会跳过语音转写分支。输入必须至少包含音频流或视频流。

## 目录结构

```text
.
├── SKILL.md                         # 面向 Agent 的工作流与运行契约
├── scripts/
│   ├── video_evidence.py             # 主 CLI 与证据提取实现
│   └── playwright_capture.mjs        # Playwright 视觉后备
└── references/
    └── output-contract.md            # 配置、产物和状态字段说明
```

## 作为 Skill 使用

保留 `SKILL.md` 位于仓库根目录，并保持 `scripts/` 与 `references/` 的相对路径不变。将该目录放入支持此类 Skill 的 Agent/Codex 技能目录后，Agent 可以按照 `SKILL.md` 中的配置、预检、提取、校验和分析流程调用脚本。

本仓库不是一个 PyPI 包，也不是独立的 Web 服务；它的核心接口是 `scripts/video_evidence.py` 的四个子命令。

## 许可证

当前仓库未包含许可证文件。公开发布前，请根据你的分发和使用需求补充合适的 `LICENSE`。
