import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"scripts"))
import mcp_runtime
import mcp_setup


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"HOME": str(self.home), "CODEX_HOME": str(self.home/".codex"),
                                           "CLAUDE_CONFIG_DIR": str(self.home/".claude")})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.state = self.home/"state.json"

    def test_codex_roundtrip_integer_and_float_timeouts(self):
        config = {"command": "server", "startup_timeout_sec": 60}
        normalized = {**config, "startup_timeout_sec": 60.0}
        self.assertEqual(mcp_setup.fingerprint(config), mcp_setup.fingerprint(normalized))
        self.assertNotEqual(mcp_setup.fingerprint(config), mcp_setup.fingerprint({**config, "startup_timeout_sec": 60.5}))

    def test_credential_only_reaches_runtime(self):
        item = {"service": "example", "account": "worker"}
        token = b"go-keyring-base64:" + base64.b64encode(b"test-token")
        result = subprocess.CompletedProcess([], 0, stdout=token + b"\n")
        with patch.object(subprocess, "run", return_value=result) as run:
            self.assertEqual(mcp_runtime.credential(item), "test-token")
            self.assertEqual(run.call_args.args[0], ["/usr/bin/security", "find-generic-password",
                                                     "-s", "example", "-a", "worker", "-w"])
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 44, stdout=b"")):
            with self.assertRaisesRegex(SystemExit, "Credential unavailable"):
                mcp_runtime.credential(item)

    def test_existing_edited_registration_cannot_be_overwritten(self):
        current = {"example": {"url": "https://personal.example/mcp"}}
        with patch.object(mcp_setup, "client_config", return_value=current), patch.object(mcp_setup, "mutate") as mutate:
            with self.assertRaisesRegex(ValueError, "another installer"):
                mcp_setup.reconcile("codex", {"example": {"url": "https://other.example/mcp"}},
                                    {}, self.state, adopt=True)
            mutate.assert_not_called()

    def test_missing_machine_setting_cannot_register_broken_stdio(self):
        spec = {"local_settings": ["JIRA_URL"], "keychain_env": ["JIRA_TOKEN"]}
        with self.assertRaisesRegex(ValueError, "JIRA_URL, JIRA_TOKEN"):
            mcp_setup.settings_for("jira", spec, {})

    def test_retry_after_interrupted_remove(self):
        old = {"type": "http", "url": "https://old.example/mcp"}
        wanted = {"type": "http", "url": "https://new.example/mcp"}
        state = {"claude": {"example": {"installed": mcp_setup.fingerprint(old), "pending": wanted}}}
        current = {}
        def mutate(agent, name, entry, exists):
            self.assertFalse(exists)
            current[name] = entry
        with patch.object(mcp_setup, "client_config", return_value=current), patch.object(mcp_setup, "mutate", mutate):
            mcp_setup.reconcile("claude", {"example": wanted}, state, self.state, False)
        self.assertEqual(state["claude"]["example"], {"installed": mcp_setup.fingerprint(wanted)})

    def test_reconcile_scoped_add_repeat_remove(self):
        current = {"other": {"url": "https://unrelated.example/mcp"}}
        mutations = []
        def mutate(agent, name, wanted, exists):
            mutations.append(name)
            if wanted is None:
                del current[name]
            else:
                current[name] = wanted
        requested = {"docs": {"url": "https://docs.example/mcp"}}
        with patch.object(mcp_setup, "client_config", return_value=current), patch.object(mcp_setup, "mutate", mutate):
            for assignments in (requested, requested, {}):
                mcp_setup.reconcile("codex", assignments, mcp_setup.read_json(self.state), self.state, False)
        self.assertEqual(mutations, ["docs", "docs"])
        self.assertEqual(list(current), ["other"])

    def test_timeouts_preserve_other_client_settings(self):
        config = self.home/".codex/config.toml"
        config.parent.mkdir()
        config.write_text('# Keep this comment.\n[features]\nfoo = true\n[mcp_servers.example]\ncommand = "/bin/date"\n')
        mcp_setup.codex_timeouts("example", {"startup_timeout_sec": 60, "tool_timeout_sec": 120})
        self.assertIn("# Keep this comment.", config.read_text())
        self.assertTrue(mcp_setup.read_toml(config)["features"]["foo"])
        self.assertEqual(mcp_setup.client_config("codex")["example"]["tool_timeout_sec"], 120)
