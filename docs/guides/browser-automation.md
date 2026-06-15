# Browser automation

Browser tools use Playwright to inspect web pages, capture evidence, evaluate page state, and generate PDFs. They are useful for documentation sites, UI smoke tests, visual regression triage, and collecting reproducible screenshots.

## Tools

| Tool | Purpose |
|---|---|
| `playwright_install_tool` | Install browser binaries when they are missing. |
| `browser_screenshot_tool` | Save a page screenshot under the workspace. |
| `browser_get_text_tool` | Extract visible text from a selector. |
| `browser_eval_tool` | Evaluate JavaScript in the page context. |
| `browser_pdf_tool` | Save a Chromium PDF of a page. |
| `playwright_run_script_tool` | Run a full Python Playwright script. |
| `remote_browser_*` | Run equivalent operations on a connected remote worker. |

## Common flows

### Screenshot a local documentation site

1. Start the site in a persistent shell session.
2. Wait until the server reports a local URL.
3. Call `browser_screenshot_tool` with that URL.
4. Use `create_file_link` if the screenshot must be downloaded from chat.
5. Kill the persistent shell session.

### Extract text for quick verification

Use `browser_get_text_tool` when the main question is whether a page rendered the expected content.

Example task wording:

```text
Start the docs preview, use browser_get_text_tool on the home page, and confirm that the deployment, tools, and usage-patterns pages appear in navigation.
```

### Run a custom Playwright script

Use `playwright_run_script_tool` when built-in screenshot/text/PDF tools are not enough, for example when you need to click through a flow, inspect console errors, or capture multiple pages.

Keep scripts bounded:

- Set explicit timeouts.
- Save artifacts under the workspace.
- Avoid entering credentials unless the environment is dedicated to that task.
- Prefer read-only checks for public sites.

## Troubleshooting

If browser launch fails:

- Run `playwright_install_tool` for the needed browser.
- Confirm the container or host has the required system dependencies.
- In Docker, prefer the official project image because it includes the intended browser/document tooling.
- For remote workers, install dependencies on the remote machine or use browser tools on the control server instead.
