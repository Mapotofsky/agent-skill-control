# Output Contract

`scripts/video_evidence.py` 是行为与字段的实现来源。本文件说明调用方应如何选择配置和阅读产物。

## Configuration

`init-config` 生成 JSON。保留未使用的默认字段，避免手工加入底层编解码参数。

| Field | Values | Effect |
| --- | --- | --- |
| `language` | `"auto"` 或 Whisper 语言代码 | 控制转写语言；仅在已知时覆盖自动检测。 |
| `whisper_model` | Whisper 可用模型名 | 优先调整准确率或速度，不更改媒体处理。 |
| `device` | `"auto"`, `"cpu"`, `"cuda"` | `auto` 优先使用可用 CUDA。 |
| `audio_stream` | `"auto"` 或流索引 | `auto` 优先默认音轨，其次语言、声道和码率。 |
| `extract_embedded_subtitles` | `true` 或 `false` | 将可转换的内嵌文本字幕保留为辅助证据。 |
| `content_profile` | `podcast`, `news`, `lecture-slides`, `product-demo`, `mixed` | 选择抽帧覆盖率与场景变化灵敏度。 |
| `max_frames` | 正整数 | 限制最终导出的关键帧数量。 |
| `keep_intermediates` | `true` 或 `false` | 保留规范化 WAV；默认只保留最终证据。 |
| `playwright_node` | `null` 或 Node 可执行文件路径 | 仅在 OpenCV 不可用时指定能加载 Playwright 的 Node。 |
| `playwright_node_modules` | `null` 或 `node_modules` 路径 | 仅在 Node 无法自动解析 Playwright 时提供；脚本会将其加入 `NODE_PATH`。 |

Profile 是高层意图，不保证语义关键帧：

- `podcast`：转写优先，低密度覆盖帧。
- `news`：更密集地保留画面切换和字幕条变化。
- `lecture-slides`：保留幻灯片变化并保证课程时间覆盖。
- `product-demo`：更密集地保留 UI 或操作变化。
- `mixed`：上述场景未知时的保守默认。

## Evidence Directory

| Path | Purpose |
| --- | --- |
| `preflight.json` | 工具、Python 包、输入流及后备能力的检查结果。 |
| `media.json` | `ffprobe` 返回的规范化媒体元数据、已选流和时长。 |
| `subtitles/` | 可提取的内嵌文本字幕；不存在或图像型字幕时会在报告中说明。 |
| `transcript/transcript.json` | Whisper 分段结果与时间戳，是时间对齐的主索引。 |
| `transcript/transcript.txt` | 便于阅读的纯文本转写。 |
| `transcript/transcript.srt` / `.vtt` | 便于播放器或字幕工具使用的转写。 |
| `frames/index.json` | 每张导出帧的时间戳、理由、场景分数、清晰度和相对路径。 |
| `frames/contact-sheet.jpg` | OpenCV 可用时生成的视觉总览。 |
| `frames/contact-sheet.html` | 始终生成的可浏览帧总览；适用于 Playwright 后备。 |
| `evidence-index.json` | 面向分析阶段的入口索引与相对路径。 |
| `run-report.json` | 提取分支、命令结果、跳过项与错误。 |
| `validation.json` | 产物完整性、转写覆盖率、帧文件和警告/错误。 |

## Statuses

- `ready`：预检满足完整提取要求。
- `warning`：已完成可用工作，但存在不影响文件完整性的限制，例如无字幕、无 CUDA 或 Playwright 不可用。
- `skipped`：输入没有该类流，例如纯音频没有帧分支。
- `failed`：一个应存在的核心产物无法生成；不要据此开始内容分析。
- `pass` / `review` / `fail`：验证结果。`review` 表示没有缺失核心产物，但警告必须在后续结论中披露。
