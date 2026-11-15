import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.watch import ensure_commit_identity, github_origin, service_config, sync_status


class WatchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.repo = self.base / "profile"
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.base)
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-qm", "Initial profile")

    def git(self, *args, cwd=None):
        return subprocess.run(
            ["git", *args], check=True, capture_output=True, cwd=cwd or self.repo,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
        )

    def test_checks_real_push_destination(self):
        self.git("remote", "add", "origin", "https://github.com/owner/private.git")
        self.assertEqual(github_origin(self.repo), "owner/private")
        self.git("config", "remote.origin.pushurl", "git@github.com:owner/public.git")
        with self.assertRaisesRegex(ValueError, "different repositories"):
            github_origin(self.repo)

    def test_status_distinguishes_edits_and_unpushed_commits(self):
        remote = self.base / "remote.git"
        self.git("init", "-q", "--bare", "-b", "main", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-qu", "origin", "main")
        self.assertEqual(sync_status(self.repo), "in sync")
        (self.repo / "skill.md").write_text("a skill")
        self.assertEqual(sync_status(self.repo), "local edits pending")
        self.git("add", "skill.md")
        self.git("commit", "-qm", "Add a skill")
        self.assertEqual(sync_status(self.repo), "local main and origin/main differ")

    def test_missing_commit_email_uses_noreply_and_keeps_name(self):
        self.git("config", "--unset", "user.email")
        with patch.dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"):
            ensure_commit_identity(self.repo, {"login": "owner", "id": 123})
        self.assertEqual(self.git("config", "--get", "user.name").stdout.strip(), b"Test")
        self.assertEqual(self.git("config", "--get", "user.email").stdout.strip(), b"123+owner@users.noreply.github.com")

    def test_topic_branch_tracking_main_cannot_push_to_main(self):
        remote = self.base / "remote.git"
        self.git("init", "-q", "--bare", "-b", "main", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-qu", "origin", "main")
        main_head = self.git("rev-parse", "main").stdout
        self.git("checkout", "-qb", "topic", "--track", "origin/main")
        self.git("commit", "--allow-empty", "-qm", "Topic change")
        self.git("config", "push.default", "upstream")
        env = service_config("public", self.repo, Path("/opt/homebrew/bin"))["EnvironmentVariables"]
        with patch.dict(os.environ, env):
            with self.assertRaises(subprocess.CalledProcessError):
                self.git("push", "origin")
        self.assertEqual(self.git("rev-parse", "main", cwd=remote).stdout, main_head)

    def test_services_use_repository_paths_and_external_logs(self):
        pub = self.repo
        daily = service_config("update", pub, Path("/opt/homebrew/bin"))
        watch = service_config("public", pub, Path("/opt/homebrew/bin"))
        self.assertEqual(daily["ProgramArguments"], [str(pub / "setup"), "update"])
        self.assertNotIn("KeepAlive", daily)
        self.assertTrue(watch["KeepAlive"])
        args = watch["ProgramArguments"]
        self.assertNotIn("-b", args)
        self.assertEqual(args[args.index("-r") + 1], "origin")
        self.assertEqual(args[-1], str(pub))
        self.assertNotIn(pub, Path(watch["StandardErrorPath"]).parents)


if __name__ == "__main__":
    unittest.main()
