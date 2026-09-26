<!-- i18n-source-sha256: 13df63c51bc29aa49ae386e7c96e1f729d23914343856b4d20f8776ca0a2acda -->
# Tools reference

यह page वास्तविक MCP tool schemas से बनती है। Public tool surface बदलने के बाद English reference update करने के लिए `python scripts/generate-tools-reference.py` चलाएँ।

अधिकांश tools `ok`, `message` और `data` वाला structured `ToolResult` लौटाते हैं। `workspace_open` MCP App render करने के लिए model-visible state लौटाता है। अधिकतर execution/file tools optional `machine` लेते हैं; इसे छोड़ने पर controller workspace और देने पर connected worker उपयोग होता है। Git operations जानबूझकर dedicated Git wrappers की जगह `run_shell` या अन्य shell tool से की जाती हैं।

## Selection guide

| Need | Preferred tools |
|---|---|
| ChatGPT में execution monitor या collaborate करना | `workspace_open` |
| Environment inspect करना | `environment_get`, `file_tree`, `file_read` |
| Short command या Git operation चलाना | `run_shell` |
| Interactive या long task चलाना | `shell_start` or `job_start` |
| File में exact changes करना | `file_edit` or `file_patch` |
| File या directory transfer करना | `remote_transfer` |
| External MCP capability discover करना | `mcp_tool_search`, then `mcp_tool_inspect` |
| Page से interact करना | `browser_session`, `browser_snapshot`, then `browser_act` |
| Custom browser logic चलाना | `browser_run_script` |
| Control a native desktop app | `gui_list`, `gui_state`, then `gui_action` |
| Remote machine पर काम करना | उसी tool के साथ `machine` उपयोग करें; केवल worker administration के लिए `remote_*` |

## Interactive workspace

### `workspace_open`

स्पष्ट रूप से दिए गए Logical Session को दिखाने वाला Live Workspace खोलें या पुनः उपयोग करें। session_manage से मिला सक्रिय session_id दें। Workspace कभी भी MCP transport से task identity का अनुमान नहीं लगाता; जब कोई Logical Session सक्रिय न हो तो स्पष्ट रूप से null दें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string \| null` | required |  |
| `machine` | `string \| null` | `null` |  |
| `cwd` | `string` | `"."` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

## Environment, Skills और task state

### `environment_get`

Local या remote machine की version, workspace, auth, policy और environment information लौटाती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `skill_list`

Installed Agent Skills को instructions load किए बिना सूचीबद्ध करती है। MCP tool surface स्थिर रहता है; Skill directories जोड़ने/हटाने का प्रभाव अगली call में दिखता है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_load`

`skill_list` से exact name द्वारा installed Skill load करती है। पूर्ण `SKILL.md` instructions और related file paths लौटाती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `skill_read`

Installed Skill की एक related text file पढ़ती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `path` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `secret_scan`

Commit या push से पहले local workspace text files में common secrets scan करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `max_results` | `integer` | `200` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `session_manage`

एक durable Logical Session को प्रबंधित करें। start नई task बनाता है और उसका session_id लौटाता है। resume केवल उसी explicit session_id को जारी रखता है जो user ने दिया हो या इस conversation में पहले से मौजूद हो। start के अलावा हर action में session_id आवश्यक है। Actions: start, resume, get, report, finish, cancel, delete. report summary/findings/next/blockers/objective/label स्वीकार करता है; delete के लिए terminal Session आवश्यक है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `label` | `string \| null` | `null` |  |
| `objective` | `string \| null` | `null` |  |
| `summary` | `string \| null` | `null` |  |
| `findings` | `array[string] \| null` | `null` |  |
| `next` | `string \| null` | `null` |  |
| `blockers` | `array[string] \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `plan_manage`

Explicit Logical Session के optional Goal mode को प्रबंधित करें। active plan, agent activity न होने के 15 मिनट बाद automatic continuation सक्षम करता है, अधिकतम 10 attempts तक। session_id वही durable id होना चाहिए जो session_manage ने लौटाया है। Actions: start, get, update, block, resume, finish, cancel. start के लिए objective और steps आवश्यक हैं; finish के लिए सभी steps completed या skipped होने चाहिए।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string` | required |  |
| `objective` | `string \| null` | `null` |  |
| `steps` | `array[object] \| null` | `null` |  |
| `step_id` | `string \| null` | `null` |  |
| `status` | `string \| null` | `null` |  |
| `text` | `string \| null` | `null` |  |
| `note` | `string \| null` | `null` |  |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `audit_tail`

