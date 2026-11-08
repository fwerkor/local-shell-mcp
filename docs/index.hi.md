<!-- i18n-source-sha256: f8fefdb11bbe7b5b755fd59ee829b2771e8c2e9694d5b9db40f8693f53c16960 -->
<div class="hero-shell" markdown>
<span class="hero-eyebrow">स्व-होस्टेड एआई कार्यक्षेत्र · एमसीपी नियंत्रण विमान</span>

# local-shell-mcp

एक स्व-होस्टेड इंटरफ़ेस में चैट, प्रोजेक्ट, फ़ाइलें, टर्मिनल, रिमोट मशीनें और एआई उपकरण। जब आपको बाहरी एमसीपी क्लाइंट की आवश्यकता हो तो उन्हें कनेक्ट करें।

<div class="hero-actions" markdown>
[शुरू करें](getting-started/quickstart.md){ .hero-action .hero-action--primary }
[Web workspace](getting-started/web-workspace.md){ .hero-action .hero-action--secondary }
[Tools reference](reference/tools.md){ .hero-action .hero-action--secondary }
</div>
</div>

<div class="feature-grid" markdown>
<div class="feature-card" markdown>
### वास्तविक coding environment
एक MCP endpoint से tests चलाएँ, repositories inspect करें, files patch करें, Git operate करें और audit trail रखें।
</div>

<div class="feature-card" markdown>
### एकीकृत वेब कार्यक्षेत्र
नियंत्रक फ़ाइलों, टर्मिनलों, डेस्कटॉप, सत्रों, रिमोट और ऑडिट के साथ-साथ अंतर्निहित चैट और प्रोजेक्ट इतिहास का उपयोग करें। बाहरी एमसीपी क्लाइंट वैकल्पिक रहते हैं।
</div>

<div class="feature-card" markdown>
### Remote machine control
SSH ports खोले बिना outbound worker connections से NAT, firewall या HPC machines जोड़ें।
</div>
</div>

## क्या प्रदान करता है

`local-shell-mcp` बाहरी ग्राहकों के लिए एक एकीकृत स्व-होस्टेड AI कार्यक्षेत्र और एक MCP सर्वर प्रदान करता है। यह प्रमाणित एमसीपी एंडपॉइंट के माध्यम से शेल, लगातार शेल, फाइल सिस्टम, खोज, पैच, गिट, प्लेराइट, ऑडिट, वैकल्पिक लक्ष्य योजनाओं के साथ टिकाऊ तार्किक सत्र, टोकनयुक्त फ़ाइल-लिंक और रिमोट-वर्कर टूल प्रदान करता है।

जब AI को repository inspect करना, tests चलाना, files edit करना, Git operate करना, browser evidence इकट्ठा करना, downloadable artifacts बनाना या केवल control server की ओर outbound connect कर सकने वाली remote machine को control करना हो, तब इसका उपयोग करें।

## Architecture

```text
Runtime layer: Docker / VS Code extension / binary / Python / stdio
Exposure layer: localhost / HTTPS proxy / tunnel / stdio pipe
क्लाइंट परत: एकीकृत वेबयूआई/जेमिनी/चैटजीपीटी/जेनेरिक एमसीपी क्लाइंट
Controlled workspace: /workspace or configured workspace root
Optional remote workers: outbound machine connections
```

इच्छित isolation boundary service चलाने वाला container या VM है।

## Scenario के अनुसार शुरुआत

