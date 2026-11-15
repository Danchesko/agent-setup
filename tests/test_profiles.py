import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/profiles.py"


class ProfilesTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.public = self.home / "agents/agent-setup"
        self.private = self.home / "agents/agent-skills-private"
        self.public.mkdir(parents=True)
        self.private.mkdir()
        (self.public / "AGENTS.md").write_text("Repository instructions.\n")
        self.publish_skill(self.public, "sample")
        (self.public / "profile.toml").write_text('[skills]\nsample = ["codex", "claude"]\n')
        (self.private / "rules").mkdir()
        (self.private / "rules/common.md").write_text("Custom policy.\n")
        (self.private / "profile.toml").write_text('[rules]\n"rules/common.md" = ["codex"]\n')
        self.codex = self.home / ".agents/skills/sample"
        self.claude = self.home / ".claude/skills/sample"
        self.codex_rules = self.home / ".codex/AGENTS.md"
        self.claude_rules = self.home / ".claude/CLAUDE.md"

    @staticmethod
    def publish_skill(root, name):
        target = root / "skills" / name
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("# A skill\n")
        return target

    def apply_profile(self, *args, success=True):
        environment = os.environ.copy()
        environment.pop("CODEX_HOME", None)
        environment.pop("CLAUDE_CONFIG_DIR", None)
        environment["HOME"] = str(self.home)
        result = subprocess.run([sys.executable, SCRIPT, self.public, *args], env=environment,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stderr + result.stdout)
        return result

    def test_public_and_private_then_remove_assignments(self):
        self.apply_profile()
        self.assertTrue(self.codex.samefile(self.public / "skills/sample"))
        self.assertTrue(self.claude.samefile(self.codex))
        self.assertIn(str(self.public / "AGENTS.md"), self.codex_rules.read_text())
        self.assertNotIn("Custom policy.", self.claude_rules.read_text())
        self.apply_profile(self.private)
        self.assertIn("Custom policy.", self.codex_rules.read_text())
        self.assertNotIn("Custom policy.", self.claude_rules.read_text())
        before = self.codex_rules.stat().st_mtime_ns
        self.apply_profile(self.private)
        self.assertEqual(self.codex_rules.stat().st_mtime_ns, before)
        (self.public / "profile.toml").write_text('[skills]\nsample = ["claude"]\n')
        self.apply_profile()
        self.assertFalse(self.codex.is_symlink())
        self.assertTrue(self.claude.is_symlink())
        self.assertNotIn("Custom policy.", self.codex_rules.read_text())

    def test_conflict_then_migrate_shared_legacy_links(self):
        self.codex.mkdir(parents=True)
        (self.codex / "SKILL.md").write_text("Local edits.\n")
        self.claude.parent.mkdir(parents=True)
        self.claude.symlink_to(self.codex)
        old_rules = self.home / ".agents/AGENTS.md"
        old_rules.write_text("Custom policy.\n")
        for path in (self.codex_rules, self.claude_rules):
            path.parent.mkdir(exist_ok=True)
            path.symlink_to(old_rules)
        self.apply_profile(self.private, success=False)
        self.assertFalse(self.codex.is_symlink())
        (self.private / "profile.toml").write_text('[rules]\n"rules/common.md" = ["codex", "claude"]\n')
        self.apply_profile(self.private, "--adopt")
        self.assertEqual(old_rules.read_text(), "Custom policy.\n")
        self.assertEqual(self.codex_rules.read_text().count("Custom policy."), 1)
        self.assertTrue(self.claude.samefile(self.public / "skills/sample"))
        backups = self.home / "Library/Application Support/agent-setup/profiles/backups"
        self.assertTrue(any(p.read_text() == "Local edits.\n" for p in backups.rglob("SKILL.md")))
        (self.private / "rules/common.md").write_text("Revised policy.\n")
        self.apply_profile(self.private)
        self.assertNotIn("Custom policy.", self.claude_rules.read_text())

    def test_keep_unrelated_global_text_and_replaced_skill(self):
        self.codex_rules.parent.mkdir()
        self.codex_rules.write_text("Existing instructions.\n")
        self.apply_profile()
        self.assertIn("Existing instructions.", self.codex_rules.read_text())
        self.codex.unlink()
        self.codex.mkdir()
        (self.codex / "mine").touch()
        self.apply_profile(success=False)
        (self.public / "profile.toml").write_text('[skills]\nsample = ["claude"]\n')
        self.apply_profile()
        self.assertTrue((self.codex / "mine").exists())

    def test_invalid_assignment_is_reported_before_any_edit(self):
        (self.public / "profile.toml").write_text('[skills]\nsample = ["codex"]\n"../other" = ["claude"]\n')
        self.apply_profile(success=False)
        self.assertFalse(self.codex.exists())
        self.assertFalse(self.codex_rules.exists())


if __name__ == "__main__":
    unittest.main()
