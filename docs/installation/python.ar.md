<!-- i18n-source-sha256: c8c0d8ebdbb123b9ac4af1fd288f30e8ca69037ca086486cb8027e2592f4b75a -->
# Python وpipx وsource runtimes

**النشر المباشر من نسخة المصدر هو الخيار الموصى به**. استخدم بيئة Python افتراضية ومساحة عمل محدودة؛ Docker Compose بديل.

استخدم هذه الصفحة لثلاث حالات مترابطة:

- `pipx install local-shell-mcp`: تثبيت executable على مستوى المستخدم.
- `pip install local-shell-mcp`: تثبيت داخل virtual environment موجودة.
- Editable source checkout: تطوير المشروع نفسه أو تصحيح أخطائه.

## تثبيت pipx

`pipx` هو أنظف تثبيت قائم على Python للمستخدم العادي لأنه يمنح command بيئة virtual environment خاصة به مع إتاحة executable على `PATH`.

```bash
pipx install local-shell-mcp
local-shell-mcp --help
```

شغّل HTTP MCP server محلياً:

```bash
mkdir -p ~/local-shell-mcp-workspace
export LOCAL_SHELL_MCP_WORKSPACE_ROOT=~/local-shell-mcp-workspace
local-shell-mcp --mode mcp
```

تحقق من الصحة:

```bash
curl -i http://127.0.0.1:8765/healthz
```

## التثبيت في virtual environment

استخدم هذا عندما تدير Python environments بنفسك:

```bash
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install local-shell-mcp
local-shell-mcp --mode mcp
```

يستخدم process الأدوات المثبتة على host. لا تثبّت Python package لك compilers أو Git أو browser system dependencies أو project dependencies.

## Editable source checkout

استخدم هذا الخيار للنشر المعتاد أو التطوير. لإعداد الوصول العام راجع [quickstart](../getting-started/quickstart.md).

```bash
git clone https://github.com/fwerkor/local-shell-mcp.git
cd local-shell-mcp
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -e .
cp .env.example .env
# Replace the example OAuth secrets in .env before starting.
set -a
. ./.env
set +a
mkdir -p workspaces/default
export LOCAL_SHELL_MCP_WORKSPACE_ROOT="$PWD/workspaces/default"
local-shell-mcp --mode mcp
```

شغّل الفحوص:

```bash
python -m pip install -e '.[dev,docs]'
ruff check .
pytest -q
mkdocs build --strict
```

## إعداد المتصفح

Playwright ميزة اختيارية؛ يمكن تثبيتها مع المتصفح عند الحاجة.

```bash
python -m pip install -e '.[browser]'
python -m playwright install chromium
```

تثبيت المتصفح اختياري؛ لا تحتوي صورة Docker الأساسية على Playwright أو متصفحات.

## الاستخدام العام لـ HTTP MCP

لـ ChatGPT أو public HTTP MCP client آخر، اضبط إعدادات public origin وOAuth نفسها كبقية HTTP runtimes، ثم اكشف local port عبر reverse proxy أو tunnel.

MCP endpoint العام هو:

```text
https://your-public-host.example.com/mcp
```

## Development modes

| Mode | Command | الاستخدام |
|---|---|---|
| MCP HTTP | `local-shell-mcp --mode mcp` | MCP clients كاملة عبر HTTP، بما فيها ChatGPT خلف HTTPS |
| REST-style HTTP | `local-shell-mcp --mode http` | Diagnostic أو compatibility endpoints، وليس المسار الرئيسي لـ ChatGPT |
| stdio | `local-shell-mcp --mode stdio` | MCP clients محلية تشغّل process |

`mode=both` محجوز ولا ينبغي حالياً استخدامه كـ mode لعملية واحدة.

## أمان host runtime

تعمل Python installs بصلاحيات host user ما لم تضعها في VM/container. أبقِ workspace ضيقاً وfull-container mode معطلاً، ولا تجعل workspace يشير إلى home directory.

استخدم Docker Compose مع repositories غير الموثوقة أو tasks كثيفة package manager أو workflows التي تكون فيها resetability أهم من host integration.
