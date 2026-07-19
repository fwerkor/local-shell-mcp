const root = document.documentElement
const finePointer = window.matchMedia("(pointer: fine)")
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)")
const filterSvg = document.querySelector(".glass-filters")

let frame = 0
let targetX = 0.5
let targetY = 0.28
let currentX = targetX
let currentY = targetY

function render(): void {
  frame = 0
  const ease = reducedMotion.matches ? 1 : 0.14
  currentX += (targetX - currentX) * ease
  currentY += (targetY - currentY) * ease

  const x = (currentX - 0.5) * 2
  const y = (currentY - 0.5) * 2
  root.style.setProperty("--glass-x", `${(currentX * 100).toFixed(2)}%`)
  root.style.setProperty("--glass-y", `${(currentY * 100).toFixed(2)}%`)
  root.style.setProperty("--parallax-x", `${(x * 13).toFixed(2)}px`)
  root.style.setProperty("--parallax-y", `${(y * 10).toFixed(2)}px`)
  root.style.setProperty("--counter-x", `${(-x * 8).toFixed(2)}px`)
  root.style.setProperty("--counter-y", `${(-y * 6).toFixed(2)}px`)
  root.style.setProperty("--parallax-soft-x", `${(x * 8).toFixed(2)}px`)
  root.style.setProperty("--parallax-soft-y", `${(y * 6).toFixed(2)}px`)
  root.style.setProperty("--parallax-subtle-x", `${(x * 5).toFixed(2)}px`)
  root.style.setProperty("--parallax-subtle-y", `${(y * 4).toFixed(2)}px`)
  root.style.setProperty("--counter-soft-x", `${(-x * 6).toFixed(2)}px`)
  root.style.setProperty("--counter-soft-y", `${(-y * 5).toFixed(2)}px`)
  root.style.setProperty("--mark-rotate-x", `${(-y * 2.4).toFixed(2)}deg`)
  root.style.setProperty("--mark-rotate-y", `${(x * 2.8).toFixed(2)}deg`)

  if (Math.abs(targetX - currentX) > 0.001 || Math.abs(targetY - currentY) > 0.001) {
    frame = requestAnimationFrame(render)
  }
}

function schedule(): void {
  if (!frame) frame = requestAnimationFrame(render)
}

function syncFilterMotion(): void {
  if (!(filterSvg instanceof SVGSVGElement)) return
  if (reducedMotion.matches || !finePointer.matches) filterSvg.pauseAnimations()
  else filterSvg.unpauseAnimations()
}

function setPointer(clientX: number, clientY: number): void {
  targetX = Math.min(1, Math.max(0, clientX / Math.max(1, window.innerWidth)))
  targetY = Math.min(1, Math.max(0, clientY / Math.max(1, window.innerHeight)))
  schedule()
}

window.addEventListener(
  "pointermove",
  (event) => {
    if (!finePointer.matches || reducedMotion.matches) return
    setPointer(event.clientX, event.clientY)
  },
  { passive: true },
)

window.addEventListener(
  "pointerleave",
  () => {
    targetX = 0.5
    targetY = 0.28
    schedule()
  },
  { passive: true },
)

finePointer.addEventListener("change", () => {
  targetX = 0.5
  targetY = 0.28
  syncFilterMotion()
  schedule()
})

reducedMotion.addEventListener("change", () => {
  syncFilterMotion()
  schedule()
})

syncFilterMotion()
schedule()
