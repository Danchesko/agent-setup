"""Install and inspect the owner's GitWatch and daily update LaunchAgents."""

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
from tempfile import NamedTemporaryFile
from urllib.error import URLError
from urllib.request import Request, urlopen


LABEL = "local.agent-setup"
DOMAIN = f"gui/{os.getuid()}"
AGENTS = Path.home() / "Library/LaunchAgents"
LOGS = Path.home() / "Library/Logs/agent-setup"
ROLES = ("public", "private", "update")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", repo, *args], text=True).strip()


def github_origin(repo):
    if Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo:
        raise ValueError(f"Expected a repository root: {repo}")
    if git(repo, "branch", "--show-current") != "main":
        raise ValueError(f"Switch {repo.name} to main before enabling GitWatch.")
    names = []
    for flags in ([], ["--push"]):
        urls = git(repo, "remote", "get-url", *flags, "--all", "origin").splitlines()
        if len(urls) != 1:
            raise ValueError(f"Expected a single origin in {repo.name}.")
        match = re.fullmatch(
            r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)"
            r"([\w.-]+/[\w.-]+?)(?:\.git)?/?", urls[0], re.ASCII | re.IGNORECASE,
        )
        if not match:
            raise ValueError(f"Expected a GitHub origin URL without credentials in {repo.name}.")
        names.append(match[1].lower())
    if names[0] != names[1]:
        raise ValueError(f"Fetch and push target different repositories in {repo.name}.")
    return names[0]


def check_access(repo, private):
    name = github_origin(repo)
    gh = shutil.which("gh")
    metadata = None
    if gh:
        result = subprocess.run(
            [gh, "api", "--hostname", "github.com", f"repos/{name}"],
            text=True, capture_output=True,
        )
        if result.returncode == 0:
            metadata = json.loads(result.stdout)
    if metadata is None:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        result = subprocess.run(
            ["git", "-C", repo, "-c", "credential.interactive=false", "credential", "fill"],
            input=f"protocol=https\nhost=github.com\npath={name}.git\n\n",
            capture_output=True, text=True, env=env,
        )
        cred = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode or not cred.get("password"):
            raise ValueError("Sign in to GitHub using a Git credential helper or gh, then retry.")
        request = Request(f"https://api.github.com/repos/{name}", headers={
            "Authorization": "Bearer " + cred["password"],
            "Accept": "application/vnd.github+json",
        })
        with urlopen(request, timeout=15) as response:
            metadata = json.load(response)
    if metadata["full_name"].lower() != name or metadata["private"] != private:
        raise ValueError(f"Check origin and visibility before enabling GitWatch for {repo.name}.")
    if not metadata.get("permissions", {}).get("push"):
        raise ValueError(f"Write access to {name} is required for automatic pushes.")
    return metadata


def ensure_commit_identity(repo, owner):
    login = owner["login"]
    defaults = {"user.name": login, "user.email": f"{int(owner['id'])}+{login}@users.noreply.github.com"}
    for key, default in defaults.items():
        current = subprocess.run(["git", "-C", repo, "config", "--get", key], capture_output=True, text=True)
        if current.returncode > 1:
            raise ValueError(f"Cannot read {key} for {repo.name}.")
        if not current.stdout.strip():
            git(repo, "config", "--local", key, default)


def brew_gitwatch():
    brew = shutil.which("brew")
    if not brew:
        raise ValueError("Install Homebrew to enable GitWatch on this Mac.")
    prefix = Path(subprocess.check_output([brew, "--prefix"], text=True).strip()) / "bin"
    if not all((prefix / cmd).exists() for cmd in ("gitwatch", "fswatch", "greadlink")):
        subprocess.run([brew, "install", "gitwatch"], check=True)
    return prefix


def service_config(role, repo, brew_bin):
    label = f"{LABEL}.{role}"
    config = {
        "Label": label,
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {
            "PATH": f"{Path.home()}/.local/bin:{brew_bin}:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "GIT_TERMINAL_PROMPT": "0",
        },
        "StandardOutPath": str(LOGS / f"{role}.log"),
        "StandardErrorPath": str(LOGS / f"{role}.log"),
    }
    if role == "update":
        config["ProgramArguments"] = [str(repo / "setup"), "update"]
        config["StartCalendarInterval"] = {"Hour": 9, "Minute": 15}
    else:
        config["ProgramArguments"] = [
            str(brew_bin / "gitwatch"), "-M", "-f", "-s", "5", "-r", "origin",
            "-m", "Sync profile edits (%d)", str(repo),
        ]
        config["EnvironmentVariables"].update({
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "push.default", "GIT_CONFIG_VALUE_0": "simple",
        })
        config["RunAtLoad"] = True
        config["KeepAlive"] = True
        config["ThrottleInterval"] = 15
    return config


