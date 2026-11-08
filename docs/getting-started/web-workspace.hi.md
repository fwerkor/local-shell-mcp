<!-- i18n-source-sha256: 521e0f39c8823597b1468b2d63af978794cb28fda8c8e60230da0a96cff2d5c2 -->
# एकीकृत वेब कार्यक्षेत्र

**एकीकृत एलएसएम वेब कार्यक्षेत्र** लोकल-शेल-एमसीपी को दिन-प्रतिदिन उपयोग करने का अनुशंसित तरीका है। यह एआई चैट, प्रोजेक्ट इतिहास और एलएसएम नियंत्रण विमान को एक संशोधित, विक्रेताबद्ध लिब्रेचैट फ्रंटएंड के आधार पर एक प्रतिक्रियाशील इंटरफ़ेस में जोड़ता है। आप अभी भी बाहरी MCP क्लाइंट जैसे [ChatGPT](chatgpt-connector.md) या [Gemini](gemini-spark.md) कनेक्ट कर सकते हैं।

कार्यक्षेत्र **स्वयं-होस्टेड है और इंस्टॉल करने के लिए वैकल्पिक** है: यह एक अलग वेब सेवा है, न्यूनतम नियंत्रक छवि, स्टैंडअलोन निष्पादन योग्य या रिमोट वर्कर बंडल का हिस्सा नहीं है। केवल-नियंत्रक परिनियोजन मूल ब्राउज़र UI और OpenTUI को बनाए रखते हैं।

## कार्यक्षेत्र में क्या है?

| क्षेत्र | आप क्या कर सकते हैं |
|---|---|
| चैट और प्रोजेक्ट | एक कॉन्फ़िगर किया गया मॉडल चुनें, वार्तालाप बनाएं, प्रोजेक्ट व्यवस्थित करें, पिछली चैट ढूंढें और वार्तालाप संग्रहीत करें। इतिहास सर्वर पर रहता है. |
| नियंत्रक सिंहावलोकन | स्वास्थ्य, हाल की गतिविधि और कनेक्टेड मशीनें देखें। |
| फ़ाइलें | स्थानीय या दूरस्थ फ़ाइलें ब्राउज़ करें और प्रबंधित करें। |
| टर्मिनल | नियंत्रक या श्रमिकों पर लगातार टर्मिनलों के साथ कार्य करें। |
| डेस्कटॉप | दूरस्थ जीयूआई सत्रों का निरीक्षण और नियंत्रण करें। |
| सत्र | टिकाऊ एलएसएम कार्यों और उनके जीवनचक्र का निरीक्षण करें। |
| रिमोट | आउटबाउंड श्रमिकों से जुड़ें और प्रशासन करें। |
| लेखापरीक्षा | मॉडल-उत्पन्न उपकरण गतिविधि का निरीक्षण करें। |
| नेस्टेड एम.सी.पी | एलएसएम के पीछे बाहरी एमसीपी सर्वर को पंजीकृत करें, संपादित करें, सक्षम करें, अक्षम करें, रीफ्रेश करें और हटाएं। |

नियंत्रक मार्ग `/control/overview`, `/control/files`, `/control/terminals`, `/control/desktop`, `/control/sessions`, `/control/remotes` और `/control/audit` हैं। चैट `/c/new` पर खुलती है। एलएसएम एमसीपी प्रबंधक **एलएसएम की नेस्टेड एमसीपी रजिस्ट्री** को नियंत्रित करता है; यह लिब्रेचैट में दूसरी रजिस्ट्री नहीं बनाता है।

## वैकल्पिक चैट स्टैक तैनात करें

1. [Install and start an LSM Controller](quickstart.md) with SQLite (now the default). On startup, durable historical state is imported automatically, retaining the original files for rollback.
2. Configure one HTTP/HTTPS Controller origin, for example `https://lsm.example.org`. Chat, terminals, files and remote controls share the same Python server and authentication.
3. To override the defaults, configure the Controller service environment:

```env
LOCAL_SHELL_MCP_STATE_BACKEND=sqlite
LOCAL_SHELL_MCP_UI_ENABLED=true
```

4. Start the Controller from its Python package or standalone executable:

