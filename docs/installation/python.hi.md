<!-- i18n-source-sha256: 1d80cfbe14747fb0691e91065f582d1e47eb36921d8b27da1648dcd26114a2e5 -->
# Python, pipx और source runtimes

सामान्य डिप्लॉयमेंट के लिए [एकल executable](binary.md) अनुशंसित है। Python और स्रोत संस्करण विकास व अनुकूलन के लिए हैं।

यह page तीन संबंधित cases के लिए है:

- `pipx install local-shell-mcp`: user-level executable install.
- `pip install local-shell-mcp`: existing virtual environment में install.
- Editable source checkout: project को स्वयं develop या debug करना।

## pipx install

सामान्य users के लिए `pipx` सबसे साफ Python-based install है क्योंकि command को अपना virtual environment मिलता है और executable `PATH` पर उपलब्ध रहता है।

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

Local HTTP MCP server शुरू करें:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

Health check करें:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Virtual environment install

जब आप Python environments स्वयं manage करते हों तब उपयोग करें:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

Process host पर installed tools उपयोग करता है। Python package आपके लिए compilers, Git, browser system dependencies या project dependencies install नहीं करता।

## Editable source checkout

स्रोत इंस्टॉल विकास के लिए है; सामान्य उपयोग में [बाइनरी](binary.md) चुनें। OAuth/HTTPS: [त्वरित शुरू](../getting-started/quickstart.md)।

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

Checks चलाएँ:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## Browser setup

Playwright वैकल्पिक है; जरूरत पड़ने पर लाइब्रेरी और ब्राउज़र इंस्टॉल करें।

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

ब्राउज़र इंस्टॉलेशन वैकल्पिक है; Docker की मूल इमेज में Playwright या ब्राउज़र शामिल नहीं हैं।

## Public HTTP MCP use

ChatGPT या किसी अन्य public HTTP MCP client के लिए वही public-origin और OAuth settings configure करें जो अन्य HTTP runtimes में हैं, फिर local port को reverse proxy या tunnel से expose करें।

Public MCP endpoint:

```text
https://your-public-host.example.com/mcp
```

## Development modes

| Mode | Command | उपयोग |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | HTTP पर full MCP clients, HTTPS के पीछे ChatGPT सहित |
| REST-style HTTP | `local-shell-mcp --mode http` | Diagnostic या compatibility endpoints, मुख्य ChatGPT path नहीं |
| stdio | `local-shell-mcp --mode stdio` | Local MCP clients जो process spawn करते हैं |

`mode=both` reserved है और अभी single process mode के रूप में उपयोग नहीं किया जाना चाहिए।

## Host-runtime safety

Python installs host user के रूप में चलती हैं जब तक उन्हें VM/container में न रखा जाए। Workspace narrow रखें, full-container mode disabled रखें और workspace को home directory पर point न करें।

Untrusted repositories, package-manager-heavy tasks या ऐसे workflows जहाँ resetability host integration से अधिक महत्वपूर्ण है, उनके लिए Docker Compose उपयोग करें।
