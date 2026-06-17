# local-shell-mcp दस्तावेज़

ChatGPT Developer Mode और अन्य MCP क्लाइंट के लिए स्थानीय नियंत्रण स्तर। यह नियंत्रित workspace, shell, फ़ाइलें, Git, ब्राउज़र स्वचालन, फ़ाइल लिंक और दूरस्थ worker को MCP टूल के रूप में उपलब्ध कराता है।

## दस्तावेज़ पथ

- [त्वरित शुरुआत](getting-started/quickstart.md)
- [ChatGPT कनेक्टर](getting-started/chatgpt-connector.md)
- [दूरस्थ worker](guides/remote-workers.md)
- [सुरक्षा](security.md)
- [समस्या निवारण](troubleshooting.md)

## मुख्य आर्किटेक्चर

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## मुख्य सुरक्षा नियम

सार्वजनिक deployment में OAuth सक्षम करें और Docker socket, host root या लंबी अवधि के credentials mount न करें।
