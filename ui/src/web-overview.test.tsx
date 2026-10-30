/** @jsxImportSource react */
import { describe, expect, test } from "bun:test"
import { renderToStaticMarkup } from "react-dom/server"
import { Overview } from "./web-app"
import { actionButton } from "./web-controls"

describe("React WebUI overview", () => {
  test("shows every alert and escapes controller supplied text", () => {
    const html = renderToStaticMarkup(<Overview data={{health:"healthy", alerts:Array.from({length:8},(_,i)=>({title:`Alert ${i}`,detail:"<script>bad()</script>"}))}} navigate={() => {}} />)
    expect(html.match(/class="overview-alert"/g)?.length).toBe(8)
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain("<script>")
  })
  test("keeps local and remote CPU and memory telemetry", () => {
    const html = renderToStaticMarkup(<Overview data={{system:{cpu_percent:12,memory_percent:34},machines:{machines:[
      {name:"controller",info:{local:true}},{name:"worker",info:{cpu_percent:56,memory_percent:78}},
    ]}}} navigate={() => {}} />)
    for (const value of ["12.0%","34.0%","56.0%","78.0%"]) expect(html).toContain(value)
    expect(html).not.toContain("Capabilities")
  })
  test("uses Canonical action buttons without interpreting labels or attributes as markup", () => {
    const html = actionButton("<script>", 'x" onclick="bad()', {primary:true})
    expect(html).toContain("p-button--positive")
    expect(html).toContain("&lt;script&gt;")
    expect(html).not.toContain(' onclick="bad()')
  })
})
