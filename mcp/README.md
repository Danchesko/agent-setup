# MCP connections

`./setup status` checks client registrations and reports missing Keychain items. `./setup check` connects to the selected servers. For a personal installation, run the check while connected to your work network. It lists the OpenAI documentation tools, runs a one-result Jira query, and checks the signed-in GitLab identity. It prints no credentials or returned records.

Server definitions live in [servers.toml](servers.toml). The private profile can supply a `mcp.toml` file with service URLs and Keychain item identifiers. Machine-specific values in `~/.config/agent-setup/mcp.toml` override these settings. For example:

```toml
[jira.settings]
JIRA_URL = "https://jira.example.org"

[jira.keychain.JIRA_PERSONAL_TOKEN]
service = "jira.example.org"
account = "agent-setup"

[gitlab.settings]
GITLAB_API_URL = "https://gitlab.example.org/api/v4"

[gitlab.keychain.GITLAB_PERSONAL_ACCESS_TOKEN]
service = "glab:gitlab.example.org:token"
```

## First sign-in

- **Jira:** in Terminal run `security add-generic-password -a ACCOUNT -s SERVICE -U -w`, substituting the account and service from the private profile. Keep `-w` last so macOS prompts for the token. The token value stays out of shell history.
- **GitLab:** sign in with `glab auth login --hostname HOST` using the macOS Keychain. The runtime reads the corresponding Keychain item directly.
- Run `./setup check` after sign-in. Already registered clients can restart the server to pick up a rotated credential.

The stdio servers use private run directories under `~/Library/Application Support/agent-setup/mcp`. Python and npm dependencies are installed from their lockfiles on first use of a version during setup. A repeated apply reuses the installed packages. The launch command does not contain credentials.
