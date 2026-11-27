# agent-setup

Set up skills, global instructions, and MCP servers for Codex and Claude Code on macOS. Both agents read each selected skill from the same checkout. A private sibling repository can add work skills, personal preferences, and service settings.

## Install on a Mac

Give an agent this repository URL and ask it to install the public profile. For the owner's environment, ask it to include the private profile. The public installation works on its own.

```sh
git clone --recurse-submodules https://github.com/Danchesko/agent-setup.git ~/agents/agent-setup
cd ~/agents/agent-setup
./setup
```

For the owner's setup, use `./setup personal` in place of `./setup`. It clones `agent-skills-private` from the same GitHub owner, applies both profiles, and starts GitWatch. Authorize Git access to the private repository and sign in to selected services. Use `./setup personal --no-watch` on a Mac where you want to manage commits and updates manually.

The bootstrap uses Git and macOS command line tools, installs uv and Python 3.12 if needed, and installs missing client CLIs with Homebrew. A personal installation also uses Homebrew for GitWatch. On an existing machine, setup reports a conflict before replacing an unmanaged skill. After reviewing the paths, `./setup apply --adopt` backs up and migrates those entries. Backups and runtime state live in `~/Library/Application Support/agent-setup/`.

## Use it

| Task | Command or file |
| --- | --- |
| Add or remove a skill | Ask either agent in any project. Setup installs a pointer to the [skill management instructions](AGENTS.md). |
| Change which agents see a skill | Edit the owning checkout's [profile.toml](profile.toml), then run `./setup apply`. Edits to an existing linked skill take effect from its source. |
| Edit personal global rules | Edit the fragments selected by the private profile and run `./setup apply`. |
| Update the environment | Run `./setup update`. It fast-forwards the checkouts and initializes their pinned submodules. Personal installations also advance selected upstream branches. Resolve local edits or divergent history before retrying. |
| Check client registrations and sync | Run `./setup status`. Run `./setup check` to test the selected MCP connections. |
| Enable or stop automatic sync | Run `./setup watch` or `./setup unwatch` in the owner's checkout. |

GitWatch monitors each owner's repository separately. It commits and pushes edits to that checkout's origin. A user LaunchAgent runs the update command at 09:15 local time. Logs are in `~/Library/Logs/agent-setup/`. Public installs do not enable automatic pushes.

## Files and client settings

| Source | Purpose |
| --- | --- |
| [profile.toml](profile.toml) | Map skills and servers to `codex`, `claude`, or both. The private checkout can supply an additional profile. |
| [skills/](skills/) | Local skill directories and relative links to selected upstream skills. |
| [.gitmodules](.gitmodules) | Upstream repositories and branches. Git records the installed commits. |
| [mcp/servers.toml](mcp/servers.toml) | Server definitions. OpenAI Docs is enabled for Codex. Jira and GitLab can be selected by a private profile. |
| [AGENTS.md](AGENTS.md) and [CLAUDE.md](CLAUDE.md) | Instructions for maintaining this repository. Claude imports the shared instructions. |

The installer links selected skills into `~/.agents/skills/` for Codex and `~/.claude/skills/` for Claude. It manages a marked section of each client's global instructions and registers selected MCPs at user scope. To disconnect a managed skill or server, remove the assignment from its profile and apply again.

Private service URLs and Keychain item identifiers can be supplied in the owner's `mcp.toml` or overridden for a Mac in `~/.config/agent-setup/mcp.toml`. Tokens are read from macOS Keychain when the MCP starts. Private work services may require VPN access. See [MCP connections](mcp/README.md) for first sign-in and read-only connection checks.

## Included skills

| Skill | Purpose |
| --- | --- |
| [clarify](skills/clarify/SKILL.md) | Clarify a request before acting on it. |
| [guided-coding](skills/guided-coding/SKILL.md) | Apply implementation and verification preferences. |
| [handoff](skills/handoff/SKILL.md) | Save a handoff for the next agent in `~/agents/handoffs/`. This version customizes the output path. [Upstream license](skills/handoff/LICENSE) |
| [exa-search](skills/exa-search/SKILL.md) | Search via the Exa API using a local Keychain item. |

[grill-me](skills/grill-me), [grilling](skills/grilling), and [wait-what](skills/wait-what) use the [mattpocock/skills](https://github.com/mattpocock/skills) submodule. Upstream skills retain their original licenses.

## Verification

From this checkout, run `uv run --python 3.12 python -m unittest discover -s tests`. The tests use temporary homes and repositories.
