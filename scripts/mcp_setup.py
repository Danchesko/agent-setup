"""Apply the MCP assignments in one or two checkout profiles on macOS."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

from mcp_runtime import keychain_command


def read_toml(path):
    return tomllib.loads(path.read_text()) if path.exists() else {}


def read_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def write_json(path, value):
    data = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text() == data:
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as out:
        out.write(data)
    os.replace(out.name, path)


def load(public, private):
    catalog = read_toml(public / "mcp/servers.toml")
    assignments = {}
    for checkout in [public, private]:
        if checkout:
            assignments.update(read_toml(checkout / "profile.toml").get("mcp", {}))
    settings = read_toml(private / "mcp.toml") if private else {}
    local = read_toml(Path.home() / ".config/agent-setup/mcp.toml")
    for name, data in local.items():
        for section, values in data.items():
            settings.setdefault(name, {}).setdefault(section, {}).update(values)
    for name, agents in assignments.items():
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", name) or name not in catalog:
            raise ValueError(f"Undefined MCP server: {name}")
        if not isinstance(agents, list) or any(a not in ("codex", "claude") for a in agents):
            raise ValueError(f"Invalid agents for MCP server {name}")
    return catalog, assignments, settings


def executable(name):
    found = shutil.which(name)
    if found:
        return Path(found).absolute()
    paths = [Path.home()/".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    if name in ("node", "npm"):
        paths.extend(sorted((Path.home()/".agents/mcp/runtime").glob("node-*/bin"), reverse=True))
    for directory in paths:
        if os.access(directory/name, os.X_OK):
            return directory/name
    raise ValueError(f"Missing executable: {name}")


def settings_for(name, spec, machine):
    values = machine.get("settings", {})
    refs = machine.get("keychain", {})
    required = spec.get("local_settings", [])
    keys = spec.get("keychain_env", [])
    missing = [k for k in required if not values.get(k)]
    missing += [k for k in keys if not refs.get(k, {}).get("service")]
    if missing:
        raise ValueError(f"{name}: set {', '.join(missing)} in private mcp.toml or ~/.config/agent-setup/mcp.toml")
    return ({k: values[k] for k in required}, {k: refs[k] for k in keys})


def package_command(name, spec, storage, packages):
    runtime, package = spec["runtime"], spec["package"]
    manager = runtime["manager"]
    source = packages / name
    tool = runtime["executable"]
    if manager == "uv":
        manifest, lock = source/"pyproject.toml", source/"uv.lock"
        if package not in read_toml(manifest)["project"]["dependencies"]:
            raise ValueError(f"{name}: dependency differs from its locked manifest")
    elif manager == "npm":
        manifest, lock = source/"package.json", source/"package-lock.json"
        npm_name, version = package.rsplit("@", 1)
        if read_json(manifest)["dependencies"].get(npm_name) != version:
            raise ValueError(f"{name}: dependency differs from its locked manifest")
    else:
        raise ValueError(f"{name}: unsupported package manager")
    version_key = hashlib.sha256(manifest.read_bytes() + lock.read_bytes()).hexdigest()[:16]
    root = storage / "packages" / name / version_key
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    ready = root / ".installed"
    if manager == "uv":
        binary = root / "venv/bin" / tool
        if not ready.exists() or not binary.is_file():
            env = dict(os.environ, UV_PROJECT_ENVIRONMENT=str(root/"venv"))
            subprocess.run([executable("uv"), "sync", "--project", source, "--frozen", "--no-dev",
                            "--python", runtime["python"]], env=env, check=True)
        command = [str(binary)]
    else:
        node = executable("node")
        binary = root / "node_modules/.bin" / tool
        if not ready.exists() or not binary.is_file():
            for file in (manifest, lock):
                shutil.copyfile(file, root/file.name)
            env = dict(os.environ, PATH=str(node.parent) + os.pathsep + os.environ.get("PATH", ""))
            subprocess.run([executable("npm"), "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
                           cwd=root.resolve(), env=env, check=True)
        command = [str(node), str(binary)]
    if not binary.is_file():
        raise ValueError(f"{name}: package did not provide {tool}")
    if not ready.exists():
        ready.touch()
    return [*command, *spec.get("args", [])]


def client_config(agent):
    if agent == "codex":
        home = Path(os.environ.get("CODEX_HOME") or Path.home()/".codex")
        return read_toml(home/"config.toml").get("mcp_servers", {})
    directory = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home())
    return read_json(directory/".claude.json").get("mcpServers", {})


def fingerprint(obj):
    if isinstance(obj, dict):
        # Codex rewrites numeric timeouts as floats when another server changes.
        obj = obj.copy()
        for key in ("startup_timeout_sec", "tool_timeout_sec"):
            value = obj.get(key)
            if isinstance(value, float) and value.is_integer():
                obj[key] = int(value)
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def matches(actual, wanted):
    if actual is None or wanted is None:
        return actual == wanted
    return all(actual.get(k) == v for k, v in wanted.items())


def completed_native_step(agent, actual, pending):
    if matches(actual, pending):
        return True
    if agent == "codex" and isinstance(pending, dict):
        # Native add may have completed just before the timeout edit.
        native = {k: v for k, v in pending.items() if k not in ("startup_timeout_sec", "tool_timeout_sec")}
        return actual == native
    return False


def legacy(name, spec):
    root = Path.home()/".agents/mcp"
    allowed = {"command", "args", "cwd", "startup_timeout_sec", "tool_timeout_sec", "enabled", "type"}
    return (spec is not None and set(spec) <= allowed and
            spec.get("command") == str(root/".venv/bin/python") and
            spec.get("args") == [str(root/"launch.py"), name])


def codex_timeouts(name, options):
    # Native mcp add writes an ordinary TOML table but has no timeout flags.
    # Insert only the two known keys, and verify the entire parsed document.
    home = Path(os.environ.get("CODEX_HOME") or Path.home()/".codex")
    path = (home/"config.toml").resolve()
    original = path.read_text()
    before = tomllib.loads(original)
    before["mcp_servers"][name].update(options)
    header = f"[mcp_servers.{name}]"
    rows = original.splitlines(keepends=True)
    index = next((i for i, line in enumerate(rows) if line.strip() == header), None)
    if index is None:
        raise ValueError(f"{name}: expected a native Codex MCP table")
    rows[index+1:index+1] = [f"{key} = {int(val)}\n" for key, val in options.items()]
    updated = "".join(rows)
    if tomllib.loads(updated) != before:
        raise ValueError(f"{name}: unexpected Codex configuration change")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        file.write(updated)
    replacement = Path(file.name)
    try:
        if path.read_text() != original:
            raise ValueError("Codex config changed concurrently. Run apply again.")
        replacement.chmod(path.stat().st_mode & 0o777)
        replacement.replace(path)
    finally:
        replacement.unlink(missing_ok=True)


def mutate(agent, name, wanted, exists):
    cli = str(executable(agent))
    if exists and (agent == "claude" or wanted is None):
        command = [cli, "mcp", "remove"]
        if agent == "claude":
            command += ["--scope", "user"]
        subprocess.run(command + [name], check=True, stdout=subprocess.DEVNULL)
    if wanted is None:
        return
    if agent == "claude":
        command = [cli, "mcp", "add-json", "--scope", "user", name, json.dumps(wanted)]
    else:
        command = [cli, "mcp", "add", name]
        if "url" in wanted:
            command += ["--url", wanted["url"]]
        else:
            command += ["--", wanted["command"], *wanted["args"]]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    if agent == "codex":
        options = {k: wanted[k] for k in ("startup_timeout_sec", "tool_timeout_sec") if k in wanted}
        if options:
            codex_timeouts(name, options)


def reconcile(agent, desired, state, state_file, adopt):
    owned = state.setdefault(agent, {})
    current = client_config(agent)
    for name in sorted(set(owned) | set(desired)):
        actual, wanted = current.get(name), desired.get(name)
        previous = owned.get(name, {})
        # Only adopt an identical unmanaged definition, or an explicitly
        # requested migration from the old shared launcher.
        if actual is not None and fingerprint(actual) != previous.get("installed"):
            if "pending" in previous and completed_native_step(agent, actual, previous["pending"]):
                pass
            elif actual == wanted:
                pass
            elif not (adopt and legacy(name, actual)):
                raise ValueError(f"{agent}/{name}: existing registration changed or belongs to another installer")
        if not matches(actual, wanted):
            if actual and not previous and adopt:
                write_json(state_file.parent/"backups"/f"{agent}-{name}-{fingerprint(actual)[:12]}.json", actual)
            owned[name] = {**previous, "installed": fingerprint(actual), "pending": wanted}
            write_json(state_file, state)
            mutate(agent, name, wanted, actual is not None)
            actual = client_config(agent).get(name)
            if not matches(actual, wanted):
                raise ValueError(f"{agent}/{name}: native CLI did not save the requested registration")
        if wanted is None:
            owned.pop(name, None)
        else:
            owned[name] = {"installed": fingerprint(actual)}
        write_json(state_file, state)


def keychain_present(item):
    return subprocess.run(keychain_command(item), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def local_root():
    return Path.home()/"Library/Application Support/agent-setup/mcp"


def server_entry(agent, spec, command):
    if spec["transport"] == "http":
        entry = {"url": spec["url"]}
    else:
        entry = {"command": command[0], "args": command[1:]}
    if agent == "claude":
        entry["type"] = spec["transport"]
    elif spec["transport"] == "stdio":
        entry.update(spec.get("codex_timeouts", {}))
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path)
    parser.add_argument("private", type=Path, nargs="?")
    parser.add_argument("--adopt", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--enroll", metavar="SERVER")
    args = parser.parse_args()
    public = args.public.resolve()
    catalog, assignments, settings = load(public, args.private)
    storage = local_root()
    if args.enroll:
        name = args.enroll
        _, refs = settings_for(name, catalog[name], settings.get(name, {}))
        if not refs:
            raise ValueError(f"{name} does not use Keychain")
        for item in refs.values():
            if item["service"].startswith("glab:"):
                host = item["service"].split(":")[1]
                raise ValueError(f"Use glab auth login --hostname {host} with the macOS Keychain")
            command = keychain_command(item)
            command[1] = "add-generic-password"
            subprocess.run(command + ["-U", "-w"], check=True)
        return
    desired = {"codex": {}, "claude": {}}
    storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    state_file = storage/"registrations.json"
    with (storage/"apply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = read_json(state_file)
        for name, agents in assignments.items():
            if not agents:
                continue
            spec = catalog[name]
            command = []
            if spec["transport"] == "stdio":
                path = storage/f"{name}.json"
                command = [sys.executable, str(public/"scripts/mcp_runtime.py"), str(path)]
                values, refs = settings_for(name, spec, settings.get(name, {}))
                runtime = spec["runtime"]
                if not args.status and not args.check:
                    write_json(path, {"command": package_command(name, spec, storage, public/"mcp/packages"), "keychain": refs,
                                      "clear_prefixes": runtime.get("clear_prefixes", []),
                                      "env": {**runtime.get("env", {}), **values}})
                missing = [k for k, item in refs.items() if not keychain_present(item)]
                if missing:
                    print(f"{name}: sign-in needed for {', '.join(missing)}")
                    if args.check:
                        raise ValueError(f"{name}: credential missing")
            for agent in agents:
                entry = server_entry(agent, spec, command)
                desired[agent][name] = entry
                if args.status or args.check:
                    if not matches(client_config(agent).get(name), entry):
                        raise ValueError(f"{agent}/{name}: registration missing or out of date")
                    print(f"{agent}/{name}: registered")
            if args.check:
                from mcp_probe import check_http, check_stdio
                if command:
                    check_stdio(name, command, spec["runtime"].get("probe"))
                else:
                    check_http(name, spec["url"])
        if args.status or args.check:
            return
        for agent in desired:
            reconcile(agent, desired[agent], state, state_file, args.adopt)
        print("MCP registrations applied.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError, KeyError) as error:
        raise SystemExit(str(error)) from None
