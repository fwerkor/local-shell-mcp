import { compile } from "sass"
import { createHash } from "node:crypto"
import { mkdir, rm } from "node:fs/promises"
import { resolve } from "node:path"

const root = resolve(import.meta.dir, "..")
const repository = resolve(root, "..")
const staticDir = resolve(repository, "src/local_shell_mcp/ui_static")
const liveHtmlPath = resolve(staticDir, "live-workspace.html")
const liveAliasesPath = resolve(staticDir, "live-workspace-aliases.json")
const maxLiveResourceAliases = 64
const browserBuild = {
  outdir: staticDir,
  target: "browser" as const,
  format: "esm" as const,
  naming: "[name].[ext]",
  minify: true,
}

const hashLiveHtml = (content: string | Buffer) =>
  createHash("sha256").update(content).digest("hex").slice(0, 16)

let previousLiveHash = ""
if (await Bun.file(liveHtmlPath).exists()) {
  previousLiveHash = hashLiveHtml(Buffer.from(await Bun.file(liveHtmlPath).arrayBuffer()))
}
let previousAliases: string[] = []
if (await Bun.file(liveAliasesPath).exists()) {
  try {
    const parsed = JSON.parse(await Bun.file(liveAliasesPath).text())
    if (Array.isArray(parsed)) {
      previousAliases = parsed.filter(
        (value): value is string => typeof value === "string" && /^[0-9a-f]{16}$/.test(value),
      )
    }
  } catch {
    previousAliases = []
  }
}

await rm(staticDir, { recursive: true, force: true })
await mkdir(staticDir, { recursive: true })
const result = await Bun.build({
  entrypoints: [
    resolve(root, "src/web.ts"),
  ],
  ...browserBuild,
  plugins: [{
    name: "compile-scss",
    setup(build) {
      build.onLoad({ filter: /\.scss$/ }, args => ({
        contents: compile(args.path, {
          loadPaths: [resolve(root, "node_modules")],
          style: "compressed",
          silenceDeprecations: ["import", "global-builtin", "color-functions", "legacy-js-api", "if-function"],
          logger: { warn() {}, debug() {} },
        }).css,
        loader: "css",
      }))
    },
  }],
})
if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
const liveResult = await Bun.build({
  entrypoints: [resolve(root, "src/live-workspace.ts"), resolve(root, "src/live-workspace.css")],
  ...browserBuild,
})
if (!liveResult.success) {
  for (const log of liveResult.logs) console.error(log)
  process.exit(1)
}
const webCssPath = resolve(staticDir, "web.css")
const bundledStyles = await Bun.file(webCssPath).text()
// SVAR ships unused remote font declarations. Native Files uses system fonts
// and embedded SVG icons, so remove those CDN references from the self-hosted bundle.
await Bun.write(webCssPath, bundledStyles.replace(/@font-face\s*\{[^}]*cdn\.svar\.dev[^}]*\}/g, ""))
const webScriptPath = resolve(staticDir, "web.js")
await Bun.write(webScriptPath, (await Bun.file(webScriptPath).text()).replace(/[ \t]+$/gm, ""))
for (const asset of ["index.html", "logo.svg", "favicon.svg", "third-party-notices.txt"]) {
  await Bun.write(resolve(staticDir, asset), Bun.file(resolve(root, "static", asset)))
}
const liveScriptPath = resolve(staticDir, "live-workspace.js")
const liveStylePath = resolve(staticDir, "live-workspace.css")
const liveScript = (await Bun.file(liveScriptPath).text()).replaceAll("</script", "<\\/script")
const liveStyle = (await Bun.file(liveStylePath).text()).replaceAll("</style", "<\\/style")
const liveHtml = `<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/><title>local-shell-mcp Live Workspace</title><style>${liveStyle}</style></head><body><script type="module">${liveScript}</script></body></html>`
  .replace(/[ \t]+$/gm, "")
const currentLiveHash = hashLiveHtml(liveHtml)
const liveAliases = [...new Set([previousLiveHash, ...previousAliases])]
  .filter((value) => value && value !== currentLiveHash)
  .slice(0, maxLiveResourceAliases)
await Bun.write(liveHtmlPath, liveHtml)
await Bun.write(liveAliasesPath, `${JSON.stringify(liveAliases, null, 2)}\n`)
await rm(liveScriptPath, { force: true })
await rm(liveStylePath, { force: true })
console.log("Built WebUI assets")
