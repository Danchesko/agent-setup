"""Run a registered stdio server with credentials scoped to its child process."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys


def keychain_command(item):
    command = ["/usr/bin/security", "find-generic-password", "-s", item["service"]]
    if "account" in item:
        command.extend(["-a", item["account"]])
    return command


def credential(item):
    result = subprocess.run(keychain_command(item) + ["-w"], capture_output=True, timeout=30)
    if result.returncode:
        raise SystemExit("Credential unavailable. Unlock Keychain or complete the service login.")
    value = result.stdout.rstrip(b"\r\n")
    # glab stores its tokens with go-keyring's binary-safe encoding.
    if value.startswith(b"go-keyring-base64:"):
        value = base64.b64decode(value.split(b":", 1)[1], validate=True)
    if not value or any(c in value for c in (b"\n", b"\r", b"\0")):
        raise SystemExit("Invalid Keychain credential.")
    return value.decode("utf-8")


def main(settings_path):
    config = json.loads(settings_path.read_text())
    env = os.environ.copy()
    for key in list(env):
        if key == "DEBUG" or key.startswith(tuple(config["clear_prefixes"])):
            del env[key]
    env.update(config["env"])
    for name, item in config["keychain"].items():
        env[name] = credential(item)
    os.chdir(settings_path.parent)
    os.execve(config["command"][0], config["command"], env)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
