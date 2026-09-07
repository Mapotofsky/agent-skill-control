#!/usr/bin/env python3
"""Create timestamped, validated evidence from a local media file.

The script deliberately owns the ffprobe, ffmpeg, OpenCV, Whisper, and optional
Playwright calls so an agent configures a run instead of reconstructing shell
pipelines for every video.
"""

from __future__ import annotations

import argparse
import html
import importlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = "1.0"
MAX_PROCESS_OUTPUT = 6000
TEXT_SUBTITLE_CODECS = {
    "ass",
    "mov_text",
    "srt",
    "ssa",
    "subrip",
    "text",
    "webvtt",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "language": "auto",
    "whisper_model": "small",
    "device": "auto",
    "audio_stream": "auto",
    "extract_embedded_subtitles": True,
    "content_profile": "mixed",
    "max_frames": 60,
    "keep_intermediates": False,
    "tool_paths": {"ffprobe": None, "ffmpeg": None},
    "playwright_node": None,
    "playwright_node_modules": None,
}

PROFILE_SETTINGS: dict[str, dict[str, float]] = {
    "podcast": {
        "coverage_interval": 30.0,
        "coverage_ratio": 1.0,
        "scene_interval": 3.0,
        "scene_threshold": 0.42,
        "min_gap": 5.0,
    },
    "news": {
        "coverage_interval": 10.0,
        "coverage_ratio": 0.55,
        "scene_interval": 1.0,
        "scene_threshold": 0.30,
        "min_gap": 2.0,
    },
    "lecture-slides": {
        "coverage_interval": 20.0,
        "coverage_ratio": 0.50,
        "scene_interval": 1.0,
        "scene_threshold": 0.24,
        "min_gap": 3.0,
    },
    "product-demo": {
        "coverage_interval": 5.0,
        "coverage_ratio": 0.45,
        "scene_interval": 0.5,
        "scene_threshold": 0.20,
        "min_gap": 1.0,
    },
    "mixed": {
        "coverage_interval": 15.0,
        "coverage_ratio": 0.50,
        "scene_interval": 1.5,
        "scene_threshold": 0.30,
        "min_gap": 3.0,
    },
}


