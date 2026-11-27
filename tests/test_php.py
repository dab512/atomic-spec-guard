"""CLI acceptance for PHP comments, source locations and coverage."""

import subprocess
import tempfile
import unittest
from pathlib import Path

import test_reverse_and_links as reverse
from test_detector import P

SOURCE = f"""<div>// {reverse.URI}</div>
<?php
namespace Demo;

/** {reverse.URI}
 * Класс соблюдает ограничение тарифа.
 */
#[Example]
final class Fare {{
    # {reverse.URI}
    // Метод вычисляет нижнюю границу.
    public function minimum(): int {{
        $fake = "// {reverse.URI}";
        $template = <<<'NOTE'
// {reverse.URI}
NOTE;
        return 100 |> abs(...);
    }}
}}
throw new \\RuntimeException('The source must never run');
"""


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/AC-1
# Проверяем публичные команды на обычном PHP-файле без исполнения его инструкций.
class PhpTests(unittest.TestCase):
    invoke = reverse.ReverseTests.invoke
    fixture = reverse.ReverseTests.fixture

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/AC-1
    # PHPDoc перед атрибутом покрывает класс, а строка, HTML и nowdoc не создают лишних ссылок.
    def test_php_audit_and_comments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "src").mkdir()
            (root / "src/fare.php").write_text(SOURCE)
            config = P / "examples/minimal/specs/atomic-spec-guard.yaml"
            (root / "policy.yaml").write_text(config.read_text())
            code, audit = self.invoke(root, "audit", "--config", "policy.yaml", "--directory", "src")
            self.assertEqual(code, 0, audit)
            self.assertTrue(audit["complete"], audit)
            self.assertEqual(["src/fare.php"], [item["file"] for item in audit["files"]])
            code, report = self.invoke(root, "comments", "--config", "policy.yaml", files=["src/fare.php"])
            self.assertEqual(code, 0, report)
            self.assertFalse(report["excluded"], report)
            self.assertEqual(
                [(item["line"], [owner["block"] for owner in item["owners"]]) for item in report["comments"]],
                [(5, ["Fare"]), (10, ["minimum"])],
            )

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-8
    # Комментарий после завершённого оператора остаётся в отчёте и не покрывает следующее объявление.
    def test_php_trailing_comment_does_not_cover_next_function(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "fare.php").write_text(f"<?php\n$value = 100; // {reverse.URI} — Граница.\nfunction fare() {{}}\n")
            config = P / "examples/minimal/specs/atomic-spec-guard.yaml"
            (root / "policy.yaml").write_text(config.read_text())
            code, report = self.invoke(root, "comments", "--config", "policy.yaml", files=["fare.php"])
            self.assertEqual(code, 1, report)
            self.assertEqual([item["code"] for item in report["diagnostics"]], ["SPEC_COVER"])
            self.assertEqual(report["comments"][0]["owners"], [])

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/AC-1
    # Пропущенное пояснение и синтаксическая ошибка дают разные явные диагностики.
    def test_php_invalid_annotation_and_syntax(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            for source, diagnostic in (
                (SOURCE.replace("    // Метод вычисляет нижнюю границу.\n", ""), "SPEC002"),
                ("<?php function broken( {", "SPEC008"),
            ):
                (root / "fare.php").write_text(source)
                code, report = self.invoke(root, "audit", files=["fare.php"])
                self.assertEqual(code, 1, report)
                self.assertIn(diagnostic, {item["code"] for item in report["diagnostics"]})

    # atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-2
    # Удаление PHPDoc в рабочей копии оставляет обязательство на уцелевшем классе.
    def test_php_diff_preserves_class_coverage_after_comment_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            source = root / "fare.php"
            source.write_text(SOURCE)
            config = P / "examples/minimal/specs/atomic-spec-guard.yaml"
            (root / "policy.yaml").write_text(
                config.read_text().replace(
                    "      node:\n        in:\n          - function\n          - type\n          - scenario",
                    "      all:\n        - language: {eq: php}\n        - node: {eq: type}",
                )
            )
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "add", "fare.php"], cwd=root, check=True)
            subprocess.run(
                ["git", "-c", "user.name=Test", "-c", "user.email=test@example.org", "commit", "-qm", "Baseline"],
                cwd=root,
                check=True,
            )
            source.write_text(SOURCE.replace(f"/** {reverse.URI}\n * Класс соблюдает ограничение тарифа.\n */\n", ""))
            code, report = self.invoke(
                root, "check", "--config", "policy.yaml", "--scope", "fare.php", "--base", "HEAD", "--working-tree"
            )
            self.assertEqual(code, 1, report)
            self.assertEqual(
                [(item["code"], item["block"]) for item in report["diagnostics"]], [("SPEC_COVER", "Fare")]
            )
