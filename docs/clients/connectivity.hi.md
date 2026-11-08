<!-- i18n-source-sha256: 4eb43e1a065d72171aad5493848eb2f8c57361b110237c8816928e28f227a3d8 -->
# नेटवर्क कनेक्टिविटी

मशीन से बाहर स्थित HTTP MCP client को पहुँच योग्य HTTPS origin चाहिए। यह पृष्ठ network routing के बारे में है, runtime चुनने के बारे में नहीं।

client endpoint सामान्यतः `/mcp` पर समाप्त होता है:

```text
https://your-public-host.example.com/mcp
```

Server की public base URL setting में केवल origin होता है:

```env
LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://your-public-host.example.com
```

इस base URL में `/mcp` शामिल न करें।

## कनेक्टिविटी विकल्प

**अनुशंसित:** सार्वजनिक पहुँच के लिए सार्वजनिक सर्वर पर तैनात करें या HTTPS रिवर्स प्रॉक्सी के साथ सार्वजनिक सर्वर से ट्रैफ़िक फ़ॉरवर्ड करें।

**अनुशंसित नहीं:** Cloudflare Tunnel में क्लाइंट-साइड अपलोड बहुत धीमे हो सकते हैं, जिससे फ़ाइल अपलोड और स्थानांतरण का उपयोग कठिन हो जाता है। इसे केवल तभी अपनाएँ जब सार्वजनिक सर्वर या फ़ॉरवर्डिंग उपलब्ध न हो।


| विकल्प | कब उपयोग करें |
|---|---|
| Caddy | सरल automatic TLS |
| Nginx या Nginx Proxy Manager | मौजूदा Nginx infrastructure |
| Traefik | मौजूदा container-native routing |
| सार्वजनिक सर्वर के माध्यम से फ़ॉरवर्डिंग | सार्वजनिक पहुँच के लिए सार्वजनिक सर्वर पर तैनात करें या HTTPS रिवर्स प्रॉक्सी के साथ सार्वजनिक सर्वर से ट्रैफ़िक फ़ॉरवर्ड करें। |
| Cloudflare Tunnel (अनुशंसित नहीं) | सार्वजनिक सर्वर से फ़ॉरवर्ड करें; Cloudflare Tunnel केवल अंतिम विकल्प |

## Paths

पूरे origin को चल रहे server पर forward करें। महत्वपूर्ण paths में शामिल हैं:

| Path | उद्देश्य |
|---|---|
| `/mcp` | MCP Streamable HTTP endpoint |
| `/healthz`, `/readyz` | Health checks |
| `/.well-known/...` | Client discovery metadata |
| `/oauth/...` | Client authorization flow |
| `/downloads/...` | वैकल्पिक generated file links |
| `/join/...`, `/remote/...` | वैकल्पिक remote-worker flow |

## Proxy behavior

Proxy को paths सुरक्षित रखने, request bodies forward करने, लंबे responses support करने और बहुत छोटे timeouts से बचने की आवश्यकता है।

## Checks

```bash
curl -i http://127.0.0.1:8765/healthz
curl -i https://your-public-host.example.com/healthz
```

## सामान्य गलतियाँ

| गलती | सुधार |
|---|---|
| ChatGPT में `https://host/mcp` के बजाय `https://host` उपयोग करना | `/mcp` केवल client endpoint में जोड़ें |
| `LOCAL_SHELL_MCP_PUBLIC_BASE_URL=https://host/mcp` सेट करना | केवल origin सेट करें |
| केवल `/mcp` route करना | पूरे origin को route करें ताकि discovery और authorization paths भी काम करें |
| Host runtime को बहुत व्यापक workspace के साथ चलाना | संकीर्ण workspace या Docker उपयोग करें |

## सुझाए गए संयोजन

| Runtime | Network pattern |
|---|---|
| Server पर Docker Compose | HTTPS रिवर्स प्रॉक्सी |
| Home machine पर Docker Compose | सार्वजनिक सर्वर से फ़ॉरवर्ड करें; Cloudflare Tunnel केवल अंतिम विकल्प |
| Laptop पर VS Code extension | सार्वजनिक सर्वर के माध्यम से फ़ॉरवर्डिंग |
| VM पर binary | VM या network edge पर reverse proxy |
| Python/source dev server | सामान्यतः केवल localhost |
| Stdio mode | कोई HTTP path नहीं; local MCP client उपयोग करें |
