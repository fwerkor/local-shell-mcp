<!-- i18n-source-sha256: cef0a90f9de3e2806e2a6bd8925217ea44ea6d6e6bce911eea09b1d4192a82d9 -->
# Runtime विकल्प और deployment model

`local-shell-mcp` के दो पूरक निर्णय हैं:

1. **Runtime**: server process कैसे चलता है और कौन-सा workspace नियंत्रित करता है।
2. **इंटरफ़ेस**: वैकल्पिक [unified web workspace](../getting-started/web-workspace.md) का उपयोग करें, या जेमिनी या ChatGPT जैसे बाहरी MCP क्लाइंट को कनेक्ट करें।

**Controller के लिए एक executable फ़ाइल अनुशंसित है**, Python, Docker या स्रोत की आवश्यकता नहीं। अन्य विकल्प भी उपलब्ध हैं।

```text
Runtime layer                      Exposure layer                 Client layer
-------------------------------    ---------------------------    ----------------------
डॉकर कंपोज़ स्थानीय HTTP केवल एकीकृत वेब कार्यक्षेत्र
VS Code extension                  HTTPS reverse proxy/tunnel     Generic MCP client
Standalone binary                  stdio process pipe             VS Code extension UI
pipx / source checkout             remote-worker outbound join    REST-style diagnostics
```

एक सामान्य स्व-होस्टेड सेटअप है:

```text
ब्राउज़र -> https://chat.example.com (एकीकृत वेब कार्यक्षेत्र)
        -> प्रमाणित स्थानीय-शेल-एमसीपी नियंत्रक
        -> नियंत्रित कार्यक्षेत्र और आउटबाउंड कर्मचारी
वैकल्पिक बाहरी क्लाइंट -> https://mcp.example.com/mcp
```

Local MCP client setup इससे सरल हो सकता है:

```text
Local MCP client
  -> starts local-shell-mcp --mode stdio
  -> controlled workspace
```

**अनुशंसित:** सार्वजनिक पहुँच के लिए सार्वजनिक सर्वर पर तैनात करें या HTTPS रिवर्स प्रॉक्सी के साथ सार्वजनिक सर्वर से ट्रैफ़िक फ़ॉरवर्ड करें। **अनुशंसित नहीं:** Cloudflare Tunnel में क्लाइंट-साइड अपलोड बहुत धीमे हो सकते हैं, जिससे फ़ाइल अपलोड और स्थानांतरण का उपयोग कठिन हो जाता है। इसे केवल तभी अपनाएँ जब सार्वजनिक सर्वर या फ़ॉरवर्डिंग उपलब्ध न हो। ([Public HTTPS exposure](../clients/connectivity.md))

## Runtime choice matrix

