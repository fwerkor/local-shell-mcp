# Docker Compose

यह पृष्ठ “Docker Compose” परिदृश्य समझाता है और साइट की समान Runtime/Client संरचना का पालन करता है।

## सारांश

Runtime यह तय करता है कि सर्वर प्रक्रिया कैसे चलेगी और कौन-सा workspace नियंत्रित होगा। Client यह तय करता है कि ChatGPT या कोई अन्य MCP क्लाइंट कैसे जुड़ेगा। Docker, VS Code एक्सटेंशन, स्वतंत्र बाइनरी, Python/pipx/source स्थापना और stdio Runtime विकल्प हैं; ChatGPT कनेक्टर, सामान्य HTTP MCP क्लाइंट और stdio MCP क्लाइंट Client कनेक्शन हैं।

## कब उपयोग करें

- जब चुना गया Runtime या Client पथ इस शीर्षक से मेल खाए, तब इस पृष्ठ का उपयोग करें।
- workspace root, public base URL, MCP endpoint, authentication mode और host पर उपलब्ध टूल को संगत रखें।
- ChatGPT web/app के लिए `/mcp` पर समाप्त होने वाला HTTPS MCP endpoint उपलब्ध कराएँ।
- स्थानीय MCP क्लाइंट के लिए क्लाइंट समर्थन के अनुसार HTTP localhost या `local-shell-mcp --mode stdio` का उपयोग करें।

## चरण

1. पहले Runtime स्थापना पृष्ठ चुनें।
2. Runtime शुरू करें और HTTP मोड में `/healthz` जाँचें।
3. फिर Client कनेक्शन पृष्ठ चुनें।
4. Client में MCP endpoint या stdio command पंजीकृत करें।
5. वास्तविक workspace और settings की जाँच के लिए `environment_info` कॉल करें।

```text
Runtime: Docker / VS Code extension / binary / Python / stdio
Client:  ChatGPT connector / generic HTTP MCP / generic stdio MCP
Endpoint: https://your-host.example.com/mcp
```

## सत्यापन

- `environment_info` Runtime settings और workspace की पुष्टि करता है।
- `tree_view` दिखाई देने वाली फ़ाइलों की पुष्टि करता है।
- `run_shell_tool` command environment की पुष्टि करता है।

## टिप्पणियाँ

छोटे और सत्यापित किए जा सकने वाले चरणों को प्राथमिकता दें: निरीक्षण, संपादन, diff, test, scan और commit। बड़े कार्यों को भी audit योग्य tool calls में बाँटें।