def job_state(role):
    return subprocess.run(
        ["launchctl", "print", f"{DOMAIN}/{LABEL}.{role}"], capture_output=True, text=True,
    )


def stop(role):
    if job_state(role).returncode == 0:
        subprocess.run(["launchctl", "bootout", f"{DOMAIN}/{LABEL}.{role}"], check=True)


def install(role, config):
    path = AGENTS / f"{LABEL}.{role}.plist"
    encoded = plistlib.dumps(config)
    matches = path.exists() and path.read_bytes() == encoded
    live = job_state(role)
    if matches and live.returncode == 0:
        return
    stop(role)
    if not matches:
        with NamedTemporaryFile(dir=AGENTS, delete=False) as tmp:
            tmp.write(encoded)
        os.replace(tmp.name, path)
    subprocess.run(["launchctl", "enable", f"{DOMAIN}/{LABEL}.{role}"], check=True)
    subprocess.run(["launchctl", "bootstrap", DOMAIN, str(path)], check=True)


def sync_status(repo):
    head = git(repo, "rev-parse", "HEAD")
    if git(repo, "branch", "--show-current") != "main":
        return "owner checkout is not on main"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        remote = subprocess.run(
            ["git", "-C", repo, "ls-remote", "--exit-code", "origin", "refs/heads/main"],
            capture_output=True, text=True, timeout=15, env=env,
        )
    except subprocess.TimeoutExpired:
        return "origin/main check timed out"
    if remote.returncode or not remote.stdout.strip():
        return "cannot read origin/main"
    if head != remote.stdout.split()[0]:
        return "local main and origin/main differ"
    if git(repo, "status", "--porcelain"):
        return "local edits pending"
    return "in sync"


def status(public, private):
    healthy = True
    for role, repo in zip(ROLES, (public, private, public)):
        job = job_state(role)
        if job.returncode != 0:
            print(f"{role}: not loaded")
            healthy = False
            continue
        state = re.search(r"^\s*state = (.+)$", job.stdout, re.MULTILINE)
        value = state[1] if state else "unknown"
        last_exit = re.search(r"^\s*last exit code = (\d+)", job.stdout, re.MULTILINE)
        if last_exit and last_exit[1] != "0":
            value += f" (last exit {last_exit[1]})"
        if role != "update":
            sync = sync_status(repo)
            healthy = healthy and sync == "in sync"
            value += f", {sync}"
        print(f"{role}: {value} | {LOGS / (role + '.log')}")
        if role != "update" and (not state or state[1] != "running"):
            healthy = False
        if role == "update" and last_exit and last_exit[1] != "0":
            healthy = False
    return healthy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path)
    parser.add_argument("private", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--status", action="store_true")
    mode.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise ValueError("LaunchAgents require macOS.")
    if args.status:
        return 0 if status(args.public, args.private) else 1
    if args.stop:
        for role in ROLES:
            stop(role)
            (AGENTS / f"{LABEL}.{role}.plist").unlink(missing_ok=True)
        return 0
    public, private = args.public.resolve(), args.private.resolve()
    if public == private or public in private.parents or private in public.parents:
        raise ValueError("The private and public Git trees must be separate.")
    if not os.access(public / "setup", os.X_OK):
        raise ValueError(f"Missing executable: {public / 'setup'}")
    pub_meta = check_access(public, False)
    priv_meta = check_access(private, True)
    if pub_meta["owner"]["id"] != priv_meta["owner"]["id"]:
        raise ValueError("The public and private origins must belong to the same owner.")
    ensure_commit_identity(public, pub_meta["owner"])
    ensure_commit_identity(private, priv_meta["owner"])
    prefix = brew_gitwatch()
    AGENTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, mode=0o700, exist_ok=True)
    for role, repo in zip(ROLES, (public, private, public)):
        install(role, service_config(role, repo, prefix))
    print(f"Loaded GitWatch for {pub_meta['full_name']} and {priv_meta['full_name']}. Daily update at 09:15 local time.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, URLError, subprocess.CalledProcessError) as exc:
        sys.exit(str(exc))