Recent local audit log entries पढ़ती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `lines` | `integer` | `100` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Shells और jobs

### `run_shell`

Local या remote machine पर एक non-interactive shell command चलाती है। शीघ्र समाप्त होने वाले build, test, package-manager, Git और inspection commands के लिए उपयोग करें। Long-running, interactive या streaming process के लिए `shell_start` या `job_start` उपयोग करें। Optional purpose/explanation fields execution का कारण बता सकते हैं।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `max_output_bytes` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `run_python`

Local या remote machine पर short Python script लिखकर चलाती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `code` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `shell_start`

Local या remote machine पर persistent interactive shell शुरू करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `shell_send`

Persistent local/remote shell session को input भेजती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `input_text` | `string` | required |  |
| `enter` | `boolean` | `true` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `shell_read`

Persistent local/remote shell session का recent output पढ़ती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `shell_stop`

Persistent local/remote shell session समाप्त करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `shell_list`

Local या remote machine पर persistent shell sessions सूचीबद्ध करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `job_start`

Local या remote machine पर tracked long-running job शुरू करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `command` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `name` | `string \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `job_list`

Local या remote machine पर tracked jobs सूचीबद्ध करती है। Active jobs पहले लौटाए जाते हैं; `limit` को 1-1000 के बीच सीमित किया जाता है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_finished` | `boolean` | `true` |  |
| `limit` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `job_tail`

Tracked local/remote job का recent output पढ़ती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `lines` | `integer` | `200` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `job_stop`

Tracked local/remote job रोकती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `job_retry`

Stopped/exited tracked local/remote job पुनः शुरू करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `job_id` | `string` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

## Files और transfer

### `file_list`

Local या remote machine पर files और directories सूचीबद्ध करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | `"."` |  |
| `recursive` | `boolean` | `false` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_tree`

Local या remote machine पर compact directory tree लौटाती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `cwd` | `string` | `"."` |  |
| `depth` | `integer` | `3` |  |
| `max_entries` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_glob`

Local या remote machine पर glob से paths खोजती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `pattern` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `max_results` | `integer` | `500` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_grep`

Local या remote machine पर file contents खोजती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `glob` | `string \| null` | `null` |  |
| `regex` | `boolean` | `true` |  |
| `case_sensitive` | `boolean` | `true` |  |
| `max_results` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_read`

Local या remote machine पर एक file या files की list पढ़ती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string \| array[string]` | required |  |
| `start_line` | `integer \| null` | `null` |  |
| `end_line` | `integer \| null` | `null` |  |
| `binary_preview` | `string \| null` | `null` |  |
| `binary_preview_bytes` | `integer` | `256` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `image_view`

PNG, JPEG, GIF या WebP को native MCP image content के रूप में local या remote machine पर दिखाती है। Visual inspection के लिए `file_read` की बजाय उपयोग करें। Remote images existing file-transfer protocol reuse करती हैं, इसलिए worker को image-specific RPC नहीं चाहिए।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_write`

Local या remote machine पर UTF-8 text file लिखती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `content` | `string` | required |  |
| `overwrite` | `boolean` | `true` |  |
| `encoding` | `string` | `"utf-8"` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_edit`

एक local/remote file पर एक या अधिक exact-text edits लागू करती है। हर edit में old, new और optional `replace_all` होता है; old को whitespace और indentation सहित exact match होना चाहिए।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `edits` | `array[TextEdit]` | required |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_delete`

