import { mkdir, rm } from "node:fs/promises"
import { resolve } from "node:path"

const root = resolve(import.meta.dir, "..")
const repository = resolve(root, "..")
const staticDir = resolve(repository, "src/local_shell_mcp/ui_static")

await rm(staticDir, { recursive: true, force: true })
await mkdir(staticDir, { recursive: true })
const result = await Bun.build({
  entrypoints: [
    resolve(root, "src/web.ts"),
    resolve(root, "src/web.css"),
    resolve(root, "src/web-console-mobile.css"),
  ],
  outdir: staticDir,
  target: "browser",
  format: "esm",
  naming: "[name].[ext]",
  minify: true,
})
if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
const webCssPath = resolve(staticDir, "web.css")
const consoleCssPath = resolve(staticDir, "web-console-mobile.css")
await Bun.write(
  webCssPath,
  `${await Bun.file(webCssPath).text()}\n${await Bun.file(consoleCssPath).text()}`,
)
await rm(consoleCssPath, { force: true })
await Bun.write(resolve(staticDir, "index.html"), Bun.file(resolve(root, "static/index.html")))
console.log("Built WebUI assets")
