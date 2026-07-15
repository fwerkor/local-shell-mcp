from __future__ import annotations

import asyncio

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .auth import (
    CloudflareAccessMiddleware,
    Principal,
    RequestBodyLimitMiddleware,
    require_scopes,
    required_scopes_for_http_tool,
    verify_request,
)
from .downloads import (
    create_download_link,
    download_endpoint,
    list_download_links,
    revoke_download_link,
)
from .fs_ops import (
    delete_path,
    edit_text,
    glob_paths,
    list_dir,
    multi_edit_text,
    read_text,
    write_text,
)
from .git_ops import (
    git_add,
    git_checkout,
    git_clone,
    git_commit,
    git_diff,
    git_fetch,
    git_log,
    git_pull,
    git_push,
    git_reset,
    git_show,
    git_status,
)
from .human_ui import ui_routes
from .playwright_ops import (
    browser_eval,
    browser_get_text,
    browser_pdf,
    browser_screenshot,
    playwright_install,
    playwright_run_script,
)
from .search_ops import grep, tree
from .settings import get_settings
from .shell_ops import (
    PUBLIC_TOOL_WATCHDOG_TIMEOUT_S,
    kill_shell,
    list_shells,
    public_run_shell,
    read_shell,
    send_shell,
    start_shell,
)
from .skill_ops import (
    list_installed_skills,
    load_installed_skill,
    read_installed_skill_file,
)
from .todo_ops import todo_read, todo_write
from .version import version_info

PUBLIC_TOOL_TIMEOUT_S = PUBLIC_TOOL_WATCHDOG_TIMEOUT_S
NON_CANCELLABLE_HTTP_MUTATIONS = frozenset(
    {
        "/tools/download/create",
        "/tools/download/revoke",
        "/tools/write_file",
        "/tools/edit_file",
        "/tools/multi_edit_file",
        "/tools/delete",
        "/tools/todo",
    }
)


class SkillLoadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)


class SkillReadFileRequest(SkillLoadRequest):
    path: str = Field(min_length=1, max_length=4096)


def principal_dep(request: Request) -> Principal:
    principal = verify_request(request)
    require_scopes(principal, required_scopes_for_http_tool(str(request.url.path), request.method))
    return principal


PRINCIPAL_DEP = Depends(principal_dep)


