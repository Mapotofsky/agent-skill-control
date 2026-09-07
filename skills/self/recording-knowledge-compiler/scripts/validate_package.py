#!/usr/bin/env python3
"""Read-only structural validator for a recording knowledge package."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


REQUIRED_FILES = (
    "01_术语与纠错表.md",
    "02_完整书面稿.md",
    "04_待回听确认项.md",
    "05_内容覆盖表.md",
)
DEFAULT_FINALS = ("03_知识点讲义.md", "03_指导手册.md")


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    path: str | None = None
    line: int | None = None


class Report:
    def __init__(self, package_dir: Path) -> None:
        self.package_dir = package_dir
        self.issues: list[Issue] = []
        self.metrics: dict[str, object] = {}
        self.files: dict[str, str] = {}

    def error(self, code: str, message: str, path: Path | None = None, line: int | None = None) -> None:
        self.issues.append(Issue("error", code, message, str(path) if path else None, line))

    def warn(self, code: str, message: str, path: Path | None = None, line: int | None = None) -> None:
        self.issues.append(Issue("warning", code, message, str(path) if path else None, line))

    @property
    def exit_code(self) -> int:
        if any(item.severity == "error" for item in self.issues):
            return 2
        if self.issues:
            return 1
        return 0

    @property
    def status(self) -> str:
        return {0: "pass", 1: "review", 2: "fail"}[self.exit_code]


def read_text(path: Path, report: Report) -> str | None:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = path.read_text(encoding=encoding)
            report.files[path.name] = str(path)
            if not text.strip():
                report.error("EMPTY_FILE", "文件为空。", path)
            return text
        except UnicodeDecodeError:
            continue
        except OSError as exc:
            report.error("READ_ERROR", f"无法读取文件：{exc}", path)
            return None
    report.error("ENCODING_ERROR", "文件不是可识别的 UTF-8 或 GB18030 文本。", path)
    return None


def markdown_headings(text: str) -> list[tuple[int, int, str]]:
    headings: list[tuple[int, int, str]] = []
    fence: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in ("```", "~~~"):
            if fence is None:
                fence = marker
            elif fence == marker:
                fence = None
            continue
        if fence is not None:
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            headings.append((number, len(match.group(1)), match.group(2)))
    return headings


def validate_heading_structure(text: str, path: Path, report: Report) -> None:
    headings = markdown_headings(text)
    h1 = [item for item in headings if item[1] == 1]
    if len(h1) != 1:
        report.error("H1_COUNT", f"必须且只能有一个 H1，当前为 {len(h1)} 个。", path)
    first_content = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_content.startswith("# "):
        report.error("H1_FIRST", "首个非空内容必须是 H1。", path)
    for previous, current in zip(headings, headings[1:]):
        if current[1] > previous[1] + 1:
            report.error(
                "HEADING_JUMP",
                f"标题从 H{previous[1]} 跳到 H{current[1]}。",
                path,
                current[0],
            )


def line_matches(text: str, pattern: re.Pattern[str]) -> Iterable[tuple[int, str]]:
    for number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            yield number, line.strip()


def validate_final(text: str, path: Path, report: Report) -> None:
    validate_heading_structure(text, path, report)
    hard_patterns = {
        "SOURCE_TAG": re.compile(r"【(?:录音|课件[^】]*|图片[^】]*|完整课件[^】]*|术语纠正|外部扩展)】"),
        "EDITORIAL_LEAK": re.compile(r"待回听确认|建议核验|证据路径|来源文件|编辑说明|参见(?:书面稿|课件|图片)"),
        "DETACHED_SUPPLEMENT": re.compile(r"^#{1,6}\s+.*(?:课件|图片|录音|资料)补充", re.MULTILINE),
    }
    for code, pattern in hard_patterns.items():
        for number, snippet in line_matches(text, pattern):
            report.error(code, f"最终稿包含内部来源或编辑信息：{snippet[:100]}", path, number)

    warning_patterns = {
        "TIMESTAMP": re.compile(r"(?<!\d)\d{1,2}:\d{2}:\d{2}(?!\d)"),
        "MEDIA_FILENAME": re.compile(r"\b[^\s<>|]+\.(?:mp3|wav|m4a|mp4|mov|pptx?|pdf|jpe?g|png)\b", re.IGNORECASE),
        "STAGE_LANGUAGE": re.compile(r"谢谢大家|今天就讲到这里|我的分享就到这里|下面有请|掌声欢迎"),
    }
    for code, pattern in warning_patterns.items():
        matches = list(line_matches(text, pattern))
        if matches:
            number, snippet = matches[0]
            report.warn(code, f"最终稿可能含不适合知识库的内容，共 {len(matches)} 处；首处：{snippet[:100]}", path, number)


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if not (value.startswith("|") and value.endswith("|")):
        return []
    return [cell.strip() for cell in value[1:-1].split("|")]


def is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


def tables(text: str) -> list[tuple[int, list[str], list[list[str]]]]:
    lines = text.splitlines()
    found: list[tuple[int, list[str], list[list[str]]]] = []
    index = 0
    while index + 1 < len(lines):
        header = split_table_row(lines[index])
        separator = split_table_row(lines[index + 1])
        if header and len(header) == len(separator) and is_separator(separator):
            rows: list[list[str]] = []
            cursor = index + 2
            while cursor < len(lines):
                row = split_table_row(lines[cursor])
                if not row:
                    break
                if len(row) == len(header):
                    rows.append(row)
                cursor += 1
            found.append((index + 1, header, rows))
            index = cursor
        else:
            index += 1
    return found


def find_column(header: list[str], patterns: tuple[str, ...]) -> int | None:
    for index, cell in enumerate(header):
        if any(re.search(pattern, cell, re.IGNORECASE) for pattern in patterns):
            return index
    return None


def validate_coverage(text: str, path: Path, report: Report) -> None:
    validate_heading_structure(text, path, report)
    usable: list[tuple[int, list[str], list[list[str]], int, int, int]] = []
    for line, header, rows in tables(text):
        source = find_column(header, (r"来源", r"时间范围", r"页码", r"材料单元", r"证据单元"))
        written = find_column(header, (r"(^|\b)02(\b|\s)", r"书面稿"))
        final = find_column(
            header,
            (r"(^|\b)03(\b|\s)", r"讲义位置", r"手册位置", r"指南位置", r"最终稿"),
        )
        if source is not None and written is not None and final is not None:
            usable.append((line, header, rows, source, written, final))
    if not usable:
        report.error("COVERAGE_SCHEMA", "未找到同时包含来源单元、书面稿落点和最终稿落点的覆盖表。", path)
        return
    row_count = 0
    generic = re.compile(r"^(?:是|否|已覆盖|已补充|已纳入|见上|同上|见正文|完成|无)$")
    for line, _header, rows, source, written, final in usable:
        row_count += len(rows)
        for offset, row in enumerate(rows, start=2):
            if not row[source]:
                report.error("COVERAGE_SOURCE_EMPTY", "覆盖行缺少可定位来源单元。", path, line + offset)
            for label, index in (("02", written), ("03", final)):
                value = row[index].strip()
                if not value or generic.fullmatch(value):
                    report.error(
                        "COVERAGE_PLACEHOLDER",
                        f"{label} 落点必须是具体标题或 04 条目，当前为“{value}”。",
                        path,
                        line + offset,
                    )
    if row_count == 0:
        report.error("COVERAGE_EMPTY", "覆盖表没有数据行。", path)
    report.metrics["coverage_rows"] = row_count


def validate_uncertainties(text: str, path: Path, report: Report) -> None:
    resolved_markers = re.compile(r"无需回听|无需确认|已完成冲突处置|已解决(?:的)?冲突")
    matches = list(line_matches(text, resolved_markers))
    if matches:
        number, snippet = matches[0]
        report.warn(
            "RESOLVED_ITEM_IN_UNCERTAINTIES",
            f"04 可能收录了已解决事项；已解决冲突应移至 01 与 05。首处：{snippet[:100]}",
            path,
            number,
        )


def substantive_lines(text: str) -> list[str]:
    result: list[str] = []
    for line in text.splitlines():
        value = re.sub(r"\s+", " ", line.strip())
        if not value or re.fullmatch(r"[-|: ]+", value):
            continue
        result.append(value)
    return result


def validate_baseline(baseline: Path, final_text: str, report: Report) -> None:
    baseline_text = read_text(baseline, report)
    if baseline_text is None:
        return
    old = substantive_lines(baseline_text)
    new = set(substantive_lines(final_text))
    retained = [line for line in old if line in new]
    removed = [line for line in old if line not in new]
    ratio = len(retained) / len(old) if old else 1.0
    report.metrics["baseline"] = {
        "substantive_lines": len(old),
        "exactly_retained_lines": len(retained),
        "exact_retention_ratio": round(ratio, 4),
        "unmatched_examples": removed[:10],
    }
    report.warn(
        "BASELINE_MANUAL_REVIEW",
        f"增量模式必须人工审查差异：{len(retained)}/{len(old)} 个实质行完全保留；未完全匹配 {len(removed)} 行。比率不证明语义损失。",
        baseline,
    )


def resolve_final(package_dir: Path, value: str | None, report: Report) -> Path | None:
    if value:
        path = Path(value)
        return path if path.is_absolute() else package_dir / path
    candidates = [package_dir / name for name in DEFAULT_FINALS if (package_dir / name).is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        report.error("FINAL_AMBIGUOUS", "同时发现两种默认最终稿；请用 --final 明确指定。", package_dir)
    else:
        report.error("FINAL_MISSING", "未找到 03_知识点讲义.md 或 03_指导手册.md。", package_dir)
    return None


def validate(args: argparse.Namespace) -> Report:
    package_dir = Path(args.package_dir).resolve()
    report = Report(package_dir)
    if not package_dir.is_dir():
        report.error("PACKAGE_DIR", "知识编译包目录不存在或不是目录。", package_dir)
        return report

    texts: dict[str, str] = {}
    for name in REQUIRED_FILES:
        path = package_dir / name
        if not path.is_file():
            report.error("REQUIRED_FILE", f"缺少必需文件：{name}", path)
            continue
        text = read_text(path, report)
        if text is not None:
            texts[name] = text
            validate_heading_structure(text, path, report)

    final_path = resolve_final(package_dir, args.final, report)
    final_text: str | None = None
    if final_path is not None:
        if not final_path.is_file():
            report.error("FINAL_FILE", "指定的最终稿不存在。", final_path)
        else:
            final_text = read_text(final_path, report)
            if final_text is not None:
                validate_final(final_text, final_path, report)

    coverage = texts.get("05_内容覆盖表.md")
    if coverage is not None:
        validate_coverage(coverage, package_dir / "05_内容覆盖表.md", report)

    uncertainties = texts.get("04_待回听确认项.md")
    if uncertainties is not None:
        validate_uncertainties(uncertainties, package_dir / "04_待回听确认项.md", report)

    if args.baseline:
        baseline = Path(args.baseline)
        if not baseline.is_absolute():
            baseline = package_dir / baseline
        if not baseline.is_file():
            report.error("BASELINE_FILE", "指定的基线文件不存在。", baseline)
        elif final_text is not None:
            validate_baseline(baseline, final_text, report)

    report.metrics["mechanical_scope"] = "结构与禁用模式；不证明语义完整性"
    return report


def emit(report: Report, as_json: bool) -> None:
    payload = {
        "status": report.status,
        "exit_code": report.exit_code,
        "package_dir": str(report.package_dir),
        "files": report.files,
        "metrics": report.metrics,
        "issues": [asdict(item) for item in report.issues],
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print(f"status: {report.status} (exit {report.exit_code})")
    print(f"package: {report.package_dir}")
    if report.metrics:
        print("metrics:")
        for key, value in report.metrics.items():
            print(f"  {key}: {value}")
    if not report.issues:
        print("issues: none")
    else:
        print("issues:")
        for issue in report.issues:
            location = issue.path or ""
            if issue.line:
                location = f"{location}:{issue.line}"
            print(f"  [{issue.severity.upper()}] {issue.code} {location} {issue.message}".rstrip())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="只读校验录音知识编译五件套；退出码 0=通过、1=需复核、2=硬性失败。"
    )
    parser.add_argument("package_dir", help="五件套所在目录")
    parser.add_argument("--final", help="最终稿路径；相对路径按 package_dir 解析")
    parser.add_argument("--baseline", help="增量更新前的基线文件；启用保真复核报告")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = validate(args)
    emit(report, args.json)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