Local/remote file या directory हटाती है। `recursive=false` files या empty directories हटाता है; non-empty directories के लिए `recursive=true` आवश्यक है और सावधानी से उपयोग करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `recursive` | `boolean` | `false` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `file_patch`

Local या remote unified diff या file_patch envelope check और apply करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `patch` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `remote_transfer`

Controller और remote machines के बीच file या directory copy करने वाला tracked job शुरू करता है। Remote uploads resumable raw-binary chunks उपयोग करते हैं; transfer को `job_list`, `job_tail`, `job_stop` और `job_retry` से manage करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `source_path` | `string` | required |  |
| `destination_path` | `string` | required |  |
| `source_machine` | `string \| null` | `null` |  |
| `destination_machine` | `string \| null` | `null` |  |
| `overwrite` | `boolean` | `false` |  |
| `chunk_size` | `integer \| null` | `null` |  |
| `purpose` | `string \| null` | `null` |  |
| `explanation` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`source_machine` और `destination_machine` में से कम-से-कम एक देना जरूरी है। छोड़ा गया endpoint controller workspace को दर्शाता है; source file या directory हो सकता है।

### `link_create`

Local file के लिए temporary browser-accessible URL बनाती है। Default response attachment download है; browser या Markdown image में direct render के लिए `inline=true` करें। Links high-entropy token, TTL, optional download-count limit और explicit revocation से सुरक्षित public bearer URLs हैं।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `path` | `string` | required |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `filename` | `string \| null` | `null` |  |
| `max_downloads` | `integer \| null` | `null` |  |
| `inline` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_list`

Generated local file download URLs सूचीबद्ध करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `include_expired` | `boolean` | `false` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `link_revoke`

Generated local file download URL revoke करती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `token` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Dynamic MCP gateway

### `mcp_manage`

Dynamic MCP servers के isolated environment/headers को register, list, get, enable, disable, refresh, remove या update करती है। Transport `stdio` के साथ command/args/cwd और `streamable_http` के साथ url उपयोग करें। Secret env/header values privately persist होते हैं और कभी लौटाए नहीं जाते।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `transport` | `string \| null` | `null` |  |
| `command` | `string \| null` | `null` |  |
| `args` | `array[string] \| null` | `null` |  |
| `cwd` | `string \| null` | `null` |  |
| `url` | `string \| null` | `null` |  |
| `env` | `object \| null` | `null` |  |
| `headers` | `object \| null` | `null` |  |
| `enabled` | `boolean` | `true` |  |
| `overwrite` | `boolean` | `false` |  |
| `refresh` | `boolean` | `true` |  |
| `key` | `string \| null` | `null` |  |
| `value` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_search`

Enabled dynamic MCP servers से cached lightweight tool summaries खोजती है। Dynamic tools इस server के `tools/list` में नहीं आतीं; call से पहले returned `<server>:<tool>` name को `mcp_tool_inspect` से inspect करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `query` | `string` | `""` |  |
| `server` | `string \| null` | `null` |  |
| `limit` | `integer` | `20` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_inspect`

`<server>:<tool>` नामक dynamic MCP tool का full cached schema लौटाती है। Cache stale हो तो `mcp_manage` से server refresh करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

### `mcp_tool_call`

Cached dynamic MCP tool `<server>:<tool>` call करती है। पहले `mcp_tool_search` से discover और `mcp_tool_inspect` से schema inspect करें। External MCP connections केवल call की अवधि में खुलती हैं।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `name` | `string` | required |  |
| `arguments` | `object \| null` | `null` |  |
| `timeout_s` | `integer \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

## Browser automation

### `browser_session`

