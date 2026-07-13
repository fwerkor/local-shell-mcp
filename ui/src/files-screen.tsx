import type { TextareaRenderable } from "@opentui/core"
import { useKeyboard } from "@opentui/react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { api, formatError } from "./api"
import { EmptyState, KeyHint, MachineSidebar, Modal, Panel, formatBytes, useVisibleRows } from "./components"
import { theme } from "./theme"
import type { FileEntry, FilePreview, FilesPayload, Machine } from "./types"

type Dialog =
  | { type: "none" }
  | { type: "input"; action: "rename" | "new-file" | "new-dir"; title: string; value: string }
  | { type: "confirm-delete"; entry: FileEntry }
  | { type: "editor"; entry: FileEntry; content: string }

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
  if (entry.type === "dir") return "▰"
  const lower = entry.name.toLowerCase()
  if (/\.(png|jpe?g|gif|webp|svg)$/.test(lower)) return "▧"
  if (/\.(zip|tar|gz|xz|7z)$/.test(lower)) return "◆"
  if (/\.(md|txt|rst|log)$/.test(lower)) return "≡"
  if (/\.(ts|tsx|js|jsx|py|rs|go|c|cpp|java|sh)$/.test(lower)) return "⌁"
  return "·"
}

function FileRows({ entries, selected, height }: { entries: FileEntry[]; selected: number; height: number }) {
  const { rows, start } = useVisibleRows(entries, selected, height)
  return (
    <box style={{ flexDirection: "column", flexGrow: 1 }}>
      {rows.map((entry, offset) => {
        const index = start + offset
        const active = index === selected
        return (
          <box
            key={entry.path}
            style={{
              height: 1,
              flexDirection: "row",
              paddingLeft: 1,
              paddingRight: 1,
              backgroundColor: active ? theme.selectedStrong : undefined,
            }}
          >
            <text fg={entry.type === "dir" ? theme.cyan : theme.muted} content={`${icon(entry)} `} />
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

function Preview({ preview, entry }: { preview: FilePreview | null; entry?: FileEntry }) {
  if (!entry) return <EmptyState title="No selection" detail="Choose an entry to inspect" />
  if (!preview) return <EmptyState title={entry.name} detail="Loading preview…" />
  if (preview.kind === "directory") {
    const entries = preview.entries || []
    return (
      <box style={{ flexDirection: "column", paddingLeft: 1, paddingRight: 1 }}>
        <text fg={theme.cyan} attributes={1} content={entry.name} />
        <text fg={theme.faint} content={`${entries.length} visible entries`} />
        <text fg={theme.borderBright} content="" />
        {entries.slice(0, 30).map((item) => (
          <text
            key={item.path}
            fg={item.type === "dir" ? theme.cyan : theme.muted}
            content={`${icon(item)} ${item.name}`}
          />
        ))}
      </box>
    )
  }
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
}: {
  machines: Machine[]
  machine: string
  onMachine: (machine: string) => void
  width: number
  height: number
  setStatus: (message: string) => void
}) {
  const [path, setPath] = useState(".")
  const [payload, setPayload] = useState<FilesPayload | null>(null)
  const [selected, setSelected] = useState(0)
  const [preview, setPreview] = useState<FilePreview | null>(null)
  const [showHidden, setShowHidden] = useState(false)
  const [dialog, setDialog] = useState<Dialog>({ type: "none" })
  const [clipboard, setClipboard] = useState<ClipboardState | null>(null)
  const [busy, setBusy] = useState(false)
  const editorRef = useRef<TextareaRenderable>(null)

  const entries = useMemo(
    () => (payload?.entries || []).filter((entry) => showHidden || !entry.hidden),
    [payload, showHidden],
  )
  const parentEntries = useMemo(
    () => (payload?.parent_entries || []).filter((entry) => showHidden || !entry.hidden),
    [payload, showHidden],
  )
  const current = entries[selected]
  const listHeight = Math.max(4, height - 10)

  useEffect(() => {
    setSelected((value) => Math.min(value, Math.max(0, entries.length - 1)))
  }, [entries.length])
  const compact = width < 105

  const refresh = useCallback(async () => {
    setBusy(true)
    try {
      const next = await api.files(machine, path)
      setPayload(next)
      setSelected((value) => Math.min(value, Math.max(0, next.entries.length - 1)))
      setStatus(`${machine}:${path}`)
    } catch (error) {
      setStatus(`Files: ${formatError(error)}`)
    } finally {
      setBusy(false)
    }
  }, [machine, path, setStatus])

  useEffect(() => {
    setSelected(0)
    void refresh()
  }, [refresh])

  useEffect(() => {
    let cancelled = false
    setPreview(null)
    if (!current) return
    const timer = setTimeout(() => {
      void api
        .filePreview(machine, current.path)
        .then((result) => {
          if (!cancelled) setPreview(result)
        })
        .catch((error) => {
          if (!cancelled) setStatus(`Preview: ${formatError(error)}`)
        })
    }, 80)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [current?.path, machine, setStatus])

  const closeDialog = () => setDialog({ type: "none" })

  const performInputAction = async (value: string) => {
    const trimmed = value.trim()
    if (!trimmed || dialog.type !== "input") return
    try {
      if (dialog.action === "rename") {
        if (!current) return
        await api.fileAction("rename", {
          machine,
          path: current.path,
          destination: joinPath(path, trimmed),
        })
      } else if (dialog.action === "new-file") {
        await api.fileAction("touch", { machine, path: joinPath(path, trimmed) })
      } else {
        await api.fileAction("mkdir", { machine, path: joinPath(path, trimmed) })
      }
      closeDialog()
      await refresh()
    } catch (error) {
      setStatus(`Files: ${formatError(error)}`)
    }
  }

  const openEditor = async (entry: FileEntry) => {
    if (entry.type === "dir") return
    setBusy(true)
    try {
      const content = await api.fileContent(machine, entry.path)
      setDialog({ type: "editor", entry, content: String(content.content || "") })
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
    onMachine(machines[next]!.name)
    setPath(".")
    setClipboard(null)
  }

  useKeyboard((key) => {
    if (dialog.type === "editor") {
      if (key.name === "escape") closeDialog()
      if (key.ctrl && key.name === "s") {
        const content = editorRef.current?.plainText ?? dialog.content
        void api
          .fileAction("write", { machine, path: dialog.entry.path, content, overwrite: true })
          .then(async () => {
            closeDialog()
            await refresh()
            setStatus(`Saved ${dialog.entry.name}`)
          })
          .catch((error) => setStatus(`Save: ${formatError(error)}`))
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
            machine,
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

    if (key.name === "j" || key.name === "down") setSelected((value) => Math.min(entries.length - 1, value + 1))
    else if (key.name === "k" || key.name === "up") setSelected((value) => Math.max(0, value - 1))
    else if (key.name === "g" && key.shift) setSelected(Math.max(0, entries.length - 1))
    else if (key.name === "g") setSelected(0)
    else if (key.name === "h" || key.name === "left" || key.name === "backspace") setPath(payload?.parent || ".")
    else if (key.name === "l" || key.name === "right" || key.name === "return") {
      if (current?.type === "dir") setPath(current.path)
      else if (current) void openEditor(current)
    } else if (key.name === "." || key.name === "period") setShowHidden((value) => !value)
    else if (key.name === "r" && !key.shift) current && setDialog({ type: "input", action: "rename", title: "Rename", value: current.name })
    else if (key.name === "n" && key.shift) setDialog({ type: "input", action: "new-dir", title: "New directory", value: "" })
    else if (key.name === "n") setDialog({ type: "input", action: "new-file", title: "New file", value: "" })
    else if (key.name === "d") current && setDialog({ type: "confirm-delete", entry: current })
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
        {!compact && <MachineSidebar machines={machines} selected={machine} />}
        <box style={{ flexGrow: 1, flexDirection: "column" }}>
          <box style={{ height: 2, flexDirection: "row", alignItems: "center", paddingLeft: 1 }}>
            <text fg={theme.faint} content={`${machine} / `} />
            <text fg={theme.cyan} attributes={1} content={path} />
            <box style={{ flexGrow: 1 }} />
            {busy && <text fg={theme.yellow} content="syncing  " />}
            {clipboard && (
              <text
                fg={clipboard.mode === "copy" ? theme.green : theme.orange}
                content={`${clipboard.mode}: ${clipboard.machine}:${clipboard.path}  `}
              />
            )}
          </box>
          <box style={{ flexGrow: 1, flexDirection: "row", gap: 1 }}>
            {!compact && (
              <Panel title="Parent" style={{ width: "24%", paddingTop: 1 }}>
                <FileRows entries={parentEntries} selected={Math.max(0, parentEntries.findIndex((entry) => entry.path === path))} height={listHeight} />
              </Panel>
            )}
            <Panel title="Current" active style={{ width: compact ? "48%" : "38%", paddingTop: 1 }}>
              {entries.length ? (
                <FileRows entries={entries} selected={selected} height={listHeight} />
              ) : (
                <EmptyState title="Empty directory" detail="n file · N directory" />
              )}
            </Panel>
            <Panel title={current ? `Preview · ${current.name}` : "Preview"} style={{ flexGrow: 1, paddingTop: 1 }}>
              <Preview preview={preview} entry={current} />
            </Panel>
          </box>
        </box>
      </box>
      <KeyHint
        items={[
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
        <Modal title={`Edit · ${dialog.entry.name}`} width={Math.max(70, width - 12)} height={Math.max(18, height - 8)}>
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
