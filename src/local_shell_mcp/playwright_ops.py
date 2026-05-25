from __future__ import annotations

import json
import shlex
import textwrap
import uuid

from .fs_ops import relative_display, resolve_path
from .shell_ops import run_shell


async def playwright_install(browser: str = "chromium", with_deps: bool = False) -> dict:
    if browser not in {"chromium", "firefox", "webkit", "all"}:
        raise ValueError("browser must be chromium, firefox, webkit, or all")
    cmd = "python3 -m playwright install"
    if with_deps:
        cmd += " --with-deps"
    if browser != "all":
        cmd += " " + shlex.quote(browser)
    result = await run_shell(cmd, timeout_s=1800, max_output_bytes=500_000)
    return result.model_dump()


async def browser_screenshot(
    url: str,
    output_path: str = "screenshots/page.png",
    browser: str = "chromium",
    full_page: bool = True,
    width: int = 1440,
    height: int = 1000,
    wait_until: str = "networkidle",
) -> dict:
    if browser not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be chromium, firefox, or webkit")
    if wait_until not in {"load", "domcontentloaded", "networkidle", "commit"}:
        raise ValueError("invalid wait_until")
    out = resolve_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    script_path = resolve_path(f".local-shell-mcp/tmp/playwright-{uuid.uuid4().hex}.py")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = getattr(p, {browser!r}).launch(headless=True)
    page = browser.new_page(viewport={{"width": {int(width)}, "height": {int(height)}}})
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    page.screenshot(path={str(out)!r}, full_page={bool(full_page)!r})
    print(page.title())
    browser.close()
'''
    script_path.write_text(textwrap.dedent(script), encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(script_path))}", timeout_s=120, max_output_bytes=200_000)
    return {**result.model_dump(), "screenshot_path": relative_display(out)}


async def browser_get_text(
    url: str,
    browser: str = "chromium",
    wait_until: str = "networkidle",
    selector: str = "body",
) -> dict:
    if browser not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be chromium, firefox, or webkit")
    script_path = resolve_path(f".local-shell-mcp/tmp/playwright-{uuid.uuid4().hex}.py")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = getattr(p, {browser!r}).launch(headless=True)
    page = browser.new_page()
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    print("TITLE:", page.title())
    print("URL:", page.url)
    locator = page.locator({selector!r}).first
    print(locator.inner_text(timeout=10000))
    browser.close()
'''
    script_path.write_text(textwrap.dedent(script), encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(script_path))}", timeout_s=120, max_output_bytes=500_000)
    return result.model_dump()


async def browser_eval(
    url: str,
    javascript: str,
    browser: str = "chromium",
    wait_until: str = "networkidle",
) -> dict:
    """Navigate to a URL and evaluate JavaScript.

    The JavaScript should be an expression or function body accepted by Playwright page.evaluate.
    """
    if browser not in {"chromium", "firefox", "webkit"}:
        raise ValueError("browser must be chromium, firefox, or webkit")
    script_path = resolve_path(f".local-shell-mcp/tmp/playwright-{uuid.uuid4().hex}.py")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
import json
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = getattr(p, {browser!r}).launch(headless=True)
    page = browser.new_page()
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    value = page.evaluate({javascript!r})
    print(json.dumps(value, ensure_ascii=False, default=str))
    browser.close()
'''
    script_path.write_text(textwrap.dedent(script), encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(script_path))}", timeout_s=120, max_output_bytes=500_000)
    parsed = None
    if result.ok and result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            parsed = None
    return {**result.model_dump(), "json": parsed}


async def browser_pdf(
    url: str,
    output_path: str = "screenshots/page.pdf",
    width: int = 1440,
    height: int = 1000,
    wait_until: str = "networkidle",
) -> dict:
    out = resolve_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    script_path = resolve_path(f".local-shell-mcp/tmp/playwright-{uuid.uuid4().hex}.py")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script = f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={{"width": {int(width)}, "height": {int(height)}}})
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    page.pdf(path={str(out)!r}, print_background=True)
    print(page.title())
    browser.close()
'''
    script_path.write_text(textwrap.dedent(script), encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(script_path))}", timeout_s=120, max_output_bytes=200_000)
    return {**result.model_dump(), "pdf_path": relative_display(out)}


async def playwright_run_script(script: str, cwd: str = ".", timeout_s: int = 300) -> dict:
    """Run a caller-supplied Python Playwright script inside the workspace.

    The script is written to .local-shell-mcp/tmp and executed with python3. This is powerful;
    use it only when the container is disposable and authenticated.
    """
    path = resolve_path(f".local-shell-mcp/tmp/playwright-custom-{uuid.uuid4().hex}.py")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    result = await run_shell(f"python3 {shlex.quote(str(path))}", cwd=cwd, timeout_s=timeout_s, max_output_bytes=1_000_000)
    return {**result.model_dump(), "script_path": relative_display(path)}