class PipelineError(RuntimeError):
    """Raised when a run cannot create a required evidence artifact."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def truncate_output(value: str) -> str:
    if len(value) <= MAX_PROCESS_OUTPUT:
        return value
    return value[-MAX_PROCESS_OUTPUT:]


def run_process(
    argv: list[str], timeout: int = 900, environment: dict[str, str] | None = None
) -> dict[str, Any]:
    record: dict[str, Any] = {"argv": argv}
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
        )
        record.update(
            {
                "returncode": completed.returncode,
                "stdout": truncate_output(completed.stdout),
                "stderr": truncate_output(completed.stderr),
            }
        )
    except FileNotFoundError as error:
        record.update({"returncode": None, "error": str(error)})
    except subprocess.TimeoutExpired as error:
        record.update({"returncode": None, "error": f"Timed out after {timeout}s: {error}"})
    return record


def command_succeeded(record: dict[str, Any]) -> bool:
    return record.get("returncode") == 0


def as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def relative_path(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def resolve_tool(name: str, configured_path: Any = None) -> str | None:
    candidates: list[Path] = []
    if isinstance(configured_path, str) and configured_path.strip():
        candidates.append(Path(configured_path).expanduser())

    environment_key = f"VIDEO_EVIDENCE_{name.upper()}"
    if os.environ.get(environment_key):
        candidates.append(Path(os.environ[environment_key]).expanduser())

    for executable in (name, f"{name}.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))

    prefix = Path(sys.prefix)
    executable_parent = Path(sys.executable).resolve().parent
    roots = [
        prefix / "Library" / "bin",
        prefix / "bin",
        executable_parent,
        executable_parent.parent / "Library" / "bin",
    ]
    for root in roots:
        candidates.extend([root / name, root / f"{name}.exe"])

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return None


def prepend_executable_directory(executable: str) -> None:
    directory = str(Path(executable).resolve().parent)
    current = os.environ.get("PATH", "")
    entries = [entry for entry in current.split(os.pathsep) if entry]
    if any(entry.casefold() == directory.casefold() for entry in entries):
        return
    os.environ["PATH"] = directory if not current else directory + os.pathsep + current


def resolve_node(config: dict[str, Any]) -> str | None:
    candidates: list[Path] = []
    configured = config.get("playwright_node")
    if isinstance(configured, str) and configured.strip():
        candidates.append(Path(configured).expanduser())
    environment_node = os.environ.get("VIDEO_EVIDENCE_NODE")
    if environment_node:
        candidates.append(Path(environment_node).expanduser())
    for executable in ("node", "node.exe"):
        found = shutil.which(executable)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except OSError:
            continue
    return None


def playwright_environment(config: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    modules = config.get("playwright_node_modules") or os.environ.get("VIDEO_EVIDENCE_PLAYWRIGHT_NODE_MODULES")
    if isinstance(modules, str) and modules.strip():
        current = environment.get("NODE_PATH", "")
        environment["NODE_PATH"] = modules if not current else modules + os.pathsep + current
    return environment


def module_status(module_name: str) -> dict[str, Any]:
    try:
        module = importlib.import_module(module_name)
        return {"available": True, "version": getattr(module, "__version__", "unknown")}
    except Exception as error:  # Import errors can arise from native library setup.
        return {"available": False, "error": f"{type(error).__name__}: {error}"}


def load_config(config_path: str | None) -> dict[str, Any]:
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if not config_path:
        return config

    source = Path(config_path).expanduser().resolve()
    try:
        supplied = read_json(source)
    except (OSError, json.JSONDecodeError) as error:
        raise PipelineError(f"Cannot read config {source}: {error}") from error
    if not isinstance(supplied, dict):
        raise PipelineError("Config must be a JSON object.")

    unknown = sorted(set(supplied) - set(DEFAULT_CONFIG))
    if unknown:
        raise PipelineError(f"Unsupported config field(s): {', '.join(unknown)}")
    for key, value in supplied.items():
        if key == "tool_paths":
            if not isinstance(value, dict):
                raise PipelineError("tool_paths must be an object.")
            unknown_tools = sorted(set(value) - {"ffprobe", "ffmpeg"})
            if unknown_tools:
                raise PipelineError(f"Unsupported tool_paths field(s): {', '.join(unknown_tools)}")
            config["tool_paths"].update(value)
        else:
            config[key] = value
    validate_config(config)
    return config


def validate_config(config: dict[str, Any]) -> None:
    if not isinstance(config["language"], str) or not config["language"].strip():
        raise PipelineError("language must be a non-empty string or 'auto'.")
    if not isinstance(config["whisper_model"], str) or not config["whisper_model"].strip():
        raise PipelineError("whisper_model must be a non-empty model name.")
    if config["device"] not in {"auto", "cpu", "cuda"}:
        raise PipelineError("device must be one of: auto, cpu, cuda.")
    if config["content_profile"] not in PROFILE_SETTINGS:
        options = ", ".join(PROFILE_SETTINGS)
        raise PipelineError(f"content_profile must be one of: {options}.")
    if not isinstance(config["extract_embedded_subtitles"], bool):
        raise PipelineError("extract_embedded_subtitles must be true or false.")
    if not isinstance(config["keep_intermediates"], bool):
        raise PipelineError("keep_intermediates must be true or false.")
    for key in ("playwright_node", "playwright_node_modules"):
        if config[key] is not None and (not isinstance(config[key], str) or not config[key].strip()):
            raise PipelineError(f"{key} must be null or a non-empty path string.")
    max_frames = as_int(config["max_frames"], -1)
    if not 1 <= max_frames <= 240:
        raise PipelineError("max_frames must be an integer from 1 to 240.")
    audio_stream = config["audio_stream"]
    if not (
        audio_stream == "auto"
        or isinstance(audio_stream, int)
        or (isinstance(audio_stream, str) and audio_stream.isdigit())
    ):
        raise PipelineError("audio_stream must be 'auto' or a numeric stream index.")


def probe_media(ffprobe: str, input_path: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        "-of",
        "json",
        str(input_path),
    ]
    record = run_process(command, timeout=120)
    if not command_succeeded(record):
        return None, record
    try:
        raw = json.loads(record["stdout"])
    except json.JSONDecodeError as error:
        record["error"] = f"ffprobe returned invalid JSON: {error}"
        return None, record

    streams = raw.get("streams", []) if isinstance(raw.get("streams"), list) else []
    format_data = raw.get("format", {}) if isinstance(raw.get("format"), dict) else {}
    duration = as_float(format_data.get("duration"))
    if duration is None:
        durations = [as_float(stream.get("duration")) for stream in streams]
        usable = [value for value in durations if value is not None]
        duration = max(usable) if usable else None

    media = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "input_path": str(input_path.resolve()),
        "duration_seconds": duration,
        "format": format_data,
        "streams": streams,
        "chapters": raw.get("chapters", []),
    }
    return media, record


def media_streams(media: dict[str, Any], codec_type: str) -> list[dict[str, Any]]:
    return [
        stream
        for stream in media.get("streams", [])
        if isinstance(stream, dict) and stream.get("codec_type") == codec_type
    ]


def stream_language(stream: dict[str, Any]) -> str:
    tags = stream.get("tags", {})
    if isinstance(tags, dict):
        language = tags.get("language")
        if isinstance(language, str) and language:
            return language.lower()
    return "und"


def choose_stream(
    streams: list[dict[str, Any]], desired: Any, language: str, label: str
) -> dict[str, Any] | None:
    if not streams:
        return None
    if desired != "auto":
        requested_index = as_int(desired, -1)
        for stream in streams:
            if as_int(stream.get("index"), -2) == requested_index:
                return stream
        raise PipelineError(f"Requested {label} stream index {desired} does not exist.")

    preferred_language = language.lower() if language != "auto" else None

    def score(stream: dict[str, Any]) -> tuple[int, int, int, int]:
        disposition = stream.get("disposition", {})
        is_default = as_int(disposition.get("default") if isinstance(disposition, dict) else 0)
        language_match = int(preferred_language is not None and stream_language(stream) == preferred_language)
        channels = as_int(stream.get("channels"))
        bitrate = as_int(stream.get("bit_rate"))
        return (is_default, language_match, channels, bitrate)

    return max(streams, key=score)


def result_status(errors: list[str]) -> str:
    return "ready" if not errors else "blocked"


def playwright_status(script_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    node = resolve_node(config)
    if not node:
        return {"available": False, "error": "node was not found on PATH"}
    if not script_path.is_file():
        return {"available": False, "error": f"Missing companion script: {script_path}"}
    record = run_process(
        [node, str(script_path), "--check"], timeout=60, environment=playwright_environment(config)
    )
    if not command_succeeded(record):
        return {"available": False, "error": record.get("stderr") or record.get("error", "check failed")}
    try:
        payload = json.loads(record.get("stdout", ""))
    except json.JSONDecodeError:
        return {"available": False, "error": "Playwright check did not return JSON"}
    if not payload.get("available"):
        return {"available": False, "error": payload.get("error", "Playwright unavailable")}
    return {"available": True, "node": node, "browser_path": payload.get("browser_path")}


def build_preflight(input_path: Path, config: dict[str, Any], script_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    if not input_path.is_file():
        errors.append(f"Input media file does not exist: {input_path}")
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "status": result_status(errors),
            "input_path": str(input_path),
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
        }

    tools = {
        name: resolve_tool(name, config.get("tool_paths", {}).get(name))
        for name in ("ffprobe", "ffmpeg")
    }
    checks["tools"] = tools
    for name, path in tools.items():
        if not path:
            errors.append(f"Required executable not found: {name}")

    module_checks = {name: module_status(name) for name in ("cv2", "whisper", "torch")}
    checks["python_modules"] = module_checks

    media: dict[str, Any] | None = None
    probe_record: dict[str, Any] | None = None
    if tools["ffprobe"]:
        media, probe_record = probe_media(tools["ffprobe"], input_path)
        checks["ffprobe"] = probe_record
        if media is None:
            errors.append("ffprobe could not read the input media.")
        else:
            checks["media_summary"] = {
                "duration_seconds": media.get("duration_seconds"),
                "video_streams": len(media_streams(media, "video")),
                "audio_streams": len(media_streams(media, "audio")),
                "subtitle_streams": len(media_streams(media, "subtitle")),
            }

    has_audio = bool(media and media_streams(media, "audio"))
    has_video = bool(media and media_streams(media, "video"))
    if has_audio:
        for name in ("whisper", "torch"):
            if not module_checks[name]["available"]:
                errors.append(f"Required Python module for speech transcription is unavailable: {name}")
    elif not module_checks["whisper"]["available"]:
        warnings.append("whisper is unavailable; it is not needed because the input has no audio stream.")

    if has_video and not module_checks["cv2"]["available"]:
        fallback = playwright_status(script_path.with_name("playwright_capture.mjs"), config)
        checks["playwright_fallback"] = fallback
        if fallback["available"]:
            warnings.append("OpenCV is unavailable; frame capture will use the Playwright fallback.")
        else:
            errors.append("OpenCV is unavailable and the Playwright frame-capture fallback is not ready.")
    elif has_video:
        checks["playwright_fallback"] = {"available": None, "note": "Not needed while OpenCV is available."}

    if media and not has_audio and not has_video:
        errors.append("Input contains neither an audio nor a video stream.")
    if media and media.get("duration_seconds") in (None, 0):
        warnings.append("Media duration is unavailable or zero; frame coverage may be limited.")

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": result_status(errors),
        "input_path": str(input_path.resolve()),
        "resolved_config": config,
        "checks": checks,
        "media": media,
        "warnings": warnings,
        "errors": errors,
    }


def prepare_output(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    existing_evidence = [
        name
        for name in ("media.json", "evidence-index.json", "run-report.json", "validation.json")
        if (output / name).exists()
    ]
    if existing_evidence:
        found = ", ".join(existing_evidence)
        raise PipelineError(
            f"Output directory already contains evidence ({found}). Choose a new output directory instead of overwriting it."
        )


def audio_file_path(output: Path) -> Path:
    return output / "intermediates" / "audio.wav"


def extract_audio(
    ffmpeg: str, input_path: Path, stream: dict[str, Any], output: Path, commands: list[dict[str, Any]]
) -> Path:
    target = audio_file_path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    stream_index = as_int(stream.get("index"), -1)
    if stream_index < 0:
        raise PipelineError("Selected audio stream has no usable stream index.")
    record = run_process(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(input_path),
            "-map",
            f"0:{stream_index}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(target),
        ],
        timeout=900,
    )
    commands.append(record)
    if not command_succeeded(record) or not target.is_file() or target.stat().st_size == 0:
        raise PipelineError("ffmpeg could not extract a normalized audio track.")
    return target


def format_timestamp(seconds: Any, separator: str) -> str:
    milliseconds = max(0, int(round((as_float(seconds) or 0.0) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}{separator}{millis:03d}"


def write_transcript_files(output: Path, result: dict[str, Any]) -> dict[str, str]:
    transcript_dir = output / "transcript"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    json_path = transcript_dir / "transcript.json"
    txt_path = transcript_dir / "transcript.txt"
    srt_path = transcript_dir / "transcript.srt"
    vtt_path = transcript_dir / "transcript.vtt"

    write_json(json_path, result)
    txt_path.write_text(str(result.get("text", "")).strip() + "\n", encoding="utf-8")

    segments = result.get("segments", []) if isinstance(result.get("segments"), list) else []
    srt_blocks: list[str] = []
    vtt_blocks: list[str] = ["WEBVTT", ""]
    for sequence, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            continue
        start = segment.get("start", 0)
        end = segment.get("end", start)
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        srt_blocks.append(
            f"{sequence}\n{format_timestamp(start, ',')} --> {format_timestamp(end, ',')}\n{text}\n"
        )
        vtt_blocks.extend(
            [
                f"{format_timestamp(start, '.')} --> {format_timestamp(end, '.')}",
                text,
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_blocks), encoding="utf-8")
    vtt_path.write_text("\n".join(vtt_blocks), encoding="utf-8")
    return {
        "json": "transcript/transcript.json",
        "text": "transcript/transcript.txt",
        "srt": "transcript/transcript.srt",
        "vtt": "transcript/transcript.vtt",
    }


def transcribe_audio(
    audio_path: Path, output: Path, config: dict[str, Any], ffmpeg: str
) -> dict[str, Any]:
    # Whisper's audio loader invokes a bare `ffmpeg`; expose the resolved tool to its child process.
    prepend_executable_directory(ffmpeg)
    try:
        import torch  # type: ignore
        import whisper  # type: ignore
    except Exception as error:
        raise PipelineError(f"Cannot import Whisper runtime: {type(error).__name__}: {error}") from error

    requested_device = config["device"]
    if requested_device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = requested_device
    if device == "cuda" and not torch.cuda.is_available():
        raise PipelineError("Config requested CUDA but torch.cuda.is_available() is false.")

    try:
        model = whisper.load_model(config["whisper_model"], device=device)
        result = model.transcribe(
            str(audio_path),
            language=None if config["language"] == "auto" else config["language"],
            fp16=device == "cuda",
            verbose=False,
        )
    except Exception as error:
        raise PipelineError(f"Whisper transcription failed: {type(error).__name__}: {error}") from error
    if not isinstance(result, dict):
        raise PipelineError("Whisper returned an unsupported transcription result.")

    files = write_transcript_files(output, result)
    segments = result.get("segments", []) if isinstance(result.get("segments"), list) else []
    end_times = [as_float(segment.get("end")) for segment in segments if isinstance(segment, dict)]
    coverage_end = max((value for value in end_times if value is not None), default=0.0)
    return {
        "status": "completed",
        "device": device,
        "detected_language": result.get("language"),
        "segment_count": len(segments),
        "coverage_end_seconds": coverage_end,
        "files": files,
    }


def extract_embedded_subtitles(
    ffmpeg: str,
    input_path: Path,
    subtitle_streams: list[dict[str, Any]],
    config: dict[str, Any],
    output: Path,
    commands: list[dict[str, Any]],
) -> dict[str, Any]:
    if not config["extract_embedded_subtitles"]:
        return {"status": "skipped", "reason": "Disabled by configuration."}
    if not subtitle_streams:
        return {"status": "skipped", "reason": "No embedded subtitle stream."}

    stream = choose_stream(subtitle_streams, "auto", config["language"], "subtitle")
    if stream is None:
        return {"status": "skipped", "reason": "No selectable subtitle stream."}
    codec = str(stream.get("codec_name", "")).lower()
    stream_index = as_int(stream.get("index"), -1)
    report: dict[str, Any] = {
        "selected_stream_index": stream_index,
        "codec": codec,
        "language": stream_language(stream),
    }
    if codec and codec not in TEXT_SUBTITLE_CODECS:
        report.update({"status": "skipped", "reason": "Subtitle stream is image-based or unsupported for SRT conversion."})
        return report

    target = output / "subtitles" / "embedded.srt"
    target.parent.mkdir(parents=True, exist_ok=True)
    record = run_process(
        [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-i",
            str(input_path),
            "-map",
            f"0:{stream_index}",
            "-c:s",
            "srt",
            str(target),
        ],
        timeout=300,
    )
    commands.append(record)
    if command_succeeded(record) and target.is_file():
        report.update({"status": "completed", "file": "subtitles/embedded.srt"})
    else:
        report.update({"status": "warning", "reason": "ffmpeg could not convert the embedded subtitle stream."})
    return report


def coverage_timestamps(duration: float, settings: dict[str, float], max_frames: int) -> list[float]:
    safe_duration = max(duration, 0.01)
    requested_count = max(1, int(math.floor(safe_duration / settings["coverage_interval"])) + 1)
    budget = max(1, int(math.ceil(max_frames * settings["coverage_ratio"])))
    count = min(requested_count, budget)
    if count == 1:
        return [0.0]
    final_timestamp = max(0.0, safe_duration - 0.05)
    return [round(index * final_timestamp / (count - 1), 3) for index in range(count)]


def scan_timestamps(duration: float, interval: float, maximum: int = 1600) -> list[float]:
    if duration <= 0:
        return [0.0]
    count = min(maximum, max(1, int(math.ceil(duration / interval)) + 1))
    if count == 1:
        return [0.0]
    final_timestamp = max(0.0, duration - 0.05)
    return [round(index * final_timestamp / (count - 1), 3) for index in range(count)]


def calculate_scene_candidates(
    input_path: Path, duration: float, settings: dict[str, float]
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        import cv2  # type: ignore
    except Exception as error:
        return [], f"OpenCV import failed: {type(error).__name__}: {error}"

    capture = cv2.VideoCapture(str(input_path))
    if not capture.isOpened():
        capture.release()
        return [], "OpenCV could not open the video stream."

    candidates: list[dict[str, Any]] = []
    previous_histogram: Any = None
    last_selected_time = -settings["min_gap"]
    try:
        for timestamp in scan_timestamps(duration, settings["scene_interval"]):
            capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
            histogram = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
            cv2.normalize(histogram, histogram)
            sharpness = float(cv2.Laplacian(small, cv2.CV_64F).var())
            if previous_histogram is not None:
                score = float(cv2.compareHist(previous_histogram, histogram, cv2.HISTCMP_BHATTACHARYYA))
                if score >= settings["scene_threshold"] and timestamp - last_selected_time >= settings["min_gap"]:
                    candidates.append(
                        {
                            "timestamp_seconds": timestamp,
                            "reasons": ["scene-change"],
                            "scene_score": round(score, 5),
                            "sharpness": round(sharpness, 3),
                        }
                    )
                    last_selected_time = timestamp
            previous_histogram = histogram
    finally:
        capture.release()
    return candidates, None


def merge_candidates(
    coverage: list[float], scenes: list[dict[str, Any]], max_frames: int, min_gap: float
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []

    def add(candidate: dict[str, Any]) -> None:
        timestamp = as_float(candidate.get("timestamp_seconds")) or 0.0
        nearest = min(selected, key=lambda item: abs((as_float(item.get("timestamp_seconds")) or 0.0) - timestamp), default=None)
        if nearest is not None and abs((as_float(nearest.get("timestamp_seconds")) or 0.0) - timestamp) <= min_gap:
            reasons = set(nearest.get("reasons", [])) | set(candidate.get("reasons", []))
            nearest["reasons"] = sorted(reasons)
            for field in ("scene_score", "sharpness"):
                new_value = as_float(candidate.get(field))
                old_value = as_float(nearest.get(field))
                if new_value is not None and (old_value is None or new_value > old_value):
                    nearest[field] = candidate[field]
            return
        if len(selected) < max_frames:
            selected.append(candidate)

    for timestamp in coverage:
        add({"timestamp_seconds": timestamp, "reasons": ["coverage"]})
    for scene in sorted(scenes, key=lambda item: as_float(item.get("scene_score")) or 0.0, reverse=True):
        add(dict(scene))
    if not selected:
        selected.append({"timestamp_seconds": 0.0, "reasons": ["coverage"]})
    return sorted(selected, key=lambda item: as_float(item.get("timestamp_seconds")) or 0.0)


def frame_filename(sequence: int, timestamp: float) -> str:
    return f"frame-{sequence:04d}-{int(round(timestamp * 1000)):010d}.jpg"


def capture_frames_with_ffmpeg(
    ffmpeg: str,
    input_path: Path,
    candidates: list[dict[str, Any]],
    frames_dir: Path,
    commands: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames: list[dict[str, Any]] = []
    errors: list[str] = []
    for sequence, candidate in enumerate(candidates, start=1):
        timestamp = as_float(candidate.get("timestamp_seconds")) or 0.0
        filename = frame_filename(sequence, timestamp)
        target = frames_dir / filename
        record = run_process(
            [
                ffmpeg,
                "-y",
                "-v",
                "error",
                "-ss",
                f"{timestamp:.3f}",
                "-i",
                str(input_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(target),
            ],
            timeout=180,
        )
        commands.append(record)
        if command_succeeded(record) and target.is_file() and target.stat().st_size > 0:
            frame = dict(candidate)
            frame["file"] = filename
            frames.append(frame)
        else:
            errors.append(f"Could not export frame at {timestamp:.3f}s.")
    return frames, errors


def capture_frames_with_playwright(
    input_path: Path,
    candidates: list[dict[str, Any]],
    frames_dir: Path,
    commands: list[dict[str, Any]],
    config: dict[str, Any],
    script_path: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    status = playwright_status(script_path, config)
    if not status.get("available"):
        return [], [f"Playwright fallback unavailable: {status.get('error', 'unknown error')}"]
    frames_dir.mkdir(parents=True, exist_ok=True)
    request: list[dict[str, Any]] = []
    candidates_by_filename: dict[str, dict[str, Any]] = {}
    for sequence, candidate in enumerate(candidates, start=1):
        timestamp = as_float(candidate.get("timestamp_seconds")) or 0.0
        filename = frame_filename(sequence, timestamp)
        request.append({"timestamp_seconds": timestamp, "filename": filename})
        candidates_by_filename[filename] = candidate
    request_path = frames_dir / "playwright-request.json"
    result_path = frames_dir / "playwright-result.json"
    write_json(request_path, request)
    record = run_process(
        [
            str(status["node"]),
            str(script_path),
            "--input",
            str(input_path),
            "--request",
            str(request_path),
            "--output",
            str(frames_dir),
            "--result",
            str(result_path),
        ],
        timeout=900,
        environment=playwright_environment(config),
    )
    commands.append(record)
    if not command_succeeded(record) or not result_path.is_file():
        return [], ["Playwright could not capture video frames."]
    try:
        captured = read_json(result_path)
    except (OSError, json.JSONDecodeError):
        return [], ["Playwright result index is unreadable."]
    frames: list[dict[str, Any]] = []
    for result in captured.get("frames", []) if isinstance(captured, dict) else []:
        if not isinstance(result, dict):
            continue
        filename = result.get("file")
        if not isinstance(filename, str) or not (frames_dir / filename).is_file():
            continue
        frame = dict(candidates_by_filename.get(filename, {}))
        frame.update({"file": filename, "timestamp_seconds": result.get("timestamp_seconds")})
        frames.append(frame)
    if not frames:
        return [], ["Playwright completed without producing readable frames."]
    return frames, []


def write_contact_sheet_html(frames_dir: Path, frames: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for frame in frames:
        filename = html.escape(str(frame.get("file", "")))
        timestamp = as_float(frame.get("timestamp_seconds")) or 0.0
        reasons = html.escape(", ".join(str(reason) for reason in frame.get("reasons", [])))
        cards.append(
            "<figure><img loading=\"lazy\" src=\"{}\" alt=\"Frame at {:.3f} seconds\">"
            "<figcaption>{:.3f}s | {}</figcaption></figure>".format(filename, timestamp, timestamp, reasons)
        )
    document = """<!doctype html>
