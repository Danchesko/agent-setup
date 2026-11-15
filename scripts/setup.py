"""Install the local profiles or update their Git checkouts."""
import argparse
import contextlib
import fcntl
import plistlib
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

PUBLIC = Path(__file__).resolve().parents[1]
PRIVATE = PUBLIC.with_name("agent-skills-private")

def run(*args, cwd=None):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True)

def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *map(str, args)], text=True).strip()

def helper(name, *args):
    run(sys.executable, PUBLIC / "scripts" / (name + ".py"), *args)

def ensure_brew():
    if shutil.which("brew"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        installer = Path(tmp) / "install.sh"
        run("curl", "--proto", "=https", "-fsSL", "https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh", "-o", installer)
        run("/bin/bash", installer)
    if not shutil.which("brew"):
        raise SystemExit("Homebrew installation unfinished. Complete the installation and rerun setup.")

def dependencies(roots):
    targets = set()
    servers = set()
    for root in roots:
        with (root / "profile.toml").open("rb") as f:
            profile = tomllib.load(f)
        for section in ("rules", "skills", "mcp"):
            for clients in profile.get(section, {}).values():
                targets.update(clients)
        servers.update(name for name, clients in profile.get("mcp", {}).items() if clients)
    for client, cask in [("codex", "codex"), ("claude", "claude-code")]:
        if client in targets and not shutil.which(client):
            ensure_brew()
            run("brew", "install", "--cask", cask)
    if "gitlab" in servers and not shutil.which("glab"):
        ensure_brew()
        run("brew", "install", "glab")
    legacy = Path.home() / ".agents/mcp/runtime"
    if "gitlab" in servers and not shutil.which("npm") and not any(legacy.glob("*/bin/npm")):
        ensure_brew()
        run("brew", "install", "node")

def get_private():
    if (PRIVATE / "profile.toml").is_file():
        return
    url = git(PUBLIC, "remote", "get-url", "origin")
    pattern = r"(https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+)/[\w.-]+"
    match = re.fullmatch(pattern, url)
    if not match:
        raise SystemExit("Clone the public GitHub repository first or place agent-skills-private beside it.")
    remote = f"{match[1]}{match[2]}/agent-skills-private.git"
    print(f"Cloning {match[2]}/agent-skills-private. Git access to this repository is required.", flush=True)
    run("git", "clone", "--recurse-submodules", remote, PRIVATE)

def apply(roots, adopt):
    dependencies(roots)
    for root in roots:
        if (root / ".gitmodules").exists():
            run("git", "submodule", "update", "--init", "--recursive", cwd=root)
    flags = ["--adopt"] if adopt else []
    helper("profiles", *roots, *flags)
    helper("mcp_setup", *roots, *flags)

def update(roots):
    for root in roots:
        if git(root, "status", "--porcelain"):
            raise SystemExit(f"Uncommitted changes in {root}. Finish or sync the edits and retry update.")
        branch = git(root, "branch", "--show-current")
        if not branch:
            raise SystemExit(f"Select a tracking branch in {root} before updating.")
    for root in roots:
        run("git", "pull", "--ff-only", cwd=root)
    # Load freshly fetched profile and MCP helpers before advancing owner pins.
    apply(roots, False)
    if len(roots) == 1:
        return
    for root in roots:
        modules = root / ".gitmodules"
        if not modules.exists():
            continue
        keys = git(root, "config", "--file", modules, "--name-only", "--get-regexp", r"^submodule\..*\.path$").splitlines()
        for key in keys:
            sub = root / git(root, "config", "--file", modules, "--get", key)
            setting = subprocess.run(
                ["git", "-C", root, "config", "--file", modules, "--get", key.removesuffix(".path") + ".branch"],
                capture_output=True, text=True,
            )
            if setting.returncode not in (0, 1):
                raise SystemExit(f"Cannot read submodule branch for {sub}.")
            branch = setting.stdout.strip() or "HEAD"
            if branch == ".":
                branch = git(root, "branch", "--show-current")
            if git(sub, "status", "--porcelain"):
                raise SystemExit(f"Local edits in {sub}; finish them before updating.")
            run("git", "fetch", "--quiet", "origin", branch, cwd=sub)
            run("git", "merge-base", "--is-ancestor", "HEAD", "FETCH_HEAD", cwd=sub)
            previous = git(sub, "rev-parse", "HEAD")
            run("git", "checkout", "--detach", "--quiet", "FETCH_HEAD", cwd=sub)
            run("git", "submodule", "update", "--init", "--recursive", cwd=sub)
            if git(sub, "rev-parse", "HEAD") != previous:
                run("git", "add", "--", sub.relative_to(root), cwd=root)
    # GitWatch can now commit the pin; another apply cannot reset it. Reconcile links without resetting it.
    helper("profiles", *roots)
    helper("mcp_setup", *roots)
    for root, role in zip(roots, ("public", "private")):
        plist = Path.home() / f"Library/LaunchAgents/local.agent-setup.{role}.plist"
        if not plist.exists() or plistlib.loads(plist.read_bytes()).get("WorkingDirectory") != str(root):
            continue
        if git(root, "branch", "--show-current") == "main" and git(root, "rev-list", "--count", "@{u}..HEAD") != "0":
            run("git", "push", "origin", "main", cwd=root)

@contextlib.contextmanager
def setup_lock():
    folder = Path.home() / "Library/Application Support/agent-setup"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "setup.lock").open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", nargs="?", default="apply", choices=["apply","personal","update","watch","unwatch","status","check"])
    p.add_argument("--adopt", action="store_true", help="Back up existing local configuration and migrate it into this installation")
    p.add_argument("--no-watch", action="store_true", help="Set up a personal Mac without automatic commits, pushes, or daily updates")
    args = p.parse_args()
    if args.no_watch and args.action != "personal":
        p.error("--no-watch is available for personal installs")
    if args.adopt and args.action not in ("apply", "personal"):
        p.error("--adopt is available for apply and personal")
    with setup_lock():
        if args.action == "personal":
            get_private()
        roots = [PUBLIC]
        if (PRIVATE / "profile.toml").is_file():
            roots.append(PRIVATE)
        if args.action in ("apply", "personal"):
            apply(roots, args.adopt)
        if args.action in ("personal", "watch") and not args.no_watch:
            if len(roots) != 2:
                raise SystemExit("Run ./setup personal to connect your private profile before starting GitWatch.")
            ensure_brew()
            helper("watch", *roots)
        if args.action == "unwatch":
            helper("watch", PUBLIC, PRIVATE, "--stop")
        if args.action == "update":
            update(roots)
        if args.action in ("status","check"):
            helper("mcp_setup", *roots, "--" + args.action)
            if len(roots) == 2 and args.action == "status":
                helper("watch", *roots, "--status")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from None
