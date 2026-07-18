# Agent Skills

`local-shell-mcp` 透過固定的 MCP 工具面支援基於 Markdown 的可重用 Agent Skill。安裝或刪除 Skill 不會改變 MCP 工具列表，因此客戶端無需重新連接。

## Skill 來源

LSM 按以下優先級掃描目錄：

```text
1. <workspace_root>/.agents/skills/
2. <state_dir>/agent_config/skills/
3. ${XDG_CONFIG_HOME:-~/.config}/agents/skills/
```

預設工作區和狀態目錄下，前兩個路徑是：

```text
/workspace/.agents/skills
/workspace/.local-shell-mcp/agent_config/skills
```

每個直接子目錄代表一個 Skill。目錄名就是 Skill 名稱，目錄中必須提供 `SKILL.md`。Skill 目錄、`SKILL.md`、關聯檔案和關聯目錄均可使用符號連結。

同名 Skill 出現在多個來源時，專案級來源優先於 LSM 管理目錄，LSM 管理目錄優先於全域目錄。`skills_list` 會返回每個有效 Skill 的 `source` 和 `source_path`，並透過 `skills_dirs` 給出完整的有序來源列表。

## 固定工具

| 工具 | 用途 |
|---|---|
| `skills_list` | 重新掃描所有來源，列出 Skill 名稱、描述、來源、入口路徑、關聯檔案和非致命警告，不載入完整指令。 |
| `skill_load` | 按 `skills_list` 返回的精確名稱載入完整 `SKILL.md`。 |
| `skill_read_file` | 使用 `skill_load` 返回的 Skill 內相對路徑讀取受大小限制的關聯文字檔案。 |

推薦流程：

```text
skills_list
  -> 選擇相關 Skill
  -> skill_load(name)
  -> 僅在需要關聯檔案時調用 skill_read_file(name, path)
  -> 按 Skill 指令調用現有 shell、Git、瀏覽器和遠端工具
```

磁碟上的修改會在下一次調用時生效，不會為每個 Skill 動態註冊 MCP 工具。

## 使用 Skills CLI 安裝

專案級和全域來源與開放的 `skills` CLI 使用的 universal 目錄一致。

安裝到目前 LSM 工作區：

```bash
cd /workspace
npx skills add owner/repository --agent universal -y
```

安裝到全域目錄：

```bash
npx skills add owner/repository --agent universal --global -y
```

安裝指定 Skill：

```bash
npx skills add XiNian-dada/Fuck_My_Shit_Mountain \
  --skill fuck-my-shit-mountain \
  --agent universal \
  -y
```

LSM 管理目錄仍可透過普通檔案或 Git 操作維護：

```bash
git clone https://example.com/team/my-skill.git \
  /workspace/.local-shell-mcp/agent_config/skills/my-skill
```

透過 CLI、Git 或普通檔案操作完成的更新和刪除，會在下一次 Skill 調用時自動生效。

## 校驗

Registry 會跳過非法 Skill 名稱和缺少可讀 `SKILL.md` 的目錄。入口檔案大小、Skill 數量、掃描條目數、關聯檔案數和路徑輸出限制仍然有效。路徑遍歷字串仍會被拒絕，但檔案系統符號連結會被正常跟隨。

## REST 相容介面

可選 REST 介面使用同一份合併後的 Registry：

```text
GET  /tools/skills_list
POST /tools/skill_load       {"name": "debugging"}
POST /tools/skill_read_file  {"name": "debugging", "path": "checklist.md"}
```
