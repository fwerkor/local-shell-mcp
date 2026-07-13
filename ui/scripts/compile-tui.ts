import { chmod, mkdir, rm } from "node:fs/promises"
import { resolve } from "node:path"
import { nonCurrentOpenTuiNativePackages } from "./platform"

const root = resolve(import.meta.dir, "..")
const executableName = process.platform === "win32" ? "local-shell-mcp-tui.exe" : "local-shell-mcp-tui"
const outdir = process.env.LSM_UI_BINARY_OUTDIR
  ? resolve(process.env.LSM_UI_BINARY_OUTDIR)
  : resolve(root, "dist")
const outfile = resolve(outdir, executableName)
if (!process.env.LSM_UI_BINARY_OUTDIR) await rm(outdir, { recursive: true, force: true })
await mkdir(outdir, { recursive: true })

const result = await Bun.build({
  entrypoints: [resolve(root, "src/tui.tsx")],
  tsconfig: resolve(root, "tsconfig.json"),
  minify: true,
  external: nonCurrentOpenTuiNativePackages(),
  compile: {
    outfile,
  },
})
if (!result.success) {
  for (const log of result.logs) console.error(log)
  process.exit(1)
}
if (process.platform !== "win32") await chmod(outfile, 0o755)
console.log(outfile)
