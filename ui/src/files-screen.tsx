import type { OptimizedBuffer, Renderable, TextareaRenderable } from "@opentui/core"
import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, MachineSidebar, Modal, Panel, formatBytes, useVisibleRows } from "./components"
import { clampIndex, nextPreviewMeasurement, payloadMatches } from "./state-utils"
import { screenTheme, theme } from "./theme"
import type { FileEntry, FilePreview, FilesPayload, Machine } from "./types"

const colors = screenTheme.Files

type Dialog =
  | { type: "none" }
  | {
      type: "input"
      action: "rename" | "new-file" | "new-dir"
      title: string
      value: string
      machine: string
      directory: string
      entry?: FileEntry
    }
  | { type: "confirm-delete"; machine: string; entry: FileEntry }
  | { type: "editor"; machine: string; entry: FileEntry; content: string; sha256: string }

interface ClipboardState {
  mode: "copy" | "move"
  machine: string
  path: string
}

function joinPath(parent: string, name: string): string {
  if (parent === "/") return `/${name}`
  if (!parent || parent === ".") return name
  return `${parent.replace(/[\\/]$/, "")}/${name}`
}

function icon(entry: FileEntry): string {
  if (entry.type === "link") return "↗"
  if (entry.type === "dir") return "▰"
  const lower = entry.name.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg)$/.test(lower)) return "▧"
  if (/\.(zip|tar|gz|xz|7z)$/.test(lower)) return "◆"
  if (/\.(md|txt|rst|log)$/.test(lower)) return "≡"
  if (/\.(ts|tsx|js|jsx|py|rs|go|c|cpp|java|sh)$/.test(lower)) return "⌁"
  return "·"
}

function FileRows({
  entries,
  selected,
  height,
  onSelect,
}: {
  entries: FileEntry[]
  selected: number
  height: number
  onSelect?: (entry: FileEntry, index: number) => void
}) {
  const { rows, start } = useVisibleRows(entries, selected, height)
  return (
    <box style={{ flexDirection: "column", flexGrow: 1 }}>
      {rows.map((entry, offset) => {
        const index = start + offset
        const active = index === selected
        return (
          <box
            key={entry.path}
            onMouseDown={() => onSelect?.(entry, index)}
            style={{
              height: 1,
              flexDirection: "row",
              paddingLeft: 1,
              paddingRight: 1,
              backgroundColor: active ? colors.selected : undefined,
            }}
          >
            <text fg={entry.type === "dir" ? colors.accent : theme.muted} content={`${icon(entry)} `} />
            <text
              fg={active ? theme.text : entry.hidden ? theme.faint : theme.muted}
              attributes={active ? 1 : 0}
              content={entry.name}
            />
            <box style={{ flexGrow: 1 }} />
            <text fg={theme.faint} content={entry.type === "dir" ? "dir" : formatBytes(entry.size)} />
          </box>
        )
      })}
    </box>
  )
}

