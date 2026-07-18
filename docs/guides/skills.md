# Agent Skills

`local-shell-mcp` supports reusable Markdown-based Agent Skills through a fixed MCP tool surface. Installing or removing a Skill never changes the MCP tool list, so clients do not need to reconnect.

## Skill sources

LSM scans these directories in priority order:

```text
1. <workspace_root>/.agents/skills/
2. <state_dir>/agent_config/skills/
3. ${XDG_CONFIG_HOME:-~/.config}/agents/skills/
```

With the default workspace and state directory, the first two paths are:

```text
/workspace/.agents/skills
/workspace/.local-shell-mcp/agent_config/skills
```

Each immediate child directory is one Skill. Its directory name is the Skill name and it must provide `SKILL.md`. Skill directories, `SKILL.md`, related files, and related directories may be symlinks.

When the same Skill name appears in multiple sources, the project source wins over the LSM-managed source, which wins over the global source. `skills_list` reports each accepted Skill's `source` and `source_path`, plus the complete ordered `skills_dirs` list.

## Fixed tools

| Tool | Purpose |
|---|---|
| `skills_list` | Rescan all sources and list Skill names, descriptions, sources, entry paths, related files, and non-fatal warnings without loading full instructions. |
| `skill_load` | Load the complete `SKILL.md` instructions for one exact name returned by `skills_list`. |
| `skill_read_file` | Read one bounded related text file using the Skill-relative path returned by `skill_load`. |

Recommended flow:

```text
skills_list
  -> choose the relevant Skill
  -> skill_load(name)
  -> skill_read_file(name, path) only when a related file is needed
  -> follow the Skill with the existing shell, Git, browser, and remote tools
```

Changes on disk are visible on the next call. No per-Skill MCP tools are registered.

## Installing with the Skills CLI

The project and global sources match the universal directories used by the open `skills` CLI.

Install into the current LSM workspace:

```bash
cd /workspace
npx skills add owner/repository --agent universal -y
```

Install globally:

```bash
npx skills add owner/repository --agent universal --global -y
```

For a specific Skill:

```bash
npx skills add XiNian-dada/Fuck_My_Shit_Mountain \
  --skill fuck-my-shit-mountain \
  --agent universal \
  -y
```

The LSM-managed source remains available for direct file or Git workflows:

```bash
git clone https://example.com/team/my-skill.git \
  /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

Updates and removals made by the CLI, Git, or ordinary filesystem operations are picked up automatically on the next Skill call.

## Validation

The registry skips malformed Skill names and directories without a readable `SKILL.md`. File-size, Skill-count, scan-entry, related-file, and path-output limits still apply. Directory traversal strings are rejected, while filesystem symlinks are followed.

## REST compatibility

The optional REST surface exposes the same merged registry:

```text
GET  /tools/skills_list
POST /tools/skill_load       {"name": "debugging"}
POST /tools/skill_read_file  {"name": "debugging", "path": "checklist.md"}
```