| रनटाइम | के लिए सर्वोत्तम | अलगाव सीमा | टूलचेन स्रोत | बाहरी एमसीपी पहुंच | पेज |
|---|---|---|---|---|---|
| **एकल executable (अनुशंसित)** | अधिकांश समर्थित सिस्टम | Host or VM | Host tools और configured executable | HTTPS proxy या tunnel जोड़ें | [Standalone binary](../installation/binary.md) |
| डॉकर कम्पोज़ | अलग, अस्थायी कंटेनर | कंटेनर | लीन नियंत्रक छवि; कार्य-विशिष्ट टूलचेन अलग से स्थापित करें | HTTPS प्रॉक्सी या टनल जोड़ें | [Docker Compose](../installation/docker.md) |
| डॉकर कंपोज़ + टनल साइडकार | अनुशंसित नहीं: सार्वजनिक सर्वर से फ़ॉरवर्ड करें; Cloudflare Tunnel केवल अंतिम विकल्प | कंटेनर | प्रोजेक्ट छवि | सार्वजनिक सर्वर से फ़ॉरवर्ड करें; Cloudflare Tunnel केवल अंतिम विकल्प | [Docker Compose](../installation/docker.md#cloudflare-tunnel-sidecar) |
| VS Code extension | Editor workspace से server start/stop | आमतौर पर host process | Host tools और configured executable | ChatGPT के लिए external HTTPS tunnel/proxy जोड़ें | [VS Code extension](../installation/vscode-extension.md) |
| स्रोत / pipx | विकास और अनुकूलन | Host virtualenv or VM | Python package और host tools | HTTPS proxy या tunnel जोड़ें | [Python install](../installation/python.md) |
| Stdio mode | Local MCP clients जो process सीधे spawn करते हैं | Client process boundary | Host tools और configured executable | ChatGPT web/app में उपयोग नहीं | [Stdio mode](../installation/stdio.md) |

## Client connection matrix

| इंटरफ़ेस | सार्वजनिक HTTPS की आवश्यकता है | `/mcp` का उपयोग करता है | OAuth की आवश्यकता है | विशिष्ट रनटाइम |
|---|---:|---:|---:|---|
| एकीकृत एलएसएम वेब कार्यक्षेत्र | दूरस्थ पहुँच के लिए हाँ; स्थानीय प्रॉक्सी भी संभव है | आंतरिक रूप से | एलएसएम लॉगिन | नियंत्रक प्लस अलग वेब स्टैक |
| जेमिनी स्पार्क/कस्टम ऐप्स | हाँ | हाँ | हाँ सार्वजनिक उपयोग के लिए | कोई HTTP नियंत्रक |
| ChatGPT custom MCP connector | हाँ | हाँ | Public use में हाँ | Docker, VS Code extension, binary, or Python |
| Generic local MCP client over stdio | नहीं | नहीं | नहीं | `local-shell-mcp --mode stdio` |
| Generic HTTP MCP client | localhost पर आमतौर पर नहीं; network पर हाँ | हाँ | localhost के बाहर अनुशंसित | Any HTTP runtime |
| VS Code extension helper flow | केवल जब ChatGPT connect करना हो | ChatGPT URL copy करते समय हाँ | ChatGPT के लिए अनुशंसित | VS Code-launched runtime |

[unified web workspace](../getting-started/web-workspace.md), [Gemini Spark](../getting-started/gemini-spark.md), [ChatGPT connector](../getting-started/chatgpt-connector.md), [generic MCP clients](../clients/generic-mcp.md), और [network connectivity](../clients/connectivity.md) देखें।

## हर runtime क्या नियंत्रित करता है

हर runtime वही server code चलाता है और enabled होने पर वही MCP tool families expose करता है:

- Shell और persistent shell sessions।
- Filesystem, search और patch tools।
- Git operations।
- Playwright से browser automation।
- Audit log और task-state tools।
- Tokenized file links।
- Optional remote-worker lifecycle और machine-routed tools।

फर्क abstract API में नहीं, उसके पीछे के **operating environment** में है।

| प्रश्न | Docker Compose | VS Code extension | Binary / Python |
|---|---|---|---|
| Commands कहाँ चलते हैं? | Container के अंदर | आमतौर पर host workspace पर | Host या VM process environment में |
| Default workspace? | Mounted `/workspace` | Current VS Code folder या configured path | `LOCAL_SHELL_MCP_WORKSPACE_ROOT` |
| क्या कंपाइलर और ब्राउज़र पहले से इंस्टॉल हैं? | नहीं; कार्य को जो चाहिए उसे स्थापित करें | केवल यदि होस्ट पर स्थापित है | केवल यदि होस्ट पर स्थापित है |
| Reset आसान? | Container और workspace volume फिर बनाएँ | Workspace पर निर्भर | Host/VM पर निर्भर |
| Arbitrary package installs के लिए ठीक? | हाँ, यदि disposable | Host पर अधिक जोखिम | VM के बाहर अधिक जोखिम |

## अनुशंसित चयन

**एकल executable चुनें**: सही प्लेटफ़ॉर्म का संस्करण डाउनलोड कर सीमित खाते व अलग workspace में चलाएँ। [बाइनरी गाइड](../installation/binary.md)।

जब वर्कफ़्लो एक संपादक से शुरू होता है और आप एक स्थानीय लॉन्चर चाहते हैं तो **वीएस कोड एक्सटेंशन** का उपयोग करें। यह अभी भी एक रनटाइम है. दूरस्थ वेब क्लाइंट को पहुंच योग्य HTTPS प्रॉक्सी या सुरंग की आवश्यकता होती है।

**स्रोत इंस्टॉल** Python वातावरण में विकास, डिबगिंग और बदलाव के लिए है। [Python गाइड](../installation/python.md)।

`local-shell-mcp` के development/debugging या आसान Python-based environment management के लिए **`pipx` या source install** उपयोग करें।

केवल ऐसे local MCP clients के लिए **stdio mode** उपयोग करें जो server process spawn कर सकें। यह public deployment नहीं है और ChatGPT web/app से सीधे उपयोग नहीं होता।

## Public endpoint नियम

जेमिनी और चैटजीपीटी जैसे बाहरी HTTP MCP क्लाइंट के लिए, MCP समापन बिंदु है:

```text
https://your-public-host.example.com/mcp
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` केवल origin है:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

`LOCAL_SHELL_MCP_PUBLIC_BASE_URL` में `/mcp` न जोड़ें।

## Runtime pages

- [Docker Compose](../installation/docker.md)
- [VS Code extension](../installation/vscode-extension.md)
- [Standalone binary](../installation/binary.md)
- [Python, `pipx`, and source install](../installation/python.md)
- [Stdio mode](../installation/stdio.md)

## Client pages

- [Unified web workspace](../getting-started/web-workspace.md)
- [Gemini Spark / Custom Apps](../getting-started/gemini-spark.md)
- [ChatGPT connector](../getting-started/chatgpt-connector.md)
- [Generic MCP clients](../clients/generic-mcp.md)
- [Public HTTPS exposure](../clients/connectivity.md)
