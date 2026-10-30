import { plugin } from "bun"

// Production compiles Canonical's component Sass through the build plugin.
// Unit tests exercise component behavior; browsers validate the compiled CSS.
plugin({
  name: "component-scss",
  setup(build) {
    build.onLoad({ filter: /\.scss$/ }, () => ({ contents: "", loader: "js" }))
  },
})
