# Working on agent-setup

## Skills

Resolve changes in the installed checkouts beside this file. For a new personal or work skill, use the sibling `agent-skills-private` checkout unless the user explicitly wants to publish it. Use the agents named in the request. If visibility or assignments are unclear for a third-party source, clarify before changing the profile.

Place each public skill maintained here in `skills/<name>/` with a `SKILL.md` entry point. Register the skill and its target agents in `profile.toml`.

For an upstream skill, declare its repository in `.gitmodules` under `skills/.vendor/` and link the selected skill directory into `skills/`. Multiple skills from the same repository share one submodule.

After adding or changing a skill, update its target agents in the owning profile, run `./setup apply` from the setup checkout, and verify the resulting links. In a private profile, use the same `skills/<name>/SKILL.md` layout and edit its own `profile.toml`. Keep private names, rules, and attachments in that checkout. To uninstall a skill from one client, remove that agent from the assignment and apply again.

## MCP

Define server packages, commands, and public endpoints in `mcp/servers.toml`. Use local settings for service-specific URLs and macOS Keychain for tokens.

## Verification

When changing a skill or server assignment, check the affected clients and verify that unrelated settings are preserved. Verify public installation with only this repository available.
