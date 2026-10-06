<!-- i18n-source-sha256: 2f0d76e5baf715634ab1bed49cb63a1382ae50536e2b8ebb880f3a27df3f8abc -->
# उपयोग पैटर्न और prompting guide

`local-shell-mcp` शक्तिशाली tools देता है। अच्छे परिणामों के लिए model से पहले निरीक्षण, छोटे कदमों में कार्य, verification और बदली चीजों की रिपोर्ट माँगें।

## सामान्य operating loop

अधिकांश coding tasks में यह loop उपयोग करें:

1. Inspect: `environment_get`, `file_tree`, `file_grep`, `file_read` और `git status` जैसे commands के लिए `run_shell`।
2. Plan: model से शामिल न्यूनतम files और tests पहचानने को कहें।
3. Edit: `file_edit`, `file_patch` या shell commands उपयोग करें।
4. Verify: `run_shell` या persistent shells से targeted tests/builds चलाएँ।
5. Review: `run_shell` से `git diff` चलाएँ, फिर जरूरत पर `secret_scan` और `audit_tail`।
6. Commit/export: `run_shell` से स्पष्ट Git CLI commands या `link_create` उपयोग करें।

## Tool चयन

| Task | प्राथमिकता | बचें |
|---|---|---|
| छोटा one-shot command | `run_shell` | हर command के लिए persistent shell शुरू करना |
| लंबा dev server, REPL, watch task | `shell_start` + `shell_read` + `shell_send` | timeout तक `run_shell` block करना |
| Structured analysis या file generation | `run_python` | जटिल JSON/text के लिए fragile shell pipelines |
| छोटा exact edit | `file_edit` | अनावश्यक पूरा file rewrite |
| एक file में एक या कई replacements | `file_edit` with an `edits` array | फिर पढ़े बिना stale edits दोहराना |
| Multi-file patch | `file_patch` | Ad hoc shell edits |
| Files खोजना | `file_tree`, `file_glob` | बड़े repositories की पूरी recursive listing |
| Code खोजना | `file_grep` | कई files बिना उद्देश्य पढ़ना |
| Browser evidence | `browser_snapshot`, `browser_run_script` | page name/route से अनुमान लगाना |
| Downloadable artifacts | `link_create` | बड़ा binary content chat में paste करना |
| Remote machine work | normal tools with `machine`, plus `remote_transfer` | outbound worker पर्याप्त होने पर inbound SSH खोलना |

## CLI से tools कॉल करना

shell scripts और CI के लिए `lsm call <tool>` चल रहे loopback controller के माध्यम से वही registered tool surface कॉल करता है, इसलिए remote workers और controller state सुरक्षित रहती है।

```bash
lsm call run_shell --json '{"command":"uname -a"}'
printf '%s\n' '{"path":"README.md"}' | lsm call file_read
```

कॉल को Logical Session से जोड़ने के लिए `--session s_...` इस्तेमाल करें। दस्तावेज़ित Docker Compose setup में मूल `LOCAL_SHELL_MCP_CLI_LOCAL_TOKEN` केवल host-owned, permission-restricted `.env` में रहता है, जबकि Compose controller में सिर्फ SHA-256 verifier भेजता है; अन्य split-runtime layouts `--token-file <path>` इस्तेमाल कर सकते हैं। `--direct` controller को bypass करता है, मौजूदा `.env` runtime settings को process के भीतर लागू करता है, host CLI token को tool environment में inject नहीं करता और केवल local calls के लिए है।

## Prompt templates

### Read-only repository orientation

```text
local-shell-mcp उपयोग करें। repository layout और git status देखें। Files न बदलें। बदलाव से पहले मुख्य components, अनुमानित test commands और स्पष्ट risks का सार दें।
```

### Focused bug fix

```text
Bug ठीक करने के लिए local-shell-mcp उपयोग करें। पहले सबसे छोटे relevant command से उसे reproduce या locate करें। Edit से पहले files पढ़ें। Minimal patch बनाएँ, targeted verification चलाएँ, फिर git diff और ठीक-ठीक चलाए गए tests दिखाएँ। मेरी स्वीकृति से पहले commit न करें।
```

### Commit और push workflow

```text
local-shell-mcp उपयोग करें। git status और diff जाँचें, relevant tests और secret_scan चलाएँ, concise message के साथ एक focused commit बनाएँ, फिर current branch push करें। Cache, build artifacts या unrelated formatting शामिल न करें।
```

### Long-running process

```text
Dev server को persistent shell session में शुरू करें, ready होने तक output पढ़ें, फिर browser tools से page verify करें। session id रखें और verification के बाद session kill करें।
```

### Remote worker task

```text
Connected remote worker <machine> उपयोग करें। पहले machine=<machine> के साथ environment_get, फिर उसी machine के साथ file_list कॉल करें। केवल configured remote workdir में काम करें। छोटे commands के लिए run_shell और लंबे काम के लिए shell_start या job_start उपयोग करें।
```

## Repositories के साथ काम

Open-source changes के लिए अनुशंसित sequence:

1. `run_shell` से `git status --short --branch` चलाएँ।
2. जब upstream state महत्वपूर्ण हो तो explicit Git CLI commands से fetch और branches inspect करें।
3. Edit से पहले `file_grep` और `file_read` उपयोग करें।
4. Minimal patch बनाएँ।
5. पहले targeted tests, फिर संभव हो तो broader tests चलाएँ।
6. Commit/push से पहले `secret_scan` चलाएँ।
7. Explicit stage और commit concise message के साथ करें।

Reviewable history के लिए logical change प्रति एक commit माँगें।

## Generated artifacts के साथ काम

PDFs, reports, screenshots, archives या logs के लिए:

1. Workspace के अंदर file generate करें।
2. File मौजूद है और expected size का है, यह verify करें।
3. Short TTL और optional `max_downloads` के साथ `link_create` उपयोग करें।
4. Link की जरूरत खत्म होने पर revoke करें।

Private keys, credential directories या unrelated personal data के public links न बनाएँ।

## Remote machines के साथ काम

Remote worker mode तब उपयोगी है जब machine outbound HTTPS कर सकती हो पर inbound SSH स्वीकार नहीं कर सकती।

अच्छी practices:

- `remote_manage(action="invite", ...)` या `remote_manage(action="rename", ...)` से machines बनाएँ/rename करें।
- काम से पहले `environment_get(machine=...)` कॉल करें।
- `remote_transfer` से controller/worker या worker/worker transfer jobs शुरू करें और normal `job_*` tools से manage करें।
- Task के बाद `remote_manage(action="revoke", ...)` से workers revoke करें।

## Anti-patterns

जब तक environment disposable न हो और consequences समझे न गए हों, इन निर्देशों से बचें:

- Host-launched server पर “जो चाहिए globally install करो”.
- Time bounds या verification criteria के बिना “चलाते रहो जब तक काम न करे”.
- Generated artifacts वाले repository में “सब commit करो”.
- Convenience के लिए “पूरा home directory expose करो”.
- “पूरे workspace का file link बनाओ”.
- `LOCAL_SHELL_MCP_AUTH_MODE=none` के साथ public deployment चलाना.
