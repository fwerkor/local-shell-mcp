<!-- i18n-source-sha256: d3c380d9a5d9a43019b0be2b5e9accc0d6e0c785d77226005db60c5721672ba6 -->
# Remote workers

Remote workers `local-shell-mcp` को उन machines को control करने देते हैं जो outbound HTTP(S) requests कर सकती हैं लेकिन inbound SSH connections स्वीकार नहीं कर सकतीं।

```text
MCP client -> control server -> outbound polling worker -> remote machine
```

## Basic workflow

1. `remote_manage(action="invite", ...)` से invite बनाएँ।
2. Generated command remote machine पर चलाएँ।
3. `remote_manage(action="list")` से registration confirm करें।
4. `machine="<worker-name>"` के साथ सामान्य tools call करें, जैसे `environment_get`, `run_shell`, `file_read` या `browser_run_script`।
5. `remote_transfer` से tracked controller-to-worker, worker-to-controller या worker-to-worker file/directory transfer शुरू करें। `job_list` या `job_tail` से follow करें; `job_stop` या `job_retry` से stop/retry करें।
6. `remote_manage(action="rename", ...)` या `remote_manage(action="revoke", ...)` से workers rename या revoke करें।

डिफ़ॉल्ट रूप से एक आमंत्रण से केवल एक worker पंजीकृत होता है (`max_uses=1`)। एक ही आमंत्रण से कई workers पंजीकृत करने के लिए `max_uses` बढ़ाएँ। कई बार उपयोग होने वाले आमंत्रण के लिए `name` खाली रखें। वैकल्पिक `ttl_s` का डिफ़ॉल्ट मान दो घंटे (7200 सेकंड) है और अधिकतम सात दिन (604800 सेकंड) हो सकता है।

केवल worker administration `remote_*` names उपयोग करता है। Execution, shell, job, filesystem, patch और browser operations local और remote दोनों में वही schema share करते हैं। Machine देने पर अतिरिक्त `remote:use` OAuth scope चाहिए।

## Persistent workers

Invite result में platform-specific commands होते हैं:

- `persistent_command` Linux/macOS पर user service install और start करता है।
- `powershell_persistent_command` PowerShell से Windows user task install और start करता है।

Windows पर `local-shell-mcp worker install-service` current user के लिए `local-shell-mcp-worker` task register करता है। यह तुरंत start होता है, reboot के बाद उस user के logon पर फिर start होता है, battery operation की अनुमति देता है, duplicate starts ignore करता है और failed runs retry करता है। Administrator rights आवश्यक नहीं हैं और user sign in से पहले यह नहीं चलता।

हर platform पर वही lifecycle commands उपयोग करें:

```text
local-shell-mcp worker status
local-shell-mcp worker start
local-shell-mcp worker stop
local-shell-mcp worker restart
local-shell-mcp worker uninstall-service
```

Worker log worker state directory में `worker.log` के रूप में stored होता है।

## Capabilities

Workers shell/persistent shell sessions, tracked jobs, filesystem operations, transfer internals, Python execution, patches और dependencies installed होने पर Playwright support करते हैं। Git standard commands `run_shell(machine=...)` से उपयोग करता है।

## Security and versioning

Joined worker MCP client को configured environment पर control देता है। Short invite TTLs, dedicated work directories/accounts उपयोग करें, audit logs review करें और task के बाद workers revoke करें। Generated invite control server version से matching worker code install करता है।

## Troubleshooting

Worker न दिखे तो outbound HTTPS access, public base URL reachability, invite expiry, system time और control-server logs जाँचें।
