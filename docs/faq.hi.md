# अक्सर पूछे जाने वाले प्रश्न

यह पृष्ठ उन बार-बार आने वाली Client और reverse proxy समस्याओं को समझाता है जो सर्वर के स्वस्थ होने पर भी LSM की विफलता जैसी दिख सकती हैं।

## LSM अपग्रेड करने के बाद ChatGPT में कुछ टूल उपलब्ध क्यों नहीं हैं?

### लक्षण

- नए टूल ChatGPT में दिखाई नहीं देते।
- ChatGPT हटाए गए, बदले गए नाम वाले या मिलाए गए पुराने टूल को कॉल करता रहता है।
- टूल मौजूद है, लेकिन ChatGPT पुराना input schema भेजता है और validation विफल हो जाता है।
- LSM को पुनः आरंभ करने या नई बातचीत खोलने से समस्या ठीक नहीं होती।

### कारण

ChatGPT उस समय उपलब्ध टूल और input schemas का frozen snapshot रख सकता है जब MCP App को scan, approve या publish किया गया था। LSM रिलीज़ में `tools/list` बदलने पर उस snapshot के अपने आप refresh होने की गारंटी नहीं है। यह documented expiry वाला अल्पकालिक cache नहीं है।

### समाधान

=== "Developer mode या व्यक्तिगत connection"

    1. **ChatGPT Settings → Apps** खोलें।
    2. LSM App खोलें और **Refresh** से टूल दोबारा scan करें।
    3. Refresh उपलब्ध न हो तो पुरानी App हटाएँ और वही MCP endpoint फिर जोड़ें।
    4. नई टूल सूची स्वीकार करने के बाद नई बातचीत शुरू करें।

=== "ChatGPT Business में प्रकाशित App"

    वर्तमान में प्रकाशित custom App अपने टूल या metadata को वहीं अपडेट नहीं कर सकती। Workspace administrator को नई App बनानी होगी, वर्तमान LSM endpoint scan करना होगा, replacement publish करना होगा और पुरानी App हटानी होगी।

=== "ChatGPT Enterprise या Edu"

    Administrator **Workspace Settings → Apps → LSM App → … → Action control → Refresh** खोलकर अंतर देख सकता है और आवश्यकता होने पर नई actions सक्षम कर सकता है।

[Issue #70](https://github.com/fwerkor/local-shell-mcp/issues/70) और [OpenAI MCP App documentation](https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt) देखें।

## Nginx के पीछे WebUI बार-बार reconnect क्यों होती है?

### लक्षण

- WebUI पृष्ठ और OAuth login सामान्य रूप से खुलते हैं।
- TUI दिखाई नहीं देती।
- स्थिति `Connecting`, `Connection error` और `Reconnecting` के बीच घूमती रहती है।
- पोर्ट `8765` से सीधा connection काम करता है।

### कारण

Browser UI, PTY WebSocket के माध्यम से native TUI render करती है। Default endpoint `/ui/ws` है; custom `ui_path` के साथ यह `${ui_path}/ws` होता है। सामान्य Nginx `proxy_pass`, WebSocket upgrade के लिए जरूरी hop-by-hop headers अपने आप forward नहीं करता।

### समाधान

HTTP/1.1 सक्षम करें और `Upgrade` तथा `Connection` headers forward करें:

```nginx
# map को http block में रखें।
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      close;
}

server {
    listen 443 ssl;
    server_name lsm.example.com;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_buffering off;
    }
}
```

Configuration जाँचकर Nginx reload करें:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

Nginx Proxy Manager में Proxy Host के लिए **Websockets Support** सक्षम करें। Reconnect जारी रहे तो Advanced configuration में समान upgrade headers जोड़ें।

### जाँच

Browser developer tools खोलें, WebUI reload करें और `/ui/ws` request देखें। सही connection यह लौटाती है:

```text
101 Switching Protocols
```

[Issue #71](https://github.com/fwerkor/local-shell-mcp/issues/71) देखें।