```sh
local-shell-mcp --mode mcp
```

5. The original React client is maintained in `ui/workspace/`. Bun is only required for building and releases; consult the [first-party WebUI build and security notes](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md).

Node.js, MongoDB, Meilisearch and the separate LibreChat Compose stack are no longer required at runtime. Workers remain ordinary Python packages.

**Migration status:** The Python Agent generation engine, SSE resume and tool approvals are still being ported. Do not deploy the draft branch as a replacement for a working production Controller.

## साइन इन करें और चैट का उपयोग करें

1. Open the LSM Controller `/ui` entrypoint and authenticate with its existing PIN or OAuth credentials. React and Controller APIs share this identity.
2. Configure an available model endpoint/API credential in LSM. The Python Agent provider engine is being migrated; the draft branch does not yet provide complete generation support.
3. Start a conversation after the Python Agent endpoints and SSE protocol pass the acceptance suite. Nested MCP, LSM tools and file uploads follow existing Controller permissions.
4. Start with a read-only request: “Check Controller status and list the workspace root. Do not modify files.”
5. Navigate to **Files**, **Terminals**, **Desktop**, **Sessions**, **Remotes** or **Audit** for direct inspection and control.

चैट अपलोड (32 एमआईबी तक) नियंत्रक कार्यक्षेत्र के अंतर्गत संग्रहीत किए जाते हैं और उनके पूर्ण पथ मॉडल को आपूर्ति किए जाते हैं। ब्राउज़र अपलोड अतिरिक्त फ़ाइल अनुमतियाँ नहीं देते हैं. मॉडल-फ़ेसिंग टूल कॉल एलएसएम प्राधिकरण, ऑडिट और रिमोट-वर्कर राउटर से होकर गुजरती हैं।

## बाहरी एमसीपी, सुरक्षा और डेटा

नेस्टेड बाहरी MCP सर्वर को प्रबंधित करने के लिए कार्यस्थान MCP साइडबार का उपयोग करें। यह स्थानीय stdio सर्वर और HTTP सर्वर का समर्थन करता है, जिसमें अलग-अलग निजी वातावरण चर और अनुरोध हेडर शामिल हैं। रहस्य ब्राउज़र पर वापस नहीं आते. **बाहरी एमसीपी** चैट टॉगल नेस्टेड टूल की खोज, निरीक्षण और आह्वान की अनुमति देता है; जब मूल एलएसएम उपकरण अक्षम हो जाते हैं तो यह मॉडल `mcp_manage` प्रदान नहीं करता है। यूआई प्रबंधन सामान्य नियंत्रक प्राधिकरण द्वारा संरक्षित है।

Chats, projects, Agents, sessions, audits and Worker metadata share `.local-shell-mcp/lsm.sqlite3`; SQLite FTS5 provides local search. Non-database artifacts remain under `.local-shell-mcp/`.

यूआई एक शीर्ष-स्तरीय ऐप है, **आईफ्रेम नहीं**। यदि वैकल्पिक चैट सेवा कॉन्फ़िगर नहीं की गई है, तो `/ui` मूल LSM WebUI की सेवा जारी रखता है। मूल OpenTUI और बाहरी क्लाइंट समर्थित रहते हैं।

## समस्या निवारण

- **Unable to start the WebUI:** check the Controller Python logs, SQLite initialization and bundled frontend archive. `LOCAL_SHELL_MCP_STATE_BACKEND=file` is an emergency storage recovery option.
- **Authentication fails:** use the existing Controller PIN/OAuth login. The React UI does not require a separate LibreChat account or bridge secret.
- **Chat loads but cannot answer:** the Python Agent generation and SSE port is still incomplete in this draft branch; do not deploy it to production.
- **Missing MCP tools:** check Controller authorization and the nested MCP registry; never expose `mcp_manage` to external-only model tools.
- **Files or sessions appear empty:** verify the Controller workspace, SQLite migration and authorized principal in its logs.

कार्यान्वयन विवरण और अपडेट के लिए, [the vendored integration README](https://github.com/fwerkor/local-shell-mcp/blob/main/ui/workspace/README.md) और [human interface guide](../guides/human-interface.md) देखें।
