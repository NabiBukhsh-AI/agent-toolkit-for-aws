"""Regression tests for the Markdown scopes used by PR and merge queue builds."""

import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "lint-markdown.py"
SPEC = importlib.util.spec_from_file_location("lint_markdown", SCRIPT)
lint_markdown = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lint_markdown)


class MarkdownScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Lint test")
        self.git("config", "user.email", "lint@example.com")
        self.write("plugins/other/README.md", "# Other\n")
        self.write("plugins/other/guide.md", "# Guide\n")
        self.write("plugins/aws-startup-advisor/README.md", "# Startup advisor\n")
        self.write("README.md", "# Repository\n")
        self.write("docs/unchanged.md", "# Shared\n")
        self.base = self.commit()

    def git(self, *args):
        return subprocess.check_output(
            ["git", *args], cwd=self.repo, stderr=subprocess.PIPE,
        ).decode().strip()

    def write(self, name, content):
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "Test fixture")
        return self.git("rev-parse", "HEAD")

    def lint_command(self, base=None, result=0):
        head = self.git("rev-parse", "HEAD")
        real_run = subprocess.run
        commands = []

        def run(command, **kwargs):
            if command[0] == "markdownlint-cli2":
                commands.append(command)
                return subprocess.CompletedProcess(command, result)
            return real_run(command, **kwargs)

        previous = Path.cwd()
        os.chdir(self.repo)
        try:
            with patch("sys.argv", [str(SCRIPT), "--base", base or self.base, "--head", head]):
                with patch.object(lint_markdown.subprocess, "run", side_effect=run):
                    status = lint_markdown.main()
        finally:
            os.chdir(previous)
        return status, commands

    def test_plugin_code_change_checks_whole_plugin_only(self):
        self.write("plugins/other/tool.py", "print('changed')\n")
        self.commit()
        status, commands = self.lint_command()
        self.assertEqual(status, 0)
        self.assertEqual(commands[0][2:], [
            ":plugins/other/README.md", ":plugins/other/guide.md",
        ])

    def test_shared_markdown_checks_only_changed_files_as_literals(self):
        self.write("docs/a [draft] with spaces.md", "# Draft\n")
        self.commit()
        _, commands = self.lint_command()
        self.assertEqual(commands[0][2:], [":docs/a [draft] with spaces.md"])

    def test_deletion_checks_remaining_plugin_markdown(self):
        self.git("rm", "plugins/other/guide.md")
        self.commit()
        _, commands = self.lint_command()
        self.assertEqual(commands[0][2:], [":plugins/other/README.md"])

    def test_cross_plugin_rename_checks_both_plugins(self):
        self.git("mv", "plugins/other/guide.md", "plugins/aws-startup-advisor/guide.md")
        self.commit()
        _, commands = self.lint_command()
        self.assertEqual(commands[0][2:], [
            ":plugins/aws-startup-advisor/README.md",
            ":plugins/aws-startup-advisor/guide.md",
            ":plugins/other/README.md",
        ])

    def test_deleted_shared_markdown_is_skipped(self):
        self.git("rm", "docs/unchanged.md")
        self.commit()
        self.assertEqual(self.lint_command(), (0, []))

    def test_no_markdown_in_scope_is_successful(self):
        self.write("tools/tool.py", "print('changed')\n")
        self.commit()
        self.assertEqual(self.lint_command(), (0, []))

    def test_shared_inputs_require_full_lint(self):
        for path in (".markdownlint-cli2.yaml", "mise.toml"):
            with self.subTest(path=path):
                base = self.git("rev-parse", "HEAD")
                self.write(path, "# Shared configuration\n")
                self.commit()
                _, commands = self.lint_command(base=base)
                self.assertEqual(commands[0][2:], ["**/*.md", "#node_modules"])

    def test_linter_failure_is_propagated(self):
        self.write("README.md", "# Changed\n")
        self.commit()
        status, _ = self.lint_command(result=1)
        self.assertEqual(status, 1)

    def test_merge_group_checks_all_changes_since_queue_base(self):
        self.write("plugins/other/tool.py", "print('first PR')\n")
        self.commit()
        self.write("README.md", "# Second PR\n")
        self.commit()
        _, commands = self.lint_command()
        self.assertEqual(commands[0][2:], [
            ":README.md", ":plugins/other/README.md", ":plugins/other/guide.md",
        ])

    def test_node_modules_are_excluded(self):
        paths = lint_markdown.select_paths(
            ["plugins/other/tool.py"],
            ["plugins/other/README.md", "plugins/other/node_modules/dependency/README.md"],
        )
        self.assertEqual(paths, ["plugins/other/README.md"])


if __name__ == "__main__":
    unittest.main()
