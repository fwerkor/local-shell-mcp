# Agent Skills

`local-shell-mcp` 通过固定的 MCP 工具面支持基于 Markdown 的可复用 Agent Skill。安装或删除 Skill 不会改变 MCP 工具列表，因此客户端无需重新连接。

## Skill 来源

LSM 按以下优先级扫描目录：

```text
1. <workspace_root>/.agents/skills/
2. <state_dir>/agent_config/skills/
3. ${XDG_CONFIG_HOME:-~/.config}/agents/skills/
```

默认工作区和状态目录下，前两个路径是：

```text
/workspace/.agents/skills
/workspace/.local-shell-mcp/agent_config/skills
```

每个直接子目录代表一个 Skill。目录名就是 Skill 名称，目录中必须提供 `SKILL.md`。Skill 目录、`SKILL.md`、关联文件和关联目录均可使用符号链接。

同名 Skill 出现在多个来源时，项目级来源优先于 LSM 管理目录，LSM 管理目录优先于全局目录。`skills_list` 会返回每个有效 Skill 的 `source` 和 `source_path`，并通过 `skills_dirs` 给出完整的有序来源列表。

## 固定工具

| 工具 | 用途 |
|---|---|
| `skills_list` | 重新扫描所有来源，列出 Skill 名称、描述、来源、入口路径、关联文件和非致命警告，不加载完整指令。 |
| `skill_load` | 按 `skills_list` 返回的精确名称加载完整 `SKILL.md`。 |
| `skill_read_file` | 使用 `skill_load` 返回的 Skill 内相对路径读取受大小限制的关联文本文件。 |

推荐流程：

```text
skills_list
  -> 选择相关 Skill
  -> skill_load(name)
  -> 仅在需要关联文件时调用 skill_read_file(name, path)
  -> 按 Skill 指令调用现有 shell、Git、浏览器和远程工具
```

磁盘上的修改会在下一次调用时生效，不会为每个 Skill 动态注册 MCP 工具。

## 使用 Skills CLI 安装

项目级和全局来源与开放的 `skills` CLI 使用的 universal 目录一致。

安装到当前 LSM 工作区：

```bash
cd /workspace
npx skills add owner/repository --agent universal -y
```

安装到全局目录：

```bash
npx skills add owner/repository --agent universal --global -y
```

安装指定 Skill：

```bash
npx skills add XiNian-dada/Fuck_My_Shit_Mountain \
  --skill fuck-my-shit-mountain \
  --agent universal \
  -y
```

LSM 管理目录仍可通过普通文件或 Git 操作维护：

```bash
git clone https://example.com/team/my-skill.git \
  /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

通过 CLI、Git 或普通文件操作完成的更新和删除，会在下一次 Skill 调用时自动生效。

## 校验

Registry 会跳过非法 Skill 名称和缺少可读 `SKILL.md` 的目录。入口文件大小、Skill 数量、扫描条目数、关联文件数和路径输出限制仍然有效。路径遍历字符串仍会被拒绝，但文件系统符号链接会被正常跟随。

## REST 兼容接口

可选 REST 接口使用同一份合并后的 Registry：

```text
GET  /tools/skills_list
POST /tools/skill_load       {"name": "debugging"}
POST /tools/skill_read_file  {"name": "debugging", "path": "checklist.md"}
```
