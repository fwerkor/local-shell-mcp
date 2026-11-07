<!-- i18n-source-sha256: a9820f08198cf8e823f59550928c07346f9669f2dbec46d3b8cd523c34034e01 -->
# त्वरित शुरुआत

यह मार्गदर्शिका एक एलएसएम नियंत्रक प्रारंभ करती है और उसका ब्राउज़र इंटरफ़ेस खोलती है। [unified web workspace](web-workspace.md) अनुशंसित दैनिक अनुभव है; यह एक अलग से तैनात, वैकल्पिक चैट स्टैक है। चैटजीपीटी, जेमिनी और अन्य बाहरी एमसीपी क्लाइंट एक ही नियंत्रक से जुड़ सकते हैं। [runtime choices and deployment model](../guides/deployment.md) देखें.

## आवश्यकताएँ

- Compose v2 सहित Docker Engine।
- यदि दूरस्थ उपयोगकर्ताओं या बाहरी MCP क्लाइंट को कनेक्ट होना चाहिए तो एक सार्वजनिक HTTPS एंडपॉइंट।
- एक dedicated workspace directory।
- लंबा random OAuth admin PIN और JWT secret।

!!! warning
    Connected model configured workspace पर काम कर सकता है। Service को disposable container या VM में चलाएँ और host-control resources mount न करें।

## 1. Clone और configure करें

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
cp .env.example .env
python scripts/init_compose_env.py
```

`.env` संपादित करें:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
LOCAL_SHELL_MCP_AUTH_MODE=oauth
LOCAL_SHELL_MCP_OAUTH_ADMIN_PIN=change-me-long-random-pin
LOCAL_SHELL_MCP_OAUTH_JWT_SECRET=change-me-64-hex-random-secret
```

## 2. Server शुरू करें

```bash
mkdir -p workspaces/default
docker compose up -d
```

Status जाँचें:

```bash
docker compose ps
docker compose logs --tail=100 local-shell-mcp
curl -i http://127.0.0.1:8765/healthz
```

स्वस्थ response HTTP `200` लौटाता है।

## 3. HTTPS expose करें

**अनुशंसित:** सार्वजनिक पहुँच के लिए सार्वजनिक सर्वर पर तैनात करें या HTTPS रिवर्स प्रॉक्सी के साथ सार्वजनिक सर्वर से ट्रैफ़िक फ़ॉरवर्ड करें।

**अनुशंसित नहीं:** Cloudflare Tunnel में क्लाइंट-साइड अपलोड बहुत धीमे हो सकते हैं, जिससे फ़ाइल अपलोड और स्थानांतरण का उपयोग कठिन हो जाता है। इसे केवल तभी अपनाएँ जब सार्वजनिक सर्वर या फ़ॉरवर्डिंग उपलब्ध न हो। Configure `CLOUDFLARE_TUNNEL_TOKEN` in `.env` only when choosing the optional tunnel sidecar.

Cloudflare Tunnel sidecar के लिए:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust में public hostname को यहाँ point करें:

```text
http://local-shell-mcp:8765
```

Caddy, Nginx, Traefik, Nginx Proxy Manager या किसी अन्य reverse proxy के लिए HTTPS traffic को `127.0.0.1:8765` या container network address पर forward करें।

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

```bash
docker compose pull
docker compose up -d
curl -i http://127.0.0.1:8765/healthz
```

यदि tunnel profile उपयोग करते हैं:

```bash
docker compose --profile tunnel pull
docker compose --profile tunnel up -d
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
