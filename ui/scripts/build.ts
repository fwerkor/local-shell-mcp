import { mkdir, rm } from "node:fs/promises"
import { resolve } from "node:path"

const root = resolve(import.meta.dir, "..")
const repository = resolve(root, "..")
const staticDir = resolve(repository, "src/local_shell_mcp/ui_static")
const browserBuild = {
  outdir: staticDir,
  target: "browser" as const,
  format: "esm" as const,
  naming: "[name].[ext]",
  minify: true,
}

await rm(staticDir, { recursive: true, force: true })
await mkdir(staticDir, { recursive: true })
const result = await Bun.build({
  entrypoints: [
    resolve(root, "src/web.ts"),
    resolve(root, "src/web.css"),
    resolve(root, "src/web-native.css"),
    resolve(root, "src/web-console-mobile.css"),
  ],
  ...browserBuild,
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
const nativeCssPath = resolve(staticDir, "web-native.css")
const consoleCssPath = resolve(staticDir, "web-console-mobile.css")
await Bun.write(
  webCssPath,
  `${await Bun.file(webCssPath).text()}\n${await Bun.file(nativeCssPath).text()}\n${await Bun.file(consoleCssPath).text()}`,
)
await rm(nativeCssPath, { force: true })
await rm(consoleCssPath, { force: true })
for (const asset of ["index.html", "logo.svg", "favicon.svg"]) {
  await Bun.write(resolve(staticDir, asset), Bun.file(resolve(root, "static", asset)))
}
const liveScriptPath = resolve(staticDir, "live-workspace.js")
const liveStylePath = resolve(staticDir, "live-workspace.css")
const liveScript = (await Bun.file(liveScriptPath).text()).replaceAll("</script", "<\\/script")
const liveStyle = (await Bun.file(liveStylePath).text()).replaceAll("</style", "<\\/style")
const liveHtml = `<!doctype html><html><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"/><title>local-shell-mcp Live Workspace</title><style>${liveStyle}</style></head><body><script type="module">${liveScript}</script></body></html>`
  .replace(/[ \t]+$/gm, "")
await Bun.write(resolve(staticDir, "live-workspace.html"), liveHtml)
await rm(liveScriptPath, { force: true })
await rm(liveStylePath, { force: true })
console.log("Built WebUI assets")
