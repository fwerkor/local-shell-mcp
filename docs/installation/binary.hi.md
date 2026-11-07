<!-- i18n-source-sha256: ed47d5e0691f17af5cd4758981c31957e299202bf72433b34b4656346312091e -->
# Standalone binary runtime

GitHub Releases से **Controller की एकल executable फ़ाइल** उपयोग करना अनुशंसित है। Python, Docker या source checkout की जरूरत नहीं।

यह runtime choice है। ChatGPT access अलग से HTTPS `/mcp` endpoint के माध्यम से configure होता है।

## Release artifacts

GitHub Releases सामान्य platforms के लिए self-contained executables build करता है:

| Platform artifact | Archive |
|---|---|
| `local-shell-mcp-linux-x86_64` | `.tar.gz` |
| `local-shell-mcp-linux-aarch64` | `.tar.gz` |
| `local-shell-mcp-macos-x86_64` | `.tar.gz` |
| `local-shell-mcp-macos-aarch64` | `.tar.gz` |
| `local-shell-mcp-windows-x86_64` | `.zip` |

हर archive में executable, README, license और छोटा quickstart file होता है।

**एकल executable फ़ाइल** भी सीधे उपलब्ध है। इसमें केवल Controller और मूल WebUI हैं; चैट, डेटाबेस, Worker, टूल्स और ब्राउज़र अलग से स्थापित होते हैं।

## Install

1. अपने प्लेटफ़ॉर्म की फ़ाइल या आर्काइव [GitHub Releases](https://github.com/fwerkor/local-shell-mcp/releases/latest) से डाउनलोड करें।
2. आर्काइव होने पर उसे निकालें।
3. Executable को `PATH` पर रखें या उसका absolute path लिख लें।
4. `local-shell-mcp --help` चलाकर binary start होने की पुष्टि करें।

उदाहरण: Linux x86_64 की फ़ाइल सीधे डाउनलोड करें; अन्य प्लेटफ़ॉर्म पर उपयुक्त रिलीज़ चुनें:

```bash
mkdir -p ~/lsm && cd ~/lsm
curl -fL https://github.com/fwerkor/local-shell-mcp/releases/latest/download/local-shell-mcp-linux-x86_64 -o local-shell-mcp
chmod +x local-shell-mcp
./local-shell-mcp --help
```

Windows users PowerShell से `local-shell-mcp.exe` चलाएँ या containing directory को `PATH` में configure करें।

## Minimal local run

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
~/lsm/local-shell-mcp --mode mcp
```

दूसरे terminal में:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## Public HTTP MCP run

ChatGPT या public HTTP MCP client के लिए ये configuration categories सेट करें:

| Setting | Purpose |
|---|---|
| `LOCAL_SHELL_MCP_WORKSPACE_ROOT` | Tools द्वारा controlled directory |
| `LOCAL_SHELL_MCP_HOST` and `LOCAL_SHELL_MCP_PORT` | Local bind address और port |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL` | `/mcp` के बिना public HTTPS origin |
| `LOCAL_SHELL_MCP_AUTH_MODE` | Public deployments में `oauth` उपयोग करें |
| OAuth PIN and JWT secret settings | Public OAuth authorization के लिए आवश्यक |

Local HTTP port को reverse proxy या tunnel से expose करें। Public endpoint:

```text
https://your-public-host.example.com/mcp
```

## YAML config

YAML config non-secret runtime defaults रख सकता है:

```yaml
host: 127.0.0.1
port: 8765
mode: mcp
workspace_root: /srv/local-shell-mcp/workspace
auth_mode: oauth
public_base_url: https://your-public-host.example.com
```

Run:

```bash
local-shell-mcp --config /path/to/config.yaml
```

`LOCAL_SHELL_MCP_` prefix वाले environment variables YAML values override करते हैं।

## Host toolchain responsibility

Binary Python application package करता है, हर developer tool नहीं। MCP tools host पर available programs call करते हैं।

अपनी tasks के लिए आवश्यक packages install करें:

| Capability | Host packages to consider |
|---|---|
| Search and shell ergonomics | `ripgrep`, `tree`, `jq`, `curl`, `wget`; Linux releases में static tmux helper पहले से शामिल है |
| Git workflows | `git`, `gh`, OpenSSH client, credential helpers |
| Python projects | Python, pip, venv, project-specific compilers and headers |
| Node projects | Node.js, npm, pnpm, yarn |
| Rust/Go/Java/C++ | Cargo/rustc, Go, JDK, Maven/Gradle, compilers, CMake, Ninja |
| Browser automation | Playwright browser binaries and OS dependencies |
| Document conversion | LibreOffice, Pandoc, Poppler utilities |

बाइनरी में Controller शामिल है; बाहरी टूल और ब्राउज़र वैकल्पिक हैं। चैट और हिस्ट्री के लिए अलग [वेब वर्कस्पेस](../getting-started/web-workspace.md) और डेटाबेस चाहिए।

## Long-running service

Persistent public deployment के लिए binary को OS process supervisor के नीचे चलाएँ। ये practices रखें:

- Dedicated low-privilege OS account उपयोग करें।
- Dedicated workspace directory उपयोग करें।
- Sensitive values को world-readable files से बाहर रखें।
- Failure पर automatically restart करें।
- हर restart के बाद `/healthz` check करें।
- Troubleshooting के लिए logs उपलब्ध रखें।

## Updates

1. नया executable बदलें और Controller पुनः शुरू करें:
2. चाहें तो checksums verify करें।
3. Executable replace करें।
4. Process manager restart करें।
5. `/healthz` check करें।
6. काम जारी रखने से पहले client से `environment_get` चलवाएँ।

## Safety notes

Binary अपने operating-system user के privileges से चलता है। Public deployments के लिए dedicated low-privilege user, dedicated workspace और जहाँ संभव हो VM/container boundary उपयोग करें।

अपने personal host पर सीधे चल रहे binary के लिए `LOCAL_SHELL_MCP_ALLOW_FULL_CONTAINER=true` सेट न करें। यह setting disposable containers या VMs के लिए है।
