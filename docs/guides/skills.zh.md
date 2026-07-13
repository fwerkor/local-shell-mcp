# Agent Skills

`local-shell-mcp` 通过固定的 MCP 工具面支持基于 Markdown 的可复用 Agent Skill。安装或删除 Skill 不会增删 MCP 工具，因此客户端无需刷新 `tools/list`，也无需重新连接。

## 目录结构

Skill 从以下目录读取：

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

默认工作区下的实际路径是：

```text
/workspace/.local-shell-mcp/agent_config/skills
```

每个直接子目录代表一个 Skill。目录名就是 Skill 名称，目录内必须包含普通文件 `SKILL.md`。Skills 不要求存在 `config.json`。

## 固定工具

| 工具 | 用途 |
|---|---|
| `skills_list` | 重新扫描目录并列出已安装 Skill 的名称、描述、入口路径、关联文件和非致命警告，不加载完整指令。 |
| `skill_load` | 按 `skills_list` 返回的精确名称加载完整 `SKILL.md`。关联文件返回 Skill 内相对路径。 |
| `skill_read_file` | 使用 `skill_load` 返回的 Skill 名称和相对路径，读取一个受大小限制的关联文本文件。 |

推荐流程：

```text
skills_list
  -> 选择相关 Skill
  -> skill_load(name)
  -> 仅在需要关联文件时调用 skill_read_file(name, path)
  -> 按 Skill 指令调用已有 shell、Git、浏览器或远程工具
```

三个工具都是固定的只读工具。`skills_list` 执行有界注册表扫描；`skill_load` 和 `skill_read_file` 只访问指定 Skill。磁盘修改会在下一次调用时生效。

## 安装和更新 Skill

运行时有意不内置 Skill 市场或包管理器。使用普通文件或 Git 操作管理该目录，例如：

```bash
cp -R ./my-skill /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

或者：

```bash
git clone https://example.com/team/skills.git /tmp/team-skills
cp -R /tmp/team-skills/debugging /workspace/.local-shell-mcp/agent_config/skills/debugging
```

更新和删除同样使用普通文件或 Git 工作流。之后调用 `skills_list` 或 `skill_load` 即可看到新内容，不会改变 MCP 工具列表。

## 校验与安全

扫描器会：

- 拒绝逃逸出配置目录的 Skill 目录和 `SKILL.md`；
- 拒绝符号链接形式的 Skill 目录、入口文件和关联文件；
- 跳过缺少 `SKILL.md` 的目录并返回警告；
- 解析有长度上限的 YAML 或 TOML front matter 描述，并支持正文和标题回退；
- 限制入口文件大小、Skill 数量、扫描条目数、关联文件数和路径输出总量；
- 返回 Skill 内相对路径，并通过 `skill_read_file` 读取，避免向普通文件工具暴露工作区外配置目录。

应把 Skill 视为发布者提供的指令和代码。放入服务端目录前，先审查 `SKILL.md` 和其中脚本。

## REST 兼容接口

可选 REST 接口使用同一份 Skill Registry：

```text
GET  /tools/skills_list
POST /tools/skill_load       {"name": "debugging"}
POST /tools/skill_read_file  {"name": "debugging", "path": "checklist.md"}
```
