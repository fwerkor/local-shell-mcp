# local-shell-mcp दस्तावेज़

ChatGPT Developer Mode और अन्य MCP clients के लिए स्थानीय control plane. यह नियंत्रित workspace, shell, files, Git, browser automation, file links और remote workers को MCP tools के रूप में उपलब्ध कराता है।

## Documentation paths

- [त्वरित शुरुआत](getting-started/quickstart.md)
- [ChatGPT connector](getting-started/chatgpt-connector.md)
- [Remote workers](guides/remote-workers.md)
- [सुरक्षा](security.md)
- [समस्या निवारण](troubleshooting.md)

## Core architecture

```text
ChatGPT / MCP client
  -> HTTPS endpoint
  -> local-shell-mcp control server
  -> controlled workspace
  -> optional outbound remote workers
```

## Key safety rule

Public deployment में OAuth सक्षम रखें और Docker socket, host root या long-lived credentials mount न करें।
