# Git access

Git operations are available both as dedicated Git tools and through `run_shell_tool`. In practice, shell-driven Git workflows are often more flexible because they support normal Git commands, hooks, and repository-specific scripts.

Before committing or pushing, run tests and use `secret_scan` on changed files or the repository root. The Docker image can persist GitHub CLI, Git HTTPS credentials, SSH keys, `.netrc`, and GPG state through the configured credentials volume.
