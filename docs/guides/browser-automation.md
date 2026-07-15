# Browser automation

Browser tools use Playwright to inspect pages, capture evidence, and run reproducible browser workflows. The public surface is deliberately small.

## Tools

| Tool | Purpose |
|---|---|
| `browser_get_text_tool` | Extract visible text from a selector. |
| `browser_capture_tool` | Save either a PNG screenshot or Chromium PDF. |
| `playwright_run_script_tool` | Run a complete Python Playwright script for clicks, forms, console inspection, or multi-page flows. |

All three accept optional `machine`. Browser dependencies must already be installed on the selected controller or worker; installation is performed with ordinary shell commands such as `python -m playwright install chromium`.

## Common flows

For visual verification, start the site with `shell_start` or `job_start`, wait for readiness, call `browser_capture_tool(capture_format="png")`, then stop the process. Use `capture_format="pdf"` with Chromium for printable output.

Use `browser_get_text_tool` when only rendered content matters. Use `playwright_run_script_tool` when the workflow requires interaction or JavaScript evaluation.

Keep scripts bounded, set explicit timeouts, save artifacts under the workspace, and avoid entering credentials unless the environment is dedicated to the task.
