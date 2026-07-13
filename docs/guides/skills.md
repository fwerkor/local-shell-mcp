# Agent Skills

`local-shell-mcp` supports reusable Markdown-based Agent Skills through a fixed MCP tool surface. Installing or removing a Skill never adds or removes MCP tools, so clients do not need to refresh `tools/list` or reconnect.

## Directory layout

Skills are read from:

```text
<state_dir>/agent_config/skills/
  debugging/
    SKILL.md
    checklist.md
  pdfs/
    SKILL.md
    scripts/
      render.py
```

With the default workspace, this is:

```text
/workspace/.local-shell-mcp/agent_config/skills
```

Each immediate child directory is one Skill. Its directory name is the Skill name, and it must contain a regular `SKILL.md` file. A `config.json` file is not required for Skills.

## Fixed tools

| Tool | Purpose |
|---|---|
| `skills_list` | Rescan the directory and list installed Skill names, descriptions, entry paths, related files, and non-fatal warnings. It does not load instructions. |
| `skill_load` | Load the complete `SKILL.md` instructions for one exact name returned by `skills_list`. Related files are returned as paths and can be read separately when needed. |

Recommended flow:

```text
skills_list
  -> choose the relevant Skill
  -> skill_load(name)
  -> follow its instructions with the existing shell, file, Git, browser, or remote tools
```

Both tools are read-only. Changes on disk are visible on the next call because the directory is rescanned each time.

## Installing and updating Skills

The runtime deliberately does not include a Skill marketplace or package manager. Manage the directory with ordinary file or Git operations, for example:

```bash
cp -R ./my-skill /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

or:

```bash
git clone https://example.com/team/skills.git /tmp/team-skills
cp -R /tmp/team-skills/debugging /workspace/.local-shell-mcp/agent_config/skills/debugging
```

Updates and removals use the same normal file or Git workflow. The next `skills_list` or `skill_load` call sees the new contents without changing the MCP tool list.

## Validation and safety

The scanner:

- rejects Skill directories and `SKILL.md` entries that escape the configured directory;
- rejects symlinked Skill directories, entry files, and related files;
- skips directories without `SKILL.md` and reports a warning;
- extracts a compact description from front matter or the first prose paragraph;
- returns related file paths without loading all related content into model context.

Treat Skills as instructions and code from their publisher. Review `SKILL.md` and any scripts before placing them in the server-side directory.

## REST compatibility

The optional REST surface exposes the same registry through:

```text
GET  /tools/skills_list
POST /tools/skill_load   {"name": "debugging"}
```
