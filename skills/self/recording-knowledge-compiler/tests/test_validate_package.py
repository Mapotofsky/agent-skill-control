"""Exercise package validation with real Markdown files and cross-file references."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_package as validator


class PackageValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.package = Path(self.temp.name)
        self.write("01_术语与纠错表.md", "# 纠错\n\n本轮没有纠错。\n")
        self.write("02_完整书面稿.md", "# 书面稿\n\n## 原始讨论\n\n保留具体内容。\n")
        self.write("04_待回听确认项.md", "# 确认项\n\n本轮未发现需要回听确认的事项。\n")
        self.coverage("议题一")

    def write(self, name, text):
        (self.package / name).write_text(text, encoding="utf-8")

    def coverage(self, final, written="原始讨论"):
        self.write(
            "05_内容覆盖表.md",
            "# 覆盖表\n\n| 来源单元 | 02 落点 | 03 落点 |\n"
            "| --- | --- | --- |\n"
            f"| 转写甲 00:00—00:30 | {written} | {final} |\n",
        )

    def report(self, *extra):
        return validator.validate(validator.parse_args([str(self.package), *extra]))

    def codes(self, report):
        return {issue.code for issue in report.issues}

    def test_each_default_final_is_discovered(self):
        for name in ("03_知识点讲义.md", "03_指导手册.md", "03_会议文档.md"):
            with self.subTest(name=name):
                self.write(name, "# 成品\n\n## 议题一\n\n具体内容。\n")
                self.assertEqual(self.report().exit_code, 0)
                (self.package / name).unlink()

    def test_multiple_finals_require_selection(self):
        for name in ("03_知识点讲义.md", "03_会议文档.md"):
            self.write(name, "# 成品\n\n## 议题一\n\n具体内容。\n")
        self.assertIn("FINAL_AMBIGUOUS", self.codes(self.report()))
        self.assertEqual(self.report("--final", "03_会议文档.md").exit_code, 0)

    def test_missing_coverage_heading_is_rejected_in_each_document(self):
        self.write("03_会议文档.md", "# 成品\n\n## 议题一\n\n具体内容。\n")
        for final, written in (("不存在的标题", "原始讨论"), ("议题一", "不存在的标题")):
            with self.subTest(final=final, written=written):
                self.coverage(final, written)
                self.assertIn("COVERAGE_TARGET_MISSING", self.codes(self.report()))

    def test_all_destinations_in_a_cell_are_checked(self):
        self.write("03_会议文档.md", "# 成品\n\n## 议题一\n\n内容。\n\n## 议题二\n\n内容。\n")
        self.coverage("议题一；议题二")
        self.assertEqual(self.report().exit_code, 0)
        self.coverage("议题一；不存在的标题")
        self.assertIn("COVERAGE_TARGET_MISSING", self.codes(self.report()))

    def test_uncertainty_and_exclusion_destinations_remain_supported(self):
        self.write("03_会议文档.md", "# 成品\n\n## 议题一\n\n具体内容。\n")
        self.write("04_待回听确认项.md", "# 确认项\n\n## R1\n\n数值不清。\n")
        self.write("01_术语与纠错表.md", "# 纠错\n\n## C1\n\n无语义串场不纳入。\n")
        self.coverage("04：R1", "不纳入：无语义串场，01 C1")
        self.assertEqual(self.report().exit_code, 0)

    def test_internal_body_links_are_rejected(self):
        links = (
            "[[来源/转写|原文]]",
            "[原文](../来源.md)",
            "[原文](<D:/会议 资料/转写.md>)",
            "[原文](#原始讨论)",
        )
        for link in links:
            with self.subTest(link=link):
                self.write("03_会议文档.md", f"# 成品\n\n## 议题一\n\n{link}\n")
                self.assertIn("INTERNAL_LINK", self.codes(self.report()))

    def test_project_metadata_is_outside_final_body_checks(self):
        self.write(
            "03_会议文档.md",
            '---\nsources:\n  - "[[来源/转写]]"\n---\n\n# 成品\n\n## 议题一\n\n正文内容。\n',
        )
        self.assertEqual(self.report().exit_code, 0)
        with (self.package / "03_会议文档.md").open("a", encoding="utf-8") as stream:
            stream.write("[[来源/转写]]\n")
        report = self.report()
        issue = next(issue for issue in report.issues if issue.code == "INTERNAL_LINK")
        self.assertEqual(issue.line, 11)

    def test_business_urls_are_not_internal_evidence_links(self):
        self.write(
            "03_会议文档.md",
            "# 成品\n\n## 议题一\n\n[办理入口](https://example.com)\n"
            "[办理入口](<https://example.com>)\n",
        )
        self.assertNotIn("INTERNAL_LINK", self.codes(self.report()))


if __name__ == "__main__":
    unittest.main()