function ImagePreview({ preview, entry }: { preview: FilePreview; entry: FileEntry }) {
  const pixelWidth = Number(preview.width || 0)
  const pixelHeight = Number(preview.height || 0)
  const cellWidth = Number(preview.cell_width || pixelWidth * 2)
  const cellHeight = Number(preview.cell_height || Math.ceil(pixelHeight / 2))
  let pixels: Uint8Array
  try {
    pixels = Uint8Array.from(Buffer.from(String(preview.rgba || ""), "base64"))
  } catch {
    return <EmptyState title={entry.name} detail="Invalid image preview data" />
  }
  if (!pixelWidth || !pixelHeight || pixels.byteLength !== pixelWidth * pixelHeight * 4) {
    return <EmptyState title={entry.name} detail="Invalid image preview dimensions" />
  }
  const sourceWidth = Number(preview.original_width || pixelWidth)
  const sourceHeight = Number(preview.original_height || pixelHeight)
  const drawPixels = function (this: Renderable, buffer: OptimizedBuffer) {
    buffer.drawSuperSampleBuffer(
      this.screenX,
      this.screenY,
      pixels as never,
      pixels.byteLength,
      "rgba8unorm",
      pixelWidth * 4,
    )
  }
  return (
    <box style={{ flexGrow: 1, flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
      <box
        style={{ width: cellWidth, height: cellHeight, flexShrink: 0 }}
        renderAfter={drawPixels}
      />
      <text
        fg={theme.faint}
        content={`${sourceWidth}×${sourceHeight} · ${formatBytes(Number(preview.bytes || entry.size || 0))}`}
      />
    </box>
  )
}

function Preview({ preview, entry }: { preview: FilePreview | null; entry?: FileEntry }) {
  if (!entry) return <EmptyState title="No selection" detail="Choose an entry to inspect" />
  if (!preview) return <EmptyState title={entry.name} detail="Loading preview…" />
  if (preview.kind === "directory") {
    const entries = preview.entries || []
    return (
      <box style={{ flexDirection: "column", paddingLeft: 1, paddingRight: 1 }}>
        <text fg={colors.accent} attributes={1} content={entry.name} />
        <text fg={theme.faint} content={`${entries.length} visible entries`} />
        <text fg={theme.borderBright} content="" />
        {entries.slice(0, 30).map((item) => (
          <text
            key={item.path}
            fg={item.type === "dir" ? colors.accent : theme.muted}
            content={`${icon(item)} ${item.name}`}
          />
        ))}
      </box>
    )
  }
  if (preview.kind === "image") return <ImagePreview preview={preview} entry={entry} />
  const text = String(preview.content || preview.preview || "")
  return (
    <scrollbox
      focused={false}
      style={{ flexGrow: 1, paddingLeft: 1, paddingRight: 1 }}
      scrollY
      verticalScrollbarOptions={{ visible: true }}
    >
      <text fg={preview.kind === "binary" ? theme.yellow : theme.muted} content={text || "Empty file"} />
    </scrollbox>
  )
}

export function FilesScreen({
  machines,
  machine,
  onMachine,
  width,
  height,
  setStatus,
  keyboardEnabled,
  onInteractionLockChange,
}: {
  machines: Machine[]
  machine: string
  onMachine: (machine: string) => void
  width: number
  height: number
  setStatus: (message: string) => void
  keyboardEnabled: boolean
  onInteractionLockChange: (locked: boolean) => void
}) {
  const [path, setPath] = useState(".")
  const [payload, setPayload] = useState<FilesPayload | null>(null)
  const [selected, setSelected] = useState(0)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [dialog, setDialog] = useState<Dialog>({ type: "none" })
  const [clipboard, setClipboard] = useState<ClipboardState | null>(null)
  const [busy, setBusy] = useState(false)
  const [narrowPane, setNarrowPane] = useState<"list" | "preview">("list")
  const [previewBounds, setPreviewBounds] = useState<{ columns: number; rows: number } | null>(null)
  const editorRef = useRef<TextareaRenderable>(null)
  const refreshRequest = useRef(0)
  const refreshController = useRef<AbortController | null>(null)
  const measuredPreviewViewport = useRef("")
  const machineRef = useRef(machine)
  machineRef.current = machine
  const activePayload = payloadMatches(payload, machine, path) ? payload : null

  const entries = useMemo(
    () => (activePayload?.entries || []).filter((entry) => showHidden || !entry.hidden),
    [activePayload, showHidden],
  )
  const parentEntries = useMemo(
    () => (activePayload?.parent_entries || []).filter((entry) => showHidden || !entry.hidden),
    [activePayload, showHidden],
  )
  const current = entries[selected]
  const listHeight = Math.max(4, height - 10)

  useEffect(() => {
    setSelected((value) => clampIndex(value, entries.length))
  }, [entries.length])
  const narrow = width < 70
  const compact = width < 105
  const fallbackPreviewColumns = Math.max(
    8,
    narrow ? width - 8 : compact ? Math.floor(width * 0.45) - 6 : Math.floor(width * 0.4) - 8,
  )
  const previewColumns = previewBounds?.columns || fallbackPreviewColumns
  const previewRows = previewBounds?.rows || Math.max(4, listHeight - 3)
  const previewViewport = `${width}x${height}:${narrow ? narrowPane : "split"}`

  const refresh = useCallback(async () => {
    const requestId = ++refreshRequest.current
    refreshController.current?.abort()
    const controller = new AbortController()
    refreshController.current = controller
    setBusy(true)
    try {
      const next = await api.files(machine, path, controller.signal)
      if (requestId !== refreshRequest.current || controller.signal.aborted) return
      setPayload(next)
      setSelected((value) => clampIndex(value, next.entries.length))
      setStatus(`${machine}:${path}`)
    } catch (error) {
      if (requestId === refreshRequest.current && !controller.signal.aborted) {
        setStatus(`Files: ${formatError(error)}`)
      }
    } finally {
      if (requestId === refreshRequest.current) {
        refreshController.current = null
        setBusy(false)
      }
    }
  }, [machine, path, setStatus])

  useEffect(() => {
    setPayload(null)
    setPreview(null)
    setSelected(0)
    setDialog({ type: "none" })
    setClipboard(null)
    setNarrowPane("list")
  }, [machine])

  useEffect(() => {
    setSelected(0)
    void refresh()
    return () => {
      refreshRequest.current += 1
      refreshController.current?.abort()
      refreshController.current = null
    }
  }, [refresh])

  useEffect(() => {
    setPreview(null)
  }, [current?.path, machine])

  useEffect(() => {
    const currentPath = current?.path
    if (!currentPath) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      void api
        .filePreview(machine, currentPath, previewColumns, previewRows, controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setPreview(result)
        })
        .catch((error) => {
          if (!controller.signal.aborted) setStatus(`Preview: ${formatError(error)}`)
        })
    }, 80)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [current?.path, machine, previewColumns, previewRows, setStatus])

  useEffect(() => {
    onInteractionLockChange(dialog.type !== "none")
    return () => onInteractionLockChange(false)
  }, [dialog.type, onInteractionLockChange])

  const closeDialog = () => setDialog({ type: "none" })

  const performInputAction = async (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || dialog.type !== "input") return
    if (dialog.machine !== machine) {
      closeDialog()
      return
    }
    try {
      if (dialog.action === "rename") {
        if (!dialog.entry) return
        await api.fileAction("rename", {
          machine: dialog.machine,
          path: dialog.entry.path,
          destination: joinPath(dialog.directory, trimmed),
        })
      } else if (dialog.action === "new-file") {
        await api.fileAction("touch", {
          machine: dialog.machine,
          path: joinPath(dialog.directory, trimmed),
        })
      } else {
        await api.fileAction("mkdir", {
          machine: dialog.machine,
          path: joinPath(dialog.directory, trimmed),
        })
      }
      closeDialog()
      await refresh()
    } catch (error) {
      setStatus(`Files: ${formatError(error)}`)
    }
  }

  const openEditor = async (entry: FileEntry) => {
    if (entry.type === "dir") return
    const targetMachine = machine
    setBusy(true)
    try {
      const content = await api.fileContent(targetMachine, entry.path)
      if (machineRef.current !== targetMachine) return
      if (!content.sha256) throw new Error("The editor did not receive a file revision")
      setDialog({
        type: "editor",
        machine: targetMachine,
        entry,
        content: String(content.content || ""),
        sha256: content.sha256,
      })
    } catch (error) {
      setStatus(`Edit: ${formatError(error)}`)
    } finally {
      setBusy(false)
    }
  }

  const pasteClipboard = async () => {
    if (!clipboard) return
    if (clipboard.machine !== machine) {
      setStatus("Paste: clipboard belongs to another machine")
      return
    }
    const destination = joinPath(path, clipboard.path.split(/[\\/]/).filter(Boolean).at(-1) || "item")
    try {
      await api.fileAction(clipboard.mode === "copy" ? "copy" : "move", {
        machine,
        path: clipboard.path,
        destination,
      })
      if (clipboard.mode === "move") setClipboard(null)
      await refresh()
    } catch (error) {
      setStatus(`Paste: ${formatError(error)}`)
    }
  }

  const switchMachine = (delta: number) => {
    if (!machines.length) return
    const index = Math.max(0, machines.findIndex((item) => item.name === machine))
    const next = (index + delta + machines.length) % machines.length
    setPayload(null)
    setPreview(null)
    setDialog({ type: "none" })
    setClipboard(null)
    setPath(".")
    setNarrowPane("list")
    onMachine(machines[next]!.name)
  }

  useKeyboard((key) => {
    if (!keyboardEnabled) return
    if (dialog.type !== "none" && dialog.machine !== machine) {
      closeDialog()
      return
    }
    if (dialog.type === "editor") {
      if (key.name === "escape") closeDialog()
      if (key.ctrl && key.name === "s") {
        const content = editorRef.current?.plainText ?? dialog.content
        void api
          .fileAction("write", {
            machine: dialog.machine,
            path: dialog.entry.path,
            content,
            overwrite: true,
            expected_sha256: dialog.sha256,
          })
          .then(async () => {
            closeDialog()
            await refresh()
            setStatus(`Saved ${dialog.entry.name}`)
          })
          .catch((error) => {
            const detail = formatError(error)
            if (detail.includes("reload before saving")) {
              setStatus(`Save conflict: ${detail}`)
            } else {
              setStatus(`Save: ${detail}`)
            }
          })
      }
      return
    }
    if (dialog.type === "input") {
      if (key.name === "escape") closeDialog()
      return
    }
    if (dialog.type === "confirm-delete") {
      if (key.name === "escape" || key.name === "n") closeDialog()
      if (key.name === "y" || key.name === "return") {
        void api
          .fileAction("delete", {
            machine: dialog.machine,
            path: dialog.entry.path,
            recursive: dialog.entry.type === "dir",
          })
          .then(async () => {
            closeDialog()
            await refresh()
          })
          .catch((error) => setStatus(`Delete: ${formatError(error)}`))
      }
      return
    }

    if (narrow && key.name === "tab") {
      key.preventDefault()
      setNarrowPane((value) => (value === "list" ? "preview" : "list"))
      return
    }
    if (key.name === "j" || key.name === "down") {
      setSelected((value) => clampIndex(value + 1, entries.length))
    }
    else if (key.name === "k" || key.name === "up") setSelected((value) => Math.max(0, value - 1))
    else if (key.name === "g" && key.shift) setSelected(Math.max(0, entries.length - 1))
    else if (key.name === "g") setSelected(0)
    else if (key.name === "h" || key.name === "left" || key.name === "backspace") setPath(activePayload?.parent || ".")
    else if (key.name === "l" || key.name === "right" || key.name === "return") {
      if (current?.type === "dir") setPath(current.path)
      else if (current) void openEditor(current)
    } else if (key.name === "." || key.name === "period") setShowHidden((value) => !value)
    else if (key.name === "r" && !key.shift) current && setDialog({
      type: "input",
      action: "rename",
      title: "Rename",
      value: current.name,
      machine,
      directory: path,
      entry: current,
    })
    else if (key.name === "n" && key.shift) setDialog({
      type: "input",
      action: "new-dir",
      title: "New directory",
      value: "",
      machine,
      directory: path,
    })
    else if (key.name === "n") setDialog({
      type: "input",
      action: "new-file",
      title: "New file",
      value: "",
      machine,
      directory: path,
    })
    else if (key.name === "d") current && setDialog({ type: "confirm-delete", machine, entry: current })
    else if (key.name === "e") current && current.type !== "dir" && void openEditor(current)
    else if (key.name === "y") current && setClipboard({ mode: "copy", machine, path: current.path })
    else if (key.name === "x") current && setClipboard({ mode: "move", machine, path: current.path })
    else if (key.name === "p") void pasteClipboard()
    else if (key.name === "[") switchMachine(-1)
    else if (key.name === "]") switchMachine(1)
    else if (key.name === "r" && key.shift) void refresh()
  })

  return (
    <box style={{ flexGrow: 1, flexDirection: "column" }}>
      <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
        {!compact && (
          <MachineSidebar
            machines={machines}
            selected={machine}
            accent={colors.accent}
            selectedColor={colors.selected}
            onSelect={(nextMachine) => {
              if (nextMachine === machine) return
              setPayload(null)
              setPreview(null)
              setDialog({ type: "none" })
              setClipboard(null)
              setPath(".")
              onMachine(nextMachine)
            }}
          />
        )}
        <box style={{ flexGrow: 1, flexDirection: "column" }}>
          <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1 }}>
            <text fg={theme.faint} content={`${machine} / `} />
            <text fg={colors.accent} attributes={1} content={path} />
            <box style={{ flexGrow: 1 }} />
            {busy && <text fg={theme.yellow} content="syncing  " />}
            {clipboard && (
              <text
                fg={clipboard.mode === "copy" ? theme.green : theme.orange}
                content={`${clipboard.mode}: ${clipboard.machine}:${clipboard.path}  `}
              />
            )}
          </box>
          {narrow && (
            <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1 }}>
              {(["list", "preview"] as const).map((pane) => {
                const active = narrowPane === pane
                return (
                  <box
                    key={pane}
                    onMouseDown={() => setNarrowPane(pane)}
                    style={{
                      height: 1,
                      marginRight: 1,
                      paddingLeft: 1,
                      paddingRight: 1,
                      backgroundColor: active ? colors.selected : theme.panelAlt,
                    }}
                  >
                    <text fg={active ? colors.accent : theme.muted} attributes={active ? 1 : 0} content={pane === "list" ? "LIST" : "PREVIEW"} />
                  </box>
                )
              })}
              <box style={{ flexGrow: 1 }} />
              <text fg={theme.faint} content="Tab switch  " />
            </box>
          )}
          <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
            {!compact && (
              <Panel title="Parent" style={{ width: "24%", paddingTop: 1 }}>
                <FileRows
                  entries={parentEntries}
                  selected={Math.max(0, parentEntries.findIndex((entry) => entry.path === path))}
                  height={listHeight}
                  onSelect={(entry) => {
                    if (entry.type === "dir") setPath(entry.path)
                  }}
                />
              </Panel>
            )}
            {(!narrow || narrowPane === "list") && (
              <Panel title="Current" active accent={colors.accent} activeBackground={colors.panel} style={{ width: narrow ? "100%" : compact ? "48%" : "38%", paddingTop: 1 }}>
                {entries.length ? (
                  <FileRows
                    entries={entries}
                    selected={selected}
                    height={listHeight}
                    onSelect={(_entry, index) => setSelected(index)}
                  />
                ) : (
                  <EmptyState title="Empty directory" detail="n file · N directory" />
                )}
              </Panel>
            )}
            {(!narrow || narrowPane === "preview") && (
              <Panel title={current ? `Preview · ${current.name}` : "Preview"} style={{ flexGrow: 1, width: narrow ? "100%" : undefined, paddingTop: 1 }}>
                <box
                  style={{ flexGrow: 1, flexDirection: "column" }}
                  onSizeChange={function (this: Renderable) {
                    const measurement = nextPreviewMeasurement(
                      measuredPreviewViewport.current,
                      previewViewport,
                      this.width,
                      this.height,
                    )
                    if (!measurement) return
                    measuredPreviewViewport.current = measurement.viewport
                    setPreviewBounds({ columns: measurement.columns, rows: measurement.rows })
                  }}
                >
                  <Preview preview={preview} entry={current} />
                </box>
              </Panel>
            )}
          </box>
        </box>
      </box>
      <KeyHint
        accent={colors.accent}
        items={[
          ...(narrow ? ([['Tab', 'list/preview']] as Array<[string, string]>) : []),
          ["j/k", "move"],
          ["h/l", "parent/open"],
          ["n/N", "new"],
          ["r", "rename"],
          ["e", "edit"],
          ["y/x/p", "copy/move/paste"],
          ["d", "delete"],
          [".", "hidden"],
        ]}
      />
      {dialog.type === "input" && (
        <Modal title={dialog.title} height={7}>
          <text fg={theme.muted} content={dialog.action === "rename" ? "Enter the new name" : "Enter a name"} />
          <box style={{ height: 3, border: true, borderColor: theme.borderBright, paddingLeft: 1, paddingRight: 1 }}>
            <input focused value={dialog.value} onSubmit={(value: unknown) => void performInputAction(typeof value === "string" ? value : "")} />
          </box>
          <text fg={theme.faint} content="Enter confirm · Esc cancel" />
        </Modal>
      )}
      {dialog.type === "confirm-delete" && (
        <Modal title="Delete" height={7}>
          <text fg={theme.red} attributes={1} content={`Delete ${dialog.entry.name}?`} />
          <text fg={theme.muted} content={dialog.entry.type === "dir" ? "This recursively removes the directory." : "This removes the file."} />
          <text fg={theme.faint} content="y / Enter confirm · n / Esc cancel" />
        </Modal>
      )}
      {dialog.type === "editor" && (
        <Modal
          title={`Edit · ${dialog.entry.name}`}
          width={Math.max(38, Math.min(120, width - 6))}
          height={Math.max(12, height - 6)}
        >
          <textarea
            ref={editorRef}
            focused
            initialValue={dialog.content}
            style={{ flexGrow: 1, backgroundColor: theme.bg, textColor: theme.text }}
          />
          <text fg={theme.faint} content="Ctrl+S save · Esc cancel" />
        </Modal>
      )}
    </box>
  )
}