async def _blocking(func, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
    return await asyncio.to_thread(func, *args, **kwargs)


def _body_bool(body: dict, key: str, default: bool) -> bool:
    if key not in body:
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _body_int(
    body: dict,
    key: str,
    default: int | None,
    *,
    allow_none: bool = False,
) -> int | None:
    if key not in body:
        return default
    value = body[key]
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def build_http_app() -> FastAPI:
    app = FastAPI(title="local-shell-mcp REST API", version="0.1.0")
    settings = get_settings()
    if settings.auth_mode != "none":
        app.add_middleware(CloudflareAccessMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware)

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):  # noqa: ARG001
        return JSONResponse(status_code=400, content={"ok": False, "error": "validation_error", "message": str(exc)})

    @app.exception_handler(KeyError)
    async def key_error_handler(request: Request, exc: KeyError):  # noqa: ARG001
        missing = str(exc.args[0]) if exc.args else "unknown"
        return JSONResponse(
            status_code=400,
            content={"ok": False, "error": "validation_error", "message": f"Missing required argument: {missing}"},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request, exc: RequestValidationError  # noqa: ARG001
    ):
        messages = []
        for error in exc.errors():
            location = ".".join(str(part) for part in error.get("loc", [])[1:])
            message = str(error.get("msg", "Invalid request"))
            messages.append(f"{location}: {message}" if location else message)
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "validation_error",
                "message": "; ".join(messages) or "Invalid request",
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):  # noqa: ARG001
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": "http_error", "message": exc.detail},
            headers=exc.headers,
        )

    @app.middleware("http")
    async def tools_timeout_middleware(request: Request, call_next):  # noqa: ANN001
        if not request.url.path.startswith("/tools/"):
            return await call_next(request)
        if request.url.path in NON_CANCELLABLE_HTTP_MUTATIONS and (
            request.url.path != "/tools/todo" or request.method.upper() != "GET"
        ):
            return await call_next(request)
        try:
            return await asyncio.wait_for(call_next(request), timeout=PUBLIC_TOOL_TIMEOUT_S)
        except TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "ok": False,
                    "error": "tool_timeout",
                    "message": f"{request.url.path} exceeded {PUBLIC_TOOL_TIMEOUT_S} second public tool timeout",
                },
            )

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.get("/readyz")
    async def readyz():
        return {"ok": True}

    @app.get("/version")
    async def api_version():
        return version_info()

    @app.get("/tools/version")
    async def api_tool_version(_: Principal = PRINCIPAL_DEP):
        return version_info()

    @app.get("/tools/skills_list")
    async def api_skills_list(_: Principal = PRINCIPAL_DEP):
        return await _blocking(list_installed_skills, settings)

    @app.post("/tools/skill_load")
    async def api_skill_load(body: SkillLoadRequest, _: Principal = PRINCIPAL_DEP):
        return await _blocking(load_installed_skill, body.name, settings)

    @app.post("/tools/skill_read_file")
    async def api_skill_read_file(
        body: SkillReadFileRequest, _: Principal = PRINCIPAL_DEP
    ):
        return await _blocking(
            read_installed_skill_file,
            body.name,
            body.path,
            settings,
        )

    @app.post("/tools/run_shell")
    async def api_run_shell(body: dict, _: Principal = PRINCIPAL_DEP):
        try:
            return (await public_run_shell(body["command"], body.get("cwd", "."), _body_int(body, "timeout_s", None, allow_none=True), _body_int(body, "max_output_bytes", None, allow_none=True))).model_dump()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/tools/shell_start")
    async def api_shell_start(body: dict, _: Principal = PRINCIPAL_DEP):
        return await start_shell(body.get("cwd", "."), body.get("name"), body.get("command"))

    @app.post("/tools/shell_send")
    async def api_shell_send(body: dict, _: Principal = PRINCIPAL_DEP):
        return await send_shell(body["session_id"], body["input_text"], _body_bool(body, "enter", True))

    @app.post("/tools/shell_read")
    async def api_shell_read(body: dict, _: Principal = PRINCIPAL_DEP):
        return await read_shell(body["session_id"], _body_int(body, "lines", 200))

    @app.post("/tools/shell_kill")
    async def api_shell_kill(body: dict, _: Principal = PRINCIPAL_DEP):
        return await kill_shell(body["session_id"])

    @app.get("/tools/shell_list")
    async def api_shell_list(_: Principal = PRINCIPAL_DEP):
        return await list_shells()

    @app.post("/tools/list_files")
    async def api_list_files(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(list_dir, body.get("path", "."), _body_bool(body, "recursive", False), _body_int(body, "max_entries", 500))

    @app.post("/tools/tree")
    async def api_tree(body: dict, _: Principal = PRINCIPAL_DEP):
        return await tree(body.get("cwd", "."), _body_int(body, "depth", 3), _body_int(body, "max_entries", 500))

    @app.post("/tools/glob")
    async def api_glob(body: dict, _: Principal = PRINCIPAL_DEP):
        return {"paths": await _blocking(glob_paths, body["pattern"], body.get("cwd", "."), _body_int(body, "max_results", 500))}

    @app.post("/tools/grep")
    async def api_grep(body: dict, _: Principal = PRINCIPAL_DEP):
        return await grep(body["query"], body.get("cwd", "."), body.get("glob"), _body_bool(body, "regex", True), _body_bool(body, "case_sensitive", True), _body_int(body, "max_results", None, allow_none=True))

    @app.api_route("/download/{token}", methods=["GET", "HEAD"])
    async def api_download(request: Request):
        return await download_endpoint(request)

    @app.post("/tools/download/create")
    async def api_create_download_link(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(
            create_download_link,
            body["path"],
            _body_int(body, "ttl_s", None, allow_none=True),
            body.get("filename"),
            _body_int(body, "max_downloads", None, allow_none=True),
        )

    @app.get("/tools/download/list")
    async def api_list_download_links(include_expired: bool = False, _: Principal = PRINCIPAL_DEP):
        return await _blocking(list_download_links, include_expired)

    @app.post("/tools/download/revoke")
    async def api_revoke_download_link(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(revoke_download_link, body["token"])

    @app.post("/tools/read_file")
    async def api_read_file(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(
            read_text,
            body["path"],
            _body_int(body, "start_line", None, allow_none=True),
            _body_int(body, "end_line", None, allow_none=True),
            body.get("binary_preview"),
            _body_int(body, "binary_preview_bytes", 256),
        )

    @app.post("/tools/write_file")
    async def api_write_file(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(write_text, body["path"], body["content"], _body_bool(body, "overwrite", True))

    @app.post("/tools/edit_file")
    async def api_edit_file(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(edit_text, body["path"], body["old"], body["new"], _body_bool(body, "replace_all", False))

    @app.post("/tools/multi_edit_file")
    async def api_multi_edit_file(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(multi_edit_text, body["path"], body["edits"])

    @app.post("/tools/delete")
    async def api_delete(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(delete_path, body["path"], _body_bool(body, "recursive", False))

    @app.post("/tools/git/status")
    async def api_git_status(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_status(body.get("cwd", "."))

    @app.post("/tools/git/diff")
    async def api_git_diff(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_diff(body.get("cwd", "."), _body_bool(body, "staged", False), body.get("path"), _body_bool(body, "stat", False))

    @app.post("/tools/git/log")
    async def api_git_log(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_log(body.get("cwd", "."), _body_int(body, "max_count", 20))

    @app.post("/tools/git/clone")
    async def api_git_clone(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_clone(body["repo_url"], body.get("dest"), body.get("branch"), body.get("cwd", "."))

    @app.post("/tools/git/checkout")
    async def api_git_checkout(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_checkout(body["cwd"], body["ref"], _body_bool(body, "create", False))

    @app.post("/tools/git/fetch")
    async def api_git_fetch(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_fetch(body.get("cwd", "."), body.get("remote", "origin"), _body_bool(body, "prune", True))

    @app.post("/tools/git/pull")
    async def api_git_pull(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_pull(body.get("cwd", "."), _body_bool(body, "ff_only", True))

    @app.post("/tools/git/add")
    async def api_git_add(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_add(body.get("cwd", "."), body.get("paths"))

    @app.post("/tools/git/commit")
    async def api_git_commit(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_commit(body["cwd"], body["message"], _body_bool(body, "all_changes", False))

    @app.post("/tools/git/push")
    async def api_git_push(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_push(body["cwd"], body.get("remote", "origin"), body.get("branch"), _body_bool(body, "set_upstream", True))

    @app.post("/tools/git/show")
    async def api_git_show(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_show(body.get("cwd", "."), body.get("ref", "HEAD"), body.get("path"))

    @app.post("/tools/git/reset")
    async def api_git_reset(body: dict, _: Principal = PRINCIPAL_DEP):
        return await git_reset(body.get("cwd", "."), body.get("mode", "soft"), body.get("ref", "HEAD"))

    @app.get("/tools/todo")
    async def api_todo_read(_: Principal = PRINCIPAL_DEP):
        return await _blocking(todo_read)

    @app.post("/tools/todo")
    async def api_todo_write(body: dict, _: Principal = PRINCIPAL_DEP):
        return await _blocking(todo_write, body.get("todos", []))

    @app.post("/tools/playwright/install")
    async def api_playwright_install(body: dict, _: Principal = PRINCIPAL_DEP):
        return await playwright_install(body.get("browser", "chromium"), _body_bool(body, "with_deps", False))

    @app.post("/tools/browser/screenshot")
    async def api_browser_screenshot(body: dict, _: Principal = PRINCIPAL_DEP):
        return await browser_screenshot(body["url"], body.get("output_path", "screenshots/page.png"), body.get("browser", "chromium"), _body_bool(body, "full_page", True), _body_int(body, "width", 1440), _body_int(body, "height", 1000), body.get("wait_until", "networkidle"))

    @app.post("/tools/browser/text")
    async def api_browser_text(body: dict, _: Principal = PRINCIPAL_DEP):
        return await browser_get_text(body["url"], body.get("browser", "chromium"), body.get("wait_until", "networkidle"), body.get("selector", "body"))

    @app.post("/tools/browser/eval")
    async def api_browser_eval(body: dict, _: Principal = PRINCIPAL_DEP):
        return await browser_eval(body["url"], body["javascript"], body.get("browser", "chromium"), body.get("wait_until", "networkidle"))

    @app.post("/tools/browser/pdf")
    async def api_browser_pdf(body: dict, _: Principal = PRINCIPAL_DEP):
        return await browser_pdf(body["url"], body.get("output_path", "screenshots/page.pdf"), _body_int(body, "width", 1440), _body_int(body, "height", 1000), body.get("wait_until", "networkidle"))

    @app.post("/tools/playwright/run_script")
    async def api_playwright_run_script(body: dict, _: Principal = PRINCIPAL_DEP):
        return await playwright_run_script(body["script"], body.get("cwd", "."), _body_int(body, "timeout_s", 60))

    app.router.routes.extend(ui_routes())
    return app
