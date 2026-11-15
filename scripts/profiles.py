"""Apply skills and global instructions selected in one or more profiles."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import tomllib


BEGIN = "<!-- agent-setup:begin -->"
END = "<!-- agent-setup:end -->"
AGENTS = ("codex", "claude")


def selected_agents(agents):
    if not isinstance(agents, list) or any(agent not in AGENTS for agent in agents):
        raise ValueError(f"Expected a list of agent names from {AGENTS}, got {agents!r}")
    return agents


def read_profiles(roots, skill_dirs):
    links = {}
    rules = {agent: [] for agent in AGENTS}
    seen = set()
    for root in roots:
        with (root / "profile.toml").open("rb") as stream:
            profile = tomllib.load(stream)
        for name, assigned in profile.get("skills", {}).items():
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", name):
                raise ValueError(f"Invalid skill name: {name!r}")
            if name.casefold() in seen:
                raise ValueError(f"Duplicate skill name across profiles: {name}")
            seen.add(name.casefold())
            source = root / "skills" / name
            if not source.resolve().is_relative_to(root) or not (source / "SKILL.md").is_file():
                raise ValueError(f"Missing skill or source outside its repository: {source}")
            for agent in selected_agents(assigned):
                links[skill_dirs[agent] / name] = source
        for filename, assigned in profile.get("rules", {}).items():
            path = root / filename
            if Path(filename).is_absolute() or not path.resolve().is_relative_to(root):
                raise ValueError(f"Rule outside profile: {filename}")
            text = path.read_text().strip()
            if BEGIN in text or END in text:
                raise ValueError(f"Reserved setup marker inside {path}")
            for agent in selected_agents(assigned):
                rules[agent].append(text)
    return links, rules


def atomic_write(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        tmp = Path(out.name)
        try:
            out.write(content.encode())
            out.flush()
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def rule_content(path, fragments, public, adopt):
    original = path.read_text() if path.exists() else ""
    if path.is_symlink() and (not adopt or not path.is_file()):
        raise ValueError(f"Global instructions are a symlink: {path}. Inspect it before using --adopt.")
    if original.count(BEGIN) != original.count(END) or original.count(BEGIN) > 1:
        raise ValueError(f"Damaged agent-setup section in {path}")
    route = f"When asked to add, change, or remove an installed agent skill, read `{public / 'AGENTS.md'}` and follow its skill management instructions."
    block = "\n\n".join([BEGIN, route, *filter(None, fragments), END])
    if BEGIN in original:
        first = original.index(BEGIN)
        last = original.index(END)
        if first > last:
            raise ValueError(f"Damaged agent-setup section in {path}")
        return original[:first] + block + original[last + len(END):]
    # During migration the same complete set of personal rules may already be installed.
    if adopt and original.strip() in fragments:
        original = ""
    return original + ("\n\n" if original else "") + block + "\n"


def readlink(path):
    return os.readlink(path) if path.is_symlink() else None


def apply_profiles(roots, state_dir, adopt):
    home = Path.home()
    codex = Path(os.environ.get("CODEX_HOME", home / ".codex"))
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude"))
    skill_dirs = {"codex": home / ".agents/skills", "claude": claude / "skills"}
    rule_paths = {"codex": codex / "AGENTS.md", "claude": claude / "CLAUDE.md"}
    override = codex / "AGENTS.override.md"
    if override.is_file() and override.read_text().strip():
        rule_paths["codex"] = override
    if not (roots[0] / "AGENTS.md").is_file():
        raise ValueError(f"Missing repository instructions: {roots[0] / 'AGENTS.md'}")
    if len({path.resolve() for path in skill_dirs.values()}) != len(skill_dirs):
        raise ValueError("Clients share a skill directory. Separate their skill directories to manage assignments.")
    links, rules = read_profiles(roots, skill_dirs)

    state_file = state_dir / "links.json"
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    changed = {}
    backups = set()
    stale = []
    for path, source in links.items():
        current = readlink(path)
        if current == str(source):
            continue
        owned = current is not None and current == previous.get(str(path))
        if os.path.lexists(path) and not owned:
            if not adopt:
                raise ValueError(f"Skill path already exists: {path}. Inspect it before using --adopt.")
            backups.add(path)
        changed[path] = source
    for target, old_source in previous.items():
        path = Path(target)
        if path.parent not in skill_dirs.values():
            raise ValueError(f"Unexpected skill path in {state_file}: {path}")
        if path not in links and readlink(path) == old_source:
            stale.append(path)

    rule_changes = {}
    for agent, path in rule_paths.items():
        content = rule_content(path, rules[agent], roots[0], adopt)
        if path.is_symlink() or not path.exists() or path.read_text() != content:
            rule_changes[path] = content
            if path.is_symlink() or path.exists() and BEGIN not in path.read_text():
                backups.add(path)

    if backups:
        batch = state_dir / "backups" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        batch.mkdir(parents=True, mode=0o700)
        for path in sorted(backups):
            # Generated backups are outside both source repositories.
            destination = batch / (str(path).lstrip("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            if path.is_symlink():
                destination.symlink_to(os.readlink(path))
                if path in rule_changes:
                    shutil.copy2(path, destination.with_name(destination.name + ".original"))
            elif path.is_dir():
                shutil.copytree(path, destination, symlinks=True)
            else:
                shutil.copy2(path, destination)
        print(f"Saved existing files in {batch}")

    for path, source in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        # Place the new link before moving a legacy directory out of the way.
        with tempfile.TemporaryDirectory(dir=path.parent) as directory:
            new = Path(directory) / "link"
            new.symlink_to(source)
            if path.is_dir() and not path.is_symlink():
                original = Path(directory) / "original"
                path.rename(original)
                try:
                    new.replace(path)
                except OSError:
                    original.rename(path)
                    raise
            else:
                new.replace(path)
    for path in stale:
        path.unlink(missing_ok=True)
    for path, content in rule_changes.items():
        mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0o600
        atomic_write(path, content, mode)
    updated = {str(path): str(source) for path, source in links.items()}
    if previous != updated:
        atomic_write(state_file, json.dumps(updated, indent=2, sort_keys=True) + "\n")
    print(f"Skills: {len(links)} assignments ({len(changed)} changed, {len(stale)} removed). Global instructions: {len(rule_changes)} updated.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path)
    parser.add_argument("private", type=Path, nargs="?")
    parser.add_argument("--adopt", action="store_true", help="Back up and replace conflicting local skill paths and global instruction links.")
    options = parser.parse_args()
    roots = [path.resolve() for path in (options.public, options.private) if path]
    state = Path.home() / "Library/Application Support/agent-setup/profiles"
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (state / "apply.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        apply_profiles(roots, state, options.adopt)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
