from __future__ import annotations

import asyncio
import textwrap
import uuid

from .fs_ops import prune_temp_dir, relative_display, resolve_path, temp_dir
from .settings import get_settings
from .shell_ops import public_run_shell_timeout, quote_shell_argument, run_shell

_VALID_BROWSERS = {"chromium", "firefox", "webkit"}
_VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}


def _assert_script_size(script: str) -> None:
    settings = get_settings()
    size = len(script.encode("utf-8"))
    if size > settings.max_file_write_bytes:
        raise ValueError(
            f"Refusing Playwright script of {size} bytes; max is {settings.max_file_write_bytes}"
        )


def _validate_browser(browser: str, wait_until: str) -> None:
    if browser not in _VALID_BROWSERS:
        raise ValueError("browser must be chromium, firefox, or webkit")
    if wait_until not in _VALID_WAIT_UNTIL:
        raise ValueError("invalid wait_until")


async def _run_generated_script(script: str, *, max_output_bytes: int = 500_000) -> dict:
    await asyncio.to_thread(prune_temp_dir)
    script_path = temp_dir() / f"playwright-{uuid.uuid4().hex}.py"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(
        script_path.write_text,
        textwrap.dedent(script),
        encoding="utf-8",
    )
    result = await run_shell(
        f"{quote_shell_argument(get_settings().python_bin)} "
        f"{quote_shell_argument(str(script_path))}",
        timeout_s=60,
        max_output_bytes=max_output_bytes,
    )
    return {**result.model_dump(), "script_path": relative_display(script_path)}


async def browser_get_text(
    url: str,
    browser: str = "chromium",
    wait_until: str = "networkidle",
    selector: str = "body",
) -> dict:
    _validate_browser(browser, wait_until)
    script = f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = getattr(p, {browser!r}).launch(headless=True)
    page = browser.new_page()
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    print("TITLE:", page.title())
    print("URL:", page.url)
    print(page.locator({selector!r}).first.inner_text(timeout=10000))
    browser.close()
'''
    return await _run_generated_script(script)


async def browser_capture(
    url: str,
    output_path: str | None = None,
    capture_format: str = "png",
    browser: str = "chromium",
    full_page: bool = True,
    width: int = 1440,
    height: int = 1000,
    wait_until: str = "networkidle",
) -> dict:
    capture_format = capture_format.lower().strip()
    if capture_format not in {"png", "pdf"}:
        raise ValueError("capture_format must be png or pdf")
    _validate_browser(browser, wait_until)
    if capture_format == "pdf" and browser != "chromium":
        raise ValueError("PDF capture requires chromium")

    output_path = output_path or f"screenshots/page.{capture_format}"
    out = resolve_path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    capture_statement = (
        f"page.screenshot(path={str(out)!r}, full_page={bool(full_page)!r})"
        if capture_format == "png"
        else f"page.pdf(path={str(out)!r}, print_background=True)"
    )
    script = f'''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = getattr(p, {browser!r}).launch(headless=True)
    page = browser.new_page(viewport={{"width": {int(width)}, "height": {int(height)}}})
    page.goto({url!r}, wait_until={wait_until!r}, timeout=60000)
    {capture_statement}
    print(page.title())
    browser.close()
'''
    result = await _run_generated_script(script, max_output_bytes=200_000)
    return {
        **result,
        "capture_format": capture_format,
        "capture_path": relative_display(out) if result.get("ok") and out.is_file() else None,
    }


async def playwright_run_script(script: str, cwd: str = ".", timeout_s: int = 60) -> dict:
    """Run a caller-supplied Python Playwright script inside the workspace."""

    _assert_script_size(script)
    await asyncio.to_thread(prune_temp_dir)
    path = temp_dir() / f"playwright-custom-{uuid.uuid4().hex}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(path.write_text, script, encoding="utf-8")
    result = await run_shell(
        f"{quote_shell_argument(get_settings().python_bin)} {quote_shell_argument(str(path))}",
        cwd=cwd,
        timeout_s=public_run_shell_timeout(timeout_s),
        max_output_bytes=1_000_000,
    )
    return {**result.model_dump(), "script_path": relative_display(path)}
