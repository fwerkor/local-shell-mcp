<!-- i18n-source-sha256: 3575b9b50708261678473f74b66076f0c14807ccd7f7c3e60b4d1e897ac778df -->
# त्वरित शुरुआत

यह मार्गदर्शिका एक एलएसएम नियंत्रक प्रारंभ करती है और उसका ब्राउज़र इंटरफ़ेस खोलती है। [unified web workspace](web-workspace.md) अनुशंसित दैनिक अनुभव है; यह एक अलग से तैनात, वैकल्पिक चैट स्टैक है। चैटजीपीटी, जेमिनी और अन्य बाहरी एमसीपी क्लाइंट एक ही नियंत्रक से जुड़ सकते हैं। [runtime choices and deployment model](../guides/deployment.md) देखें.

अलग वातावरण में **सीधे स्रोत कोड से डिप्लॉय करना** अनुशंसित है। Docker Compose वैकल्पिक है।

## आवश्यकताएँ

- Git और Python 3.11+ के साथ `venv` तथा `pip`.
- बाहरी MCP क्लाइंट या दूरस्थ उपयोगकर्ताओं के लिए ही सार्वजनिक HTTPS.
- सीमित अधिकारों वाली अलग workspace डायरेक्टरी.
- मजबूत OAuth admin PIN और यादृच्छिक JWT secret.

!!! warning
    Connected model configured workspace पर काम कर सकता है। Service को disposable container या VM में चलाएँ और host-control resources mount न करें।

## 1. Clone और configure करें

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
```

`.env` में नमूना PIN और JWT secret बदलें (`openssl rand -hex 32` का उपयोग करें)। स्रोत से चलाने पर `.env` स्वतः लोड नहीं होता।

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Server शुरू करें

```bash
mkdir -p workspaces/default
set -a
. ./.env
set +a
. .venv/bin/activate
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

दूसरे टर्मिनल से स्थिति जाँचें:

```bash
curl -i http://127.0.0.1:8765/healthz
```

सही उत्तर HTTP `200` है। लंबे समय तक चलाने के लिए सर्विस मैनेजर का उपयोग करें।

## 3. HTTPS expose करें

दूरस्थ पहुँच के लिए सार्वजनिक सर्वर या HTTPS रिवर्स प्रॉक्सी (Caddy, Nginx, Traefik) प्रयोग करें। अपलोड/डाउनलोड सहित पूरे साइट को यहाँ अग्रेषित करें:

```text
http://127.0.0.1:8765
```

HTTPS जाँचें:

```bash
curl -i https://your-public-host.example.com/healthz
```

फ़ाइल ट्रांसफ़र के लिए **Cloudflare Tunnel अनुशंसित नहीं है**: क्लाइंट अपलोड धीमे हो सकते हैं। सार्वजनिक सर्वर या सामान्य प्रॉक्सी/पोर्ट फ़ॉरवर्डिंग को प्राथमिकता दें और OAuth चालू रखें। विकल्प: [Docker](../installation/docker.md).

## 4. ब्राउज़र कार्यक्षेत्र खोलें

नियंत्रक लॉगिन खोलें:

```text
https://your-public-host.example.com/ui
```

चैट, प्रोजेक्ट और एकीकृत नियंत्रण पृष्ठों के लिए, [unified web workspace guide](web-workspace.md) का पालन करें। चैट इंस्टॉल न होने पर मूल हल्का वेबयूआई उपलब्ध होता है।

## 5. Tool access सुरक्षित रूप से जाँचें

Model से कहें:

```text
local-shell-mcp का उपयोग करें। पहले environment_get कॉल करें, फिर workspace root सूचीबद्ध करें। अभी files संशोधित न करें।
```

अपेक्षित read-only tools:

- `environment_get`
- `file_list`
- `file_tree`
- `file_read`

## 6. सीमित coding task से शुरू करें

एक अच्छा पहला task:

```text
इस repository का निरीक्षण करें, project layout का सार दें, यदि मौजूदा test suite स्पष्ट हो तो उसे चलाएँ, और files न बदलें।
```

Connectivity की पुष्टि के बाद अधिक विशिष्ट निर्देश दें:

```text
Failing test ठीक करें। पहले संबंधित files पढ़ें, सबसे छोटा patch बनाएँ, targeted test चलाएँ, फिर git diff दिखाएँ। मेरी स्वीकृति से पहले commit न करें।
```

## अपडेट

स्रोत अपडेट करें, editable पैकेज पुनः इंस्टॉल करें और Controller पुनः शुरू करें:

```bash
git pull --ff-only
python -m pip install -e .
# Restart the Controller process or service after updating.
curl -i http://127.0.0.1:8765/healthz
```

Docker Compose होने पर कंटेनर अपडेट करें:

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

## अगले पेज

| ज़रूरत | पेज |
|---|---|
| runtime और client विकल्प समझें | [Runtime choices और deployment model](../guides/deployment.md) |
| Docker Compose से चलाएँ | [Docker Compose runtime](../installation/docker.md) |
| VS Code से चलाएँ | [VS Code extension runtime](../installation/vscode-extension.md) |
| release binary से चलाएँ | [Standalone binary runtime](../installation/binary.md) |
| Python या source checkout से चलाएँ | [Python runtimes](../installation/python.md) |
| एकीकृत चैट और नियंत्रण इंटरफ़ेस का उपयोग करें | [Unified web workspace](web-workspace.md) |
| जेमिनी स्पार्क को ग्राहक के रूप में जोड़ें | [Gemini Custom Apps](gemini-spark.md) |
| ChatGPT को client के रूप में जोड़ें | [ChatGPT connector](chatgpt-connector.md) |
| tools चुनें और बेहतर prompts लिखें | [Usage patterns](../guides/usage-patterns.md) |
| HPC, NPU/GPU या NAT machine जोड़ें | [Remote workers](../guides/remote-workers.md) |
| सभी MCP tools समझें | [Tools reference](../reference/tools.md) |