Local या remote persistent high-level browser sessions start, list, close या cleanup करती है। `start` URL खोल सकता है, persistent `profile_id` reuse कर सकता है या `storage_state_path` load कर सकता है; `close` storage state save कर सकता है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `session_id` | `string \| null` | `null` |  |
| `browser` | `string` | `"chromium"` |  |
| `headless` | `boolean` | `true` |  |
| `width` | `integer` | `1440` |  |
| `height` | `integer` | `1000` |  |
| `url` | `string \| null` | `null` |  |
| `wait_until` | `string` | `"domcontentloaded"` |  |
| `profile_id` | `string \| null` | `null` |  |
| `storage_state_path` | `string \| null` | `null` |  |
| `save_storage_state_path` | `string \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `browser_snapshot`

Persistent browser page capture करती है: title, URL, bounded visible text, `e1` जैसे stable short refs वाले interactive elements, recent page/network errors और optional screenshot path। Page navigate या नया snapshot होने तक refs को `browser_act` targets के रूप में सीधे उपयोग करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `include_text` | `boolean` | `true` |  |
| `screenshot` | `boolean` | `true` |  |
| `full_page` | `boolean` | `false` |  |
| `max_text_chars` | `integer` | `100000` |  |
| `max_elements` | `integer` | `100` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `browser_act`

Persistent browser session में structured actions चलाती है। navigate, new_page, close_page, click, fill, type, select, press, check, uncheck, hover, wait, wait_for_text और wait_for_url support करती है। `target` `browser_snapshot` ref जैसे `e1` या CSS selector हो सकता है। High-level actions पर्याप्त न हों तभी `browser_run_script` उपयोग करें।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `session_id` | `string` | required |  |
| `actions` | `array[object]` | required |  |
| `page_id` | `string \| null` | `null` |  |
| `timeout_ms` | `integer` | `30000` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

### `browser_run_script`

Local या remote machine पर full Python Playwright script चलाती है।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `script` | `string` | required |  |
| `cwd` | `string` | `"."` |  |
| `timeout_s` | `integer` | `60` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।

## डेस्कटॉप GUI ऑटोमेशन

### `gui_list`

List visible desktop application windows and GUI backend capabilities locally or remotely.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_state`

Observe one desktop window before acting. Returns its accessibility elements plus an optional native MCP screenshot and a short-lived state_id. Prefer element_id actions; coordinate actions are relative to the observed window and are rejected if the window moved or resized.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `screenshot` | `boolean` | `true` |  |
| `include_elements` | `boolean` | `true` |  |
| `max_elements` | `integer` | `300` |  |
| `max_depth` | `integer` | `12` |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

### `gui_action`

Execute GUI actions against a fresh gui_state observation locally or remotely. The state_id is single-use. Prefer semantic element_id targeting; raw x/y coordinates are window-relative. Supported actions are click, double_click, right_click, move, scroll, drag, type, key, set_value, focus, and wait.

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `window_id` | `string` | required |  |
| `state_id` | `string` | required |  |
| `actions` | `array[GuiAction]` | required |  |
| `machine` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | Logical Session for this tool call. Pass the session_id returned by session_manage while working in that task. Use null only when no Logical Session is active. This is the same durable session_id used by session_manage. |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

When `machine` is supplied, the call additionally requires `remote:use` and runs through the remote worker protocol.

## Remote worker administration

### `remote_manage`

action=invite, list, revoke या rename से remote workers manage करती है। invite name/workdir/ttl_s स्वीकार करता है; revoke को machine; rename को machine और new_name चाहिए।

| Parameter | Type | Required/default | Description |
|---|---|---|---|
| `action` | `string` | required |  |
| `name` | `string \| null` | `null` |  |
| `workdir` | `string \| null` | `null` |  |
| `ttl_s` | `integer \| null` | `null` |  |
| `machine` | `string \| null` | `null` |  |
| `new_name` | `string \| null` | `null` |  |
| `logical_session_id` | `string \| null` | required | इस tool call के लिए Logical Session। task पर काम करते समय session_manage से मिला session_id दें। null केवल तब दें जब कोई Logical Session सक्रिय न हो। |

OAuth scopes: `shell:read, shell:write, shell:execute, browser:use, file:share, remote:use`.

`machine` देने पर call को अतिरिक्त `remote:use` चाहिए और वह remote worker protocol के जरिए चलता है।
