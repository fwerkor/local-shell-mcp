# Agent Skills

`local-shell-mcp` 透過固定的 MCP 工具面支援基於 Markdown 的可重用 Agent Skill。安裝或刪除 Skill 不會增刪 MCP 工具，因此客戶端無需刷新 `tools/list`，也無需重新連接。

## 目錄結構

Skill 從以下目錄讀取：

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

預設工作區下的實際路徑是：

```text
/workspace/.local-shell-mcp/agent_config/skills
```

每個直接子目錄代表一個 Skill。目錄名就是 Skill 名稱，目錄內必須包含普通檔案 `SKILL.md`。Skills 不要求存在 `config.json`。

## 固定工具

| 工具 | 用途 |
|---|---|
| `skills_list` | 重新掃描目錄並列出已安裝 Skill 的名稱、描述、入口路徑、關聯檔案和非致命警告，不載入完整指令。 |
| `skill_load` | 按 `skills_list` 返回的精確名稱載入完整 `SKILL.md`。關聯檔案返回 Skill 內相對路徑。 |
| `skill_read_file` | 使用 `skill_load` 返回的 Skill 名稱和相對路徑，讀取一個受大小限制的關聯文字檔案。 |

推薦流程：

```text
skills_list
  -> 選擇相關 Skill
  -> skill_load(name)
  -> 僅在需要關聯檔案時調用 skill_read_file(name, path)
  -> 按 Skill 指令調用已有 shell、Git、瀏覽器或遠程工具
```

三個工具都是固定的只讀工具。`skills_list` 執行有界註冊表掃描；`skill_load` 和 `skill_read_file` 只訪問指定 Skill。磁碟修改會在下一次調用時生效。

## 安裝和更新 Skill

運行時有意不內置 Skill 市場或包管理器。使用普通檔案或 Git 操作管理該目錄，例如：

```bash
cp -R ./my-skill /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

或者：

```bash
git clone https://example.com/team/skills.git /tmp/team-skills
cp -R /tmp/team-skills/debugging /workspace/.local-shell-mcp/agent_config/skills/debugging
```

更新和刪除同樣使用普通檔案或 Git 工作流。之後調用 `skills_list` 或 `skill_load` 即可看到新內容，不會改變 MCP 工具列表。

## 校驗與安全

掃描器會：

- 拒絕逃逸出配置目錄的 Skill 目錄和 `SKILL.md`；
- 拒絕符號連結形式的 Skill 目錄、入口檔案和關聯檔案；
- 跳過缺少 `SKILL.md` 的目錄並返回警告；
- 解析有長度上限的 YAML 或 TOML front matter 描述，並支援正文和標題回退；
- 限制入口檔案大小、Skill 數量、掃描條目數、關聯檔案數和路徑輸出總量；
- 返回 Skill 內相對路徑，並透過 `skill_read_file` 讀取，避免向普通檔案工具暴露工作區外配置目錄。

應把 Skill 視為發布者提供的指令和代碼。放入服務端目錄前，先審查 `SKILL.md` 和其中腳本。

## REST 相容接口

可選 REST 接口使用同一份 Skill Registry：

```text
GET  /tools/skills_list
POST /tools/skill_load       {"name": "debugging"}
POST /tools/skill_read_file  {"name": "debugging", "path": "checklist.md"}
```
