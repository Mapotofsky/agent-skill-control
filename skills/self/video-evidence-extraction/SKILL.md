---
name: video-evidence-extraction
description: 从本地视频或音频生成可核查的转写、关键帧与时间对齐证据，再用于总结、讲解、评价、科普或信息提取。用于播客、新闻、课程、发布会、幻灯片、产品演示等需要同时利用语音与画面的媒体分析请求。
---

# Video Evidence Extraction

将媒体先变成可检查的证据，再开始解释。不要把转写、字幕或单帧当作完整事实。

## Runtime Contract

使用一个已配置的 Python 解释器。它必须能找到 `ffprobe` 与 `ffmpeg`，并能导入 `cv2`、`whisper` 和 `torch`。`whisper` 的语言支持范围就是语音转写范围。

把 Playwright 视为 OpenCV 不可用时的视觉采样后备；它仍不能替代 `ffprobe` 的元数据或 `ffmpeg` 的解码与音频处理。不要在此 Skill 中安装依赖，也不要临时编写底层 `ffmpeg`、OpenCV 或 Whisper 命令。

令 `<skill-dir>` 为本 Skill 所在目录，令 `<python>` 为上述解释器。所有媒体处理都通过：

```powershell
<python> <skill-dir>/scripts/video_evidence.py <subcommand> ...
```

## Evidence Run

### 1. Configure

为每个输入媒体选择一个新的输出目录。先生成配置，再只编辑高层选择：语言、Whisper 模型、设备、音轨、内容类型和最大帧数。

```powershell
<python> <skill-dir>/scripts/video_evidence.py init-config --output <config.json>
```

使用 `content_profile`：`podcast`、`news`、`lecture-slides`、`product-demo` 或 `mixed`。未知类型使用 `mixed`；只有在已知语言时才覆盖 `language: "auto"`。

完成条件：输入媒体存在，输出目录尚未承载另一轮证据，配置可被脚本读取。

### 2. Preflight

运行预检，并将其 JSON 结果作为环境和输入的唯一判断依据。

```powershell
<python> <skill-dir>/scripts/video_evidence.py preflight --input <media> --output <evidence-dir> --config <config.json>
```

完成条件：`preflight.json` 的 `status` 为 `ready`。若不是，报告缺失工具、Python 包、输入流或 Playwright 后备状态；除非用户授权，不安装或替换运行环境。

### 3. Extract

只在预检通过后运行完整提取。

```powershell
<python> <skill-dir>/scripts/video_evidence.py run --input <media> --output <evidence-dir> --config <config.json>
```

脚本固定完成元数据探测、音轨与内嵌字幕选择、音频规范化、Whisper 转写、覆盖式与场景变化抽帧、时间索引和联系表。无音轨或无视频流是有效媒体状态，脚本会明确标记跳过的分支。

完成条件：生成 `evidence-index.json`，且命令以成功状态结束。

### 4. Validate

在阅读内容前验证证据目录。

```powershell
<python> <skill-dir>/scripts/video_evidence.py validate --output <evidence-dir>
```

只有 `validation.json` 没有 `errors` 时，才能开始分析；`warnings` 必须进入最终答案的局限性。若提取失败，读取 `preflight.json`、`run-report.json` 和 `validation.json`，修正配置后使用一个新的输出目录重跑。

完成条件：所有已存在的音频、视频、转写和帧产物均在验证报告中通过或被明确标记为不适用。

### 5. Analyze

先读 `evidence-index.json`、转写文本和联系表；只在具体论点需要时打开对应时间戳的原始帧。将输出组织为用户要求的总结、讲解、介绍、评价、案例或方法论。

对每项关键判断区分三层：

- 视频直接说出或展示的内容，附转写时间戳或帧路径；
- 基于这些证据的解释；
- 需要外部来源才能确认的事实判断。

当用户要求评价或事实核查时，媒体证据只能说明视频的主张，不能证明主张为真；另行检索并引用外部来源。

## Evidence Limits

OpenCV 的场景变化、清晰度和去重是抽帧启发式，不是语义理解；Whisper 可能误识别人名、术语、数字和混合语言。没有 OCR 依赖时，幻灯片文字由模型查看关键帧，而不是被脚本当作完整文本抽取。

本 Skill 不承诺识别音乐、环境音或其他非语音音频的语义。需要此类分析时，明确说明需要额外的音频特征或事件识别工具。

## Resources

- 使用 `scripts/video_evidence.py` 执行预检、提取、配置初始化和验证。
- 仅在解释字段、配置 profile 或验证状态时读取 [references/output-contract.md](references/output-contract.md)。
