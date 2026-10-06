<!-- i18n-source-sha256: a3fdf9088031e6903b15497a3df881a8e6ed2f6f2b34dd4d0b68b0414a2ca81e -->
# त्वरित शुरुआत

यह गाइड पहले runtime के रूप में Docker Compose और पहले client के रूप में ChatGPT का उपयोग करती है। ये अलग विकल्प हैं: Docker, VS Code extension, binary, Python और stdio runtime विकल्प हैं; ChatGPT और generic MCP clients client विकल्प हैं। पूरी संरचना के लिए [runtime choices और deployment model](../guides/deployment.md) देखें।

## आवश्यकताएँ

- Compose v2 सहित Docker Engine।
- यदि ChatGPT को Web से connect करना है तो public HTTPS endpoint।
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
CLOUDFLARE_TUNNEL_TOKEN=
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

Cloudflare Tunnel sidecar के लिए:

```bash
docker compose --profile tunnel up -d
```

Cloudflare Zero Trust में public hostname को यहाँ point करें:

```text
http://local-shell-mcp:8765
```

Caddy, Nginx, Traefik, Nginx Proxy Manager या किसी अन्य reverse proxy के लिए HTTPS traffic को `127.0.0.1:8765` या container network address पर forward करें।

## 4. ChatGPT connect करें

यह MCP endpoint उपयोग करें:

```text
https://your-public-host.example.com/mcp
```

OAuth और tool approval पूरा करने के लिए [ChatGPT connector guide](chatgpt-connector.md) का पालन करें।

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
| ChatGPT को client के रूप में जोड़ें | [ChatGPT connector](chatgpt-connector.md) |
| tools चुनें और बेहतर prompts लिखें | [Usage patterns](../guides/usage-patterns.md) |
| HPC, NPU/GPU या NAT machine जोड़ें | [Remote workers](../guides/remote-workers.md) |
| सभी MCP tools समझें | [Tools reference](../reference/tools.md) |
