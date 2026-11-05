#!/usr/bin/env python3
"""Apply the minimal LSM authentication bridge to a pinned LibreChat checkout."""

from pathlib import Path
import argparse
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent


def apply(source: Path) -> None:
    index = source / "api/server/index.js"
    if not index.is_file() or not (source / "api/server/routes/auth.js").is_file():
        raise ValueError("Not a supported LibreChat source checkout")
    original = index.read_text()
    target = "  app.use('/api/auth', preAuthTenantMiddleware, routes.auth);"
    injection = (
        "  app.use('/api/auth/lsm', preAuthTenantMiddleware, "
        "require('./routes/lsm-auth'));\n" + target
    )
    if injection not in original:
        if original.count(target) != 1:
            raise ValueError("LibreChat authentication route anchor has changed")
        index.write_text(original.replace(target, injection))
    dest = source / "api/server/routes/lsm-auth.js"
    shutil.copy2(ROOT / "upstream/api/server/routes/lsm-auth.js", dest)

    meta = """  if (process.env.LSM_PARENT_ORIGIN) {
    const origin = new URL(process.env.LSM_PARENT_ORIGIN).origin;
    indexHTML = indexHTML.replace('</head>', `<meta name="lsm-parent-origin" content="${escapeHtmlAttribute(origin)}"></head>`);
  }
"""
    html_anchor = "  /* The composer lays out against whether a footer bar sits beneath it"
    if meta not in index.read_text():
        current = index.read_text()
        if current.count(html_anchor) != 1:
            raise ValueError("LibreChat HTML integration anchor has changed")
        index.write_text(current.replace(html_anchor, meta + "\n" + html_anchor))

    prefs = source / "api/server/routes/lsm-prefs.js"
    shutil.copy2(ROOT / "upstream/api/server/routes/lsm-prefs.js", prefs)
    if "lsmChatPrefs" not in (source / "api/server/controllers/agents/client.js").read_text():
        subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(ROOT / "preferences.patch")],
            cwd=source, check=True,
        )

    agent = source / "api/server/controllers/agents/openai.js"
    if "req.lsmChatPrefs?.memory" not in agent.read_text():
        subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(ROOT / "agentPolicy.patch")],
            cwd=source, check=True,
        )

    components = source / "client/src/components/Chat/Input"
    shutil.copy2(
        ROOT / "upstream/client/src/components/Chat/Input/LsmChatPermissions.tsx",
        components / "LsmChatPermissions.tsx",
    )
    form = components / "ChatForm.tsx"
    if "LsmChatPermissions" not in form.read_text():
        subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(ROOT / "chatForm.patch")],
            cwd=source, check=True,
        )

    shutil.copy2(
        ROOT / "upstream/client/src/components/Chat/Input/LsmLocalAttachmentButton.tsx",
        components / "LsmLocalAttachmentButton.tsx",
    )
    if "LsmLocalAttachmentButton" not in form.read_text():
        subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(ROOT / "localUpload.patch")],
            cwd=source, check=True,
        )

    composer = source / "client/src/hooks/Input/useTextarea.ts"
    if "lsm:local-attachment" not in composer.read_text():
        subprocess.run(
            ["patch", "-p1", "--forward", "-i", str(ROOT / "useTextarea.patch")],
            cwd=source, check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