| Scenario | यहाँ से शुरू करें | क्यों |
|---|---|---|
| प्राथमिक ब्राउज़र कार्यक्षेत्र | [Unified web workspace](getting-started/web-workspace.md) | साझा लॉगिन के साथ चैट, प्रोजेक्ट और एलएसएम नियंत्रण पृष्ठ |
| प्रथम नियंत्रक परिनियोजन | [Quickstart](getting-started/quickstart.md) | अनुशंसित बाइनरी, OAuth और पहला ब्राउज़र सत्र |
| runtime layer चुनना | [Runtime choices](guides/deployment.md) | Docker, VS Code, binary, Python और stdio को अलग runtime options के रूप में समझाता है |
| जेमिनी स्पार्क को जोड़ना | [Gemini Custom Apps](getting-started/gemini-spark.md) | पात्रता, HTTPS MCP URL, OAuth और परीक्षण |
| ChatGPT को client के रूप में जोड़ना | [ChatGPT connector](getting-started/chatgpt-connector.md) | Endpoint, OAuth, पहला safe prompt, tool discovery |
| LSM को DeepSeek Harness में जोड़ना | [DeepSeek Harness plugin](clients/deepseek-harness.md) | इस repository को DSH bundle के रूप में install करें और पूर्ण LSM tool/remote-worker surface बनाए रखें |
| VS Code से चलाना | [VS Code extension runtime](installation/vscode-extension.md) | Editor-launched runtime और host safety notes |
| toolset operate करना सीखना | [Usage patterns](guides/usage-patterns.md) | Prompt templates और tool-choice guidance |
| हर tool समझना | [Tools reference](reference/tools.md) | हर tool का purpose, inputs, returns, combinations और notes |
| HPC, NPU/GPU या server node जोड़ना | [Remote workers](guides/remote-workers.md) | Outbound worker join flow और remote tool usage |
| Generated files share करना | [File links](guides/file-links.md) | TTL और revocation वाले tokenized download URLs |
| Deployment harden करना | [Security](security.md) | Isolation, OAuth, workspace scope और audit logs |

## मुख्य tool families

| Family | Examples | उपयोग |
|---|---|---|
| Shell and Python | `run_shell`, `run_python`, `shell_start` | Builds, tests, scripts, long-running processes |
| Files and search | `file_tree`, `file_grep`, `file_read`, `file_patch` | Repository inspection और precise edits |
| Git | `run_shell`, `run_shell`, `run_shell`, `run_shell` | Reviewable source-control workflows |
| Sessions और goals | `session_manage`, `plan_manage` | Durable task handoff, progress reports और optional Goal mode |
| Browser | `browser_session`, `browser_snapshot`, `browser_act`, `browser_run_script` | Persistent interaction, UI checks, screenshots, rendered docs और page text |
| File links | `link_create`, `link_revoke` | Chat से generated artifacts download करना |
| Remote workers | `remote_manage`, `run_shell`, `remote_transfer` | NAT, firewalls या cluster login flows के पीछे machines |

## Typical workflows

### वेब कार्यक्षेत्र में कोडिंग

1. एक एलएसएम नियंत्रक और वैकल्पिक [unified web workspace](getting-started/web-workspace.md) प्रारंभ करें।
2. `/ui` खोलें और LSM पहचान का उपयोग करके साइन इन करें।
3. एक मॉडल समापन बिंदु कॉन्फ़िगर करें और एक नया वार्तालाप खोलें।
4. मॉडल को रिपॉजिटरी का निरीक्षण करने और पहले केवल-पढ़ने के लिए चेक चलाने के लिए कहें।
5. Approval के बाद files patch, tests, diff review, commit और push करने दें।
6. File links या remote systems वाले tasks में audit log review करें।

### Remote HPC या accelerator host

1. One-time remote worker invite बनाएँ।
2. Generated command remote host पर paste करें।
3. Normal tools में `machine` उपयोग करें; Git के लिए `run_shell` और transfer के लिए `remote_transfer`।
4. Task के बाद worker revoke करें।

### Artifact generation

1. AI से `/workspace` के नीचे file generate कराएँ।
2. TTL/download limits वाला tokenized file link बनाएँ।
3. Link chat में share करें।
4. पूरा होने पर revoke करें।

## Language

यह site native MkDocs i18n plugin से build होती है। Header के language selector से English और translated pages के बीच बदलें। बिना translation वाली pages English पर fallback करती हैं।
