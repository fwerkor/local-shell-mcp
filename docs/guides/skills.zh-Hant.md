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
| `skill_load` | 按 `skills_list` 返回的精確名稱載入完整 `SKILL.md`。關聯檔案只返回路徑，需要時再單獨讀取。 |

推薦流程：

```text
skills_list
  -> 選擇相關 Skill
  -> skill_load(name)
  -> 按 Skill 指令調用已有 shell、檔案、Git、瀏覽器或遠程工具
```

兩個工具都是只讀工具。每次調用都會重新掃描目錄，因此磁碟上的修改會在下一次調用時生效。

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
- 從 front matter 或首個正文段落提取簡短描述；
- 只返回關聯檔案路徑，不把所有關聯內容一次性塞進模型上下文。

應把 Skill 視為發布者提供的指令和代碼。放入服務端目錄前，先審查 `SKILL.md` 和其中腳本。

## REST 相容接口

可選 REST 接口使用同一份 Skill Registry：

```text
GET  /tools/skills_list
POST /tools/skill_load   {"name": "debugging"}
```