<meta charset=\"utf-8\">
<title>Video evidence contact sheet</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 16px; background: #f7f7f7; }}
main {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
figure {{ margin: 0; background: white; padding: 8px; border: 1px solid #ddd; }}
img {{ display: block; width: 100%; height: auto; }}
figcaption {{ margin-top: 6px; font-size: 12px; color: #333; }}
</style>
<main>{}</main>
""".format("\n".join(cards))
    target = frames_dir / "contact-sheet.html"
    target.write_text(document, encoding="utf-8")
    return "frames/contact-sheet.html"


def write_contact_sheet_jpg(frames_dir: Path, frames: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None, "OpenCV contact sheet unavailable."
    images: list[tuple[dict[str, Any], Any]] = []
    for frame in frames:
        filename = frame.get("file")
        if not isinstance(filename, str):
            continue
        image = cv2.imread(str(frames_dir / filename))
        if image is not None:
            images.append((frame, image))
    if not images:
        return None, "No readable frames for contact sheet."

    cell_width, cell_height = 320, 220
    columns = max(1, math.ceil(math.sqrt(len(images))))
    rows = math.ceil(len(images) / columns)
    canvas = np.full((rows * cell_height, columns * cell_width, 3), 245, dtype=np.uint8)
    for index, (frame, image) in enumerate(images):
        row, column = divmod(index, columns)
        height, width = image.shape[:2]
        scale = min((cell_width - 12) / width, (cell_height - 34) / height)
        resized = cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))))
        offset_x = column * cell_width + (cell_width - resized.shape[1]) // 2
        offset_y = row * cell_height + 6
        canvas[offset_y : offset_y + resized.shape[0], offset_x : offset_x + resized.shape[1]] = resized
        timestamp = as_float(frame.get("timestamp_seconds")) or 0.0
        cv2.putText(
            canvas,
            f"{timestamp:.3f}s",
            (column * cell_width + 8, (row + 1) * cell_height - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (30, 30, 30),
            1,
            cv2.LINE_AA,
        )
    target = frames_dir / "contact-sheet.jpg"
    if not cv2.imwrite(str(target), canvas):
        return None, "OpenCV could not write the contact sheet."
    return "frames/contact-sheet.jpg", None


def extract_frames(
    ffmpeg: str,
    input_path: Path,
    duration: float,
    config: dict[str, Any],
    output: Path,
    commands: list[dict[str, Any]],
    script_path: Path,
) -> dict[str, Any]:
    settings = PROFILE_SETTINGS[config["content_profile"]]
    max_frames = as_int(config["max_frames"])
    coverage = coverage_timestamps(duration, settings, max_frames)
    scene_candidates, opencv_error = calculate_scene_candidates(input_path, duration, settings)
    candidates = merge_candidates(coverage, scene_candidates, max_frames, settings["min_gap"])
    frames_dir = output / "frames"
    warnings: list[str] = []

    if opencv_error is None:
        frames, errors = capture_frames_with_ffmpeg(ffmpeg, input_path, candidates, frames_dir, commands)
        backend = "opencv-selection+ffmpeg-export"
    else:
        warnings.append(opencv_error)
        fallback_candidates = [{"timestamp_seconds": timestamp, "reasons": ["coverage"]} for timestamp in coverage]
        frames, errors = capture_frames_with_playwright(
            input_path,
            fallback_candidates,
            frames_dir,
            commands,
            config,
            script_path.with_name("playwright_capture.mjs"),
        )
        backend = "playwright"
        if errors:
            warnings.extend(errors)
            frames, errors = capture_frames_with_ffmpeg(
                ffmpeg, input_path, fallback_candidates, frames_dir, commands
            )
            backend = "ffmpeg-uniform"
            warnings.append("Playwright fallback failed; used uniform ffmpeg frame export without scene analysis.")

    if errors:
        raise PipelineError("; ".join(errors))
    if not frames:
        raise PipelineError("Frame extraction produced no readable frames.")

    html_file = write_contact_sheet_html(frames_dir, frames)
    jpg_file, sheet_warning = write_contact_sheet_jpg(frames_dir, frames)
    if sheet_warning:
        warnings.append(sheet_warning)
    index = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "backend": backend,
        "duration_seconds": duration,
        "frame_count": len(frames),
        "frames": frames,
        "contact_sheet_html": html_file,
        "contact_sheet_jpg": jpg_file,
        "warnings": warnings,
    }
    write_json(frames_dir / "index.json", index)
    return {"status": "completed", "file": "frames/index.json", **index}


def remove_intermediate_audio(output: Path) -> None:
    path = audio_file_path(output)
    if path.exists():
        path.unlink()
    parent = path.parent
    try:
        parent.rmdir()
    except OSError:
        pass


def build_evidence_index(
    input_path: Path, media: dict[str, Any], stages: dict[str, Any], output: Path
) -> dict[str, Any]:
    transcript = stages.get("transcript", {})
    frames = stages.get("frames", {})
    subtitles = stages.get("subtitles", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "completed" if not stages.get("errors") else "failed",
        "input_path": str(input_path.resolve()),
        "duration_seconds": media.get("duration_seconds"),
        "entrypoints": {
            "media": "media.json",
            "transcript": transcript.get("files", {}).get("json"),
            "transcript_text": transcript.get("files", {}).get("text"),
            "frames": frames.get("file"),
            "visual_overview": frames.get("contact_sheet_jpg") or frames.get("contact_sheet_html"),
            "embedded_subtitles": subtitles.get("file"),
        },
        "stages": {
            key: {name: value for name, value in stage.items() if name not in {"raw"}}
            for key, stage in stages.items()
            if isinstance(stage, dict) and key != "errors"
        },
        "analysis_order": [
            "Read transcript text and visual overview.",
            "Use transcript segment timestamps and frames/index.json to inspect evidence for material claims.",
            "Separate recording content, interpretation, and externally verifiable claims.",
        ],
    }


def run_pipeline(input_path: Path, output: Path, config: dict[str, Any], script_path: Path) -> int:
    prepare_output(output)
    commands: list[dict[str, Any]] = []
    preflight = build_preflight(input_path, config, script_path)
    write_json(output / "preflight.json", preflight)
    if preflight["status"] != "ready":
        write_json(
            output / "run-report.json",
            {
                "schema_version": SCHEMA_VERSION,
                "created_at": utc_now(),
                "status": "failed",
                "reason": "Preflight blocked the run.",
                "errors": preflight["errors"],
                "warnings": preflight["warnings"],
            },
        )
        return 2

    media = preflight.get("media")
    if not isinstance(media, dict):
        raise PipelineError("Preflight did not return media metadata.")
    tools = preflight["checks"]["tools"]
    ffmpeg = tools["ffmpeg"]
    if not isinstance(ffmpeg, str):
        raise PipelineError("Preflight did not resolve ffmpeg.")
    duration = as_float(media.get("duration_seconds")) or 0.0
    audio_streams = media_streams(media, "audio")
    video_streams = media_streams(media, "video")
    subtitle_streams = media_streams(media, "subtitle")
    selected_audio = choose_stream(audio_streams, config["audio_stream"], config["language"], "audio")
    media["selection"] = {
        "audio_stream_index": as_int(selected_audio.get("index"), -1) if selected_audio else None,
        "video_stream_indices": [as_int(stream.get("index"), -1) for stream in video_streams],
        "subtitle_stream_indices": [as_int(stream.get("index"), -1) for stream in subtitle_streams],
    }
    write_json(output / "media.json", media)
    write_json(output / "resolved-config.json", config)

    stages: dict[str, Any] = {"errors": []}
    try:
        stages["subtitles"] = extract_embedded_subtitles(
            ffmpeg, input_path, subtitle_streams, config, output, commands
        )
    except Exception as error:
        stages["subtitles"] = {"status": "warning", "reason": str(error)}

    if selected_audio is None:
        stages["audio"] = {"status": "skipped", "reason": "No audio stream."}
        stages["transcript"] = {"status": "skipped", "reason": "No audio stream."}
    else:
        try:
            normalized_audio = extract_audio(ffmpeg, input_path, selected_audio, output, commands)
            stages["audio"] = {
                "status": "completed",
                "selected_stream_index": as_int(selected_audio.get("index"), -1),
                "file": "intermediates/audio.wav" if config["keep_intermediates"] else None,
            }
            stages["transcript"] = transcribe_audio(normalized_audio, output, config, ffmpeg)
            if not config["keep_intermediates"]:
                remove_intermediate_audio(output)
        except Exception as error:
            stages["errors"].append(str(error))
            stages["transcript"] = {"status": "failed", "reason": str(error)}

    if not video_streams:
        stages["frames"] = {"status": "skipped", "reason": "No video stream."}
    else:
        try:
            stages["frames"] = extract_frames(
                ffmpeg, input_path, duration, config, output, commands, script_path
            )
        except Exception as error:
            stages["errors"].append(str(error))
            stages["frames"] = {"status": "failed", "reason": str(error)}

    evidence_index = build_evidence_index(input_path, media, stages, output)
    write_json(output / "evidence-index.json", evidence_index)
    stage_warnings = list(preflight["warnings"])
    for stage_name, stage in stages.items():
        if stage_name == "errors" or not isinstance(stage, dict):
            continue
        warnings = stage.get("warnings")
        if isinstance(warnings, list):
            stage_warnings.extend(str(item) for item in warnings)
        if stage.get("status") == "warning" and isinstance(stage.get("reason"), str):
            stage_warnings.append(stage["reason"])
    report = {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": "completed" if not stages["errors"] else "failed",
        "input_path": str(input_path.resolve()),
        "warnings": stage_warnings,
        "errors": stages["errors"],
        "stages": stages,
        "commands": commands,
    }
    write_json(output / "run-report.json", report)
    return 0 if not stages["errors"] else 1


def validate_output(output: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    required = ["preflight.json", "media.json", "run-report.json", "evidence-index.json"]
    for name in required:
        exists = (output / name).is_file()
        checks[name] = {"exists": exists}
        if not exists:
            errors.append(f"Missing required artifact: {name}")
    if errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "status": "fail",
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
        }

    try:
        media = read_json(output / "media.json")
        run_report = read_json(output / "run-report.json")
        evidence = read_json(output / "evidence-index.json")
    except (OSError, json.JSONDecodeError) as error:
        errors.append(f"Cannot parse core JSON artifact: {error}")
        return {
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "status": "fail",
            "checks": checks,
            "warnings": warnings,
            "errors": errors,
        }

    duration = as_float(media.get("duration_seconds"))
    checks["media_duration"] = duration
    if duration is None or duration <= 0:
        warnings.append("Media duration is unavailable or non-positive.")

    audio_streams = media_streams(media, "audio")
    video_streams = media_streams(media, "video")
    transcript = evidence.get("entrypoints", {}).get("transcript") if isinstance(evidence.get("entrypoints"), dict) else None
    frames_index_path = evidence.get("entrypoints", {}).get("frames") if isinstance(evidence.get("entrypoints"), dict) else None

    if audio_streams:
        if not isinstance(transcript, str) or not (output / transcript).is_file():
            errors.append("Input has audio but transcript JSON is missing.")
        else:
            try:
                transcript_data = read_json(output / transcript)
                segments = transcript_data.get("segments", []) if isinstance(transcript_data, dict) else []
                end_times = [as_float(segment.get("end")) for segment in segments if isinstance(segment, dict)]
                coverage_end = max((value for value in end_times if value is not None), default=0.0)
                checks["transcript"] = {"segments": len(segments), "coverage_end_seconds": coverage_end}
                if not segments:
                    warnings.append("Transcript has no speech segments; verify that the audio is not silent or unsupported.")
                elif duration and coverage_end < duration * 0.25:
                    warnings.append("Transcript timestamps cover less than 25% of media duration; inspect the audio and language setting.")
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"Transcript JSON is unreadable: {error}")
    else:
        checks["transcript"] = {"status": "not_applicable"}

    if video_streams:
        if not isinstance(frames_index_path, str) or not (output / frames_index_path).is_file():
            errors.append("Input has video but frames/index.json is missing.")
        else:
            try:
                frames_data = read_json(output / frames_index_path)
                frames = frames_data.get("frames", []) if isinstance(frames_data, dict) else []
                missing = []
                for frame in frames:
                    filename = frame.get("file") if isinstance(frame, dict) else None
                    if not isinstance(filename, str) or not (output / "frames" / filename).is_file():
                        missing.append(filename)
                checks["frames"] = {"count": len(frames), "missing_files": missing}
                if not frames:
                    errors.append("Frame index contains no frames.")
                if missing:
                    errors.append(f"Frame files are missing: {missing}")
                visual = frames_data.get("contact_sheet_jpg") or frames_data.get("contact_sheet_html")
                if isinstance(visual, str) and not (output / visual).is_file():
                    warnings.append("Frame contact sheet is missing; use frames/index.json directly.")
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"Frame index is unreadable: {error}")
    else:
        checks["frames"] = {"status": "not_applicable"}

    if run_report.get("status") != "completed":
        errors.append("Run report is not completed.")
    report_warnings = run_report.get("warnings", [])
    if isinstance(report_warnings, list):
        warnings.extend(str(item) for item in report_warnings)

    status = "fail" if errors else "review" if warnings else "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "created_at": utc_now(),
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "errors": errors,
    }


def write_default_config(target: Path) -> None:
    if target.exists():
        raise PipelineError(f"Refusing to overwrite existing config: {target}")
    write_json(target, DEFAULT_CONFIG)


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description="Extract timestamped, validated evidence from local media files."
    )
    subcommands = argument_parser.add_subparsers(dest="command", required=True)

    init_config = subcommands.add_parser("init-config", help="Write a default JSON configuration.")
    init_config.add_argument("--output", required=True, help="New JSON config path.")

    for name, help_text in (
        ("preflight", "Check the runtime and input media."),
        ("run", "Generate media evidence."),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("--input", required=True, help="Local video or audio file.")
        command.add_argument("--output", required=True, help="Evidence output directory.")
        command.add_argument("--config", help="Optional JSON configuration path.")

    validate = subcommands.add_parser("validate", help="Validate an evidence output directory.")
    validate.add_argument("--output", required=True, help="Evidence output directory.")
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    script_path = Path(__file__).resolve()
    try:
        if args.command == "init-config":
            write_default_config(Path(args.output).expanduser().resolve())
            print(f"Created config: {Path(args.output).expanduser().resolve()}")
            return 0

        if args.command in {"preflight", "run"}:
            input_path = Path(args.input).expanduser().resolve()
            output = Path(args.output).expanduser().resolve()
            config = load_config(args.config)
            if args.command == "preflight":
                output.mkdir(parents=True, exist_ok=True)
                preflight = build_preflight(input_path, config, script_path)
                write_json(output / "preflight.json", preflight)
                print(f"Preflight status: {preflight['status']}")
                return 0 if preflight["status"] == "ready" else 2
            result = run_pipeline(input_path, output, config, script_path)
            print("Run completed." if result == 0 else "Run completed with failures; inspect run-report.json.")
            return result

        if args.command == "validate":
            output = Path(args.output).expanduser().resolve()
            report = validate_output(output)
            write_json(output / "validation.json", report)
            print(f"Validation status: {report['status']}")
            return 0 if report["status"] != "fail" else 1
    except PipelineError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    except Exception as error:  # Keep a machine-readable report when possible, without hiding bugs.
        print(f"UNEXPECTED ERROR: {type(error).__name__}: {error}", file=sys.stderr)
        return 3
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
