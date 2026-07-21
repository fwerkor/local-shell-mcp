import { theme } from "./theme"

export type HighlightKind =
  | "plain"
  | "key"
  | "string"
  | "number"
  | "literal"
  | "keyword"
  | "comment"
  | "heading"
  | "symbol"
  | "operator"
  | "punctuation"

export interface HighlightToken {
  text: string
  kind: HighlightKind
}

type HighlightMode = "auto" | "plain" | "json" | "code" | "config" | "markdown"

const CODE_EXTENSIONS = new Set([
  "c", "cc", "cpp", "cxx", "h", "hh", "hpp", "hxx",
  "go", "java", "js", "jsx", "kt", "kts", "mjs", "mts",
  "py", "rb", "rs", "sh", "bash", "zsh", "swift", "ts", "tsx", "zig",
])

const CONFIG_EXTENSIONS = new Set(["env", "ini", "properties", "toml", "yaml", "yml"])

const KEYWORDS = new Set([
  "abstract", "as", "async", "await", "break", "case", "catch", "class", "const", "continue",
  "def", "defer", "do", "else", "enum", "except", "export", "extends", "false", "finally", "fn",
  "for", "from", "func", "function", "if", "implements", "import", "in", "instanceof", "interface",
  "let", "match", "mod", "new", "nil", "none", "null", "package", "pass", "private", "protected",
  "public", "raise", "return", "self", "static", "struct", "super", "switch", "this", "throw", "trait",
  "true", "try", "type", "typeof", "undefined", "use", "var", "while", "with", "yield",
])

function pushToken(tokens: HighlightToken[], text: string, kind: HighlightKind): void {
  if (!text) return
  const previous = tokens[tokens.length - 1]
  if (previous?.kind === kind) previous.text += text
  else tokens.push({ text, kind })
}

function fileExtension(filename: string): string {
  const base = filename.toLowerCase().split(/[\\/]/).pop() || ""
  if (base === "dockerfile" || base.startsWith("dockerfile.")) return "dockerfile"
  if (base === "makefile" || base.endsWith(".mk")) return "makefile"
  const index = base.lastIndexOf(".")
  return index >= 0 ? base.slice(index + 1) : ""
}

export function highlightModeForFilename(filename = ""): HighlightMode {
  const extension = fileExtension(filename)
  if (extension === "json" || extension === "jsonl") return "json"
  if (extension === "md" || extension === "markdown" || extension === "rst") return "markdown"
  if (CONFIG_EXTENSIONS.has(extension)) return "config"
  if (CODE_EXTENSIONS.has(extension) || extension === "dockerfile" || extension === "makefile") return "code"
  return "plain"
}

function isJson(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed) return false
  try {
    JSON.parse(trimmed)
    return true
  } catch {
    return false
  }
}

export function tokenizeJson(text: string): HighlightToken[] {
  const tokens: HighlightToken[] = []
  const pattern = /"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\b(?:true|false|null)\b|[{}\[\],:]|\s+|./gy
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const value = match[0]
    if (value.startsWith("\"")) {
      const rest = text.slice(pattern.lastIndex)
      pushToken(tokens, value, /^\s*:/.test(rest) ? "key" : "string")
    } else if (/^-?\d/.test(value)) {
      pushToken(tokens, value, "number")
    } else if (/^(?:true|false|null)$/.test(value)) {
      pushToken(tokens, value, "literal")
    } else if (/^[{}\[\],:]$/.test(value)) {
      pushToken(tokens, value, "punctuation")
    } else {
      pushToken(tokens, value, "plain")
    }
  }
  return tokens
}

function tokenizeCode(text: string, filename: string): HighlightToken[] {
  const tokens: HighlightToken[] = []
  const extension = fileExtension(filename)
  const hashComments = new Set(["py", "rb", "sh", "bash", "zsh", "makefile", "dockerfile"])
  const slashComments = !hashComments.has(extension)
  let index = 0

  while (index < text.length) {
    const start = index
    const char = text[index]!

    if (/\s/.test(char)) {
      while (index < text.length && /\s/.test(text[index]!)) index += 1
      pushToken(tokens, text.slice(start, index), "plain")
      continue
    }

    if (text.startsWith("/*", index)) {
      const end = text.indexOf("*/", index + 2)
      index = end < 0 ? text.length : end + 2
      pushToken(tokens, text.slice(start, index), "comment")
      continue
    }

    if ((slashComments && text.startsWith("//", index)) || (hashComments.has(extension) && char === "#")) {
      const end = text.indexOf("\n", index)
      index = end < 0 ? text.length : end
      pushToken(tokens, text.slice(start, index), "comment")
      continue
    }

    if (char === "\"" || char === "'" || char === "`") {
      const triple = char !== "`" && text.slice(index, index + 3) === char.repeat(3)
      const delimiter = triple ? char.repeat(3) : char
      index += delimiter.length
      while (index < text.length) {
        if (text[index] === "\\") {
          index += Math.min(2, text.length - index)
          continue
        }
        if (text.startsWith(delimiter, index)) {
          index += delimiter.length
          break
        }
        index += 1
      }
      pushToken(tokens, text.slice(start, index), "string")
      continue
    }

    const number = text.slice(index).match(/^(?:0[xob][\da-f]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)/i)
    if (number) {
      index += number[0].length
      pushToken(tokens, number[0], "number")
      continue
    }

    const identifier = text.slice(index).match(/^[A-Za-z_$][\w$]*/)
    if (identifier) {
      index += identifier[0].length
      const lower = identifier[0].toLowerCase()
      const next = text.slice(index).match(/^\s*./)?.[0].trim()
      pushToken(tokens, identifier[0], KEYWORDS.has(lower) ? "keyword" : next === "(" ? "symbol" : "plain")
      continue
    }

    index += 1
    pushToken(tokens, char, /[=+\-*/%<>!&|^~?:]/.test(char) ? "operator" : "punctuation")
  }

  return tokens
}

function tokenizeConfigValue(text: string, tokens: HighlightToken[]): void {
  let consumed = 0
  const pattern = /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|-?\d+(?:\.\d+)?|\b(?:true|false|null|yes|no|on|off)\b|\s+|./giy
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const value = match[0]
    if (value === "#" || value === ";") {
      pushToken(tokens, text.slice(consumed), "comment")
      return
    }
    consumed = pattern.lastIndex
    if (value.startsWith("\"") || value.startsWith("'")) pushToken(tokens, value, "string")
    else if (/^-?\d/.test(value)) pushToken(tokens, value, "number")
    else if (/^(?:true|false|null|yes|no|on|off)$/i.test(value)) pushToken(tokens, value, "literal")
    else pushToken(tokens, value, "plain")
  }
}

function tokenizeConfig(text: string): HighlightToken[] {
  const tokens: HighlightToken[] = []
  for (const line of text.match(/.*(?:\n|$)/g) || []) {
    if (!line) continue
    const section = line.match(/^(\s*)(\[[^\]\n]+\])(.*)$/)
    if (section) {
      pushToken(tokens, section[1]!, "plain")
      pushToken(tokens, section[2]!, "heading")
      tokenizeConfigValue(section[3]!, tokens)
      continue
    }
    const assignment = line.match(/^(\s*(?:-\s*)?)([A-Za-z0-9_.-]+)(\s*[:=]\s*)(.*)$/)
    if (assignment) {
      pushToken(tokens, assignment[1]!, "plain")
      pushToken(tokens, assignment[2]!, "key")
      pushToken(tokens, assignment[3]!, "punctuation")
      tokenizeConfigValue(assignment[4]!, tokens)
      continue
    }
    if (/^\s*[#;]/.test(line)) pushToken(tokens, line, "comment")
    else pushToken(tokens, line, "plain")
  }
  return tokens
}

function tokenizeMarkdownInline(text: string, tokens: HighlightToken[]): void {
  const pattern = /`[^`\n]+`|\[[^\]\n]+\]\([^)\n]+\)|\*\*[^*\n]+\*\*|__[^_\n]+__|\s+|./gy
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text))) {
    const value = match[0]
    if (value.startsWith("`")) pushToken(tokens, value, "string")
    else if (value.startsWith("[")) pushToken(tokens, value, "symbol")
    else if (value.startsWith("**") || value.startsWith("__")) pushToken(tokens, value, "keyword")
    else pushToken(tokens, value, "plain")
  }
}

function tokenizeMarkdown(text: string): HighlightToken[] {
  const tokens: HighlightToken[] = []
  let fenced = false
  for (const line of text.match(/.*(?:\n|$)/g) || []) {
    if (!line) continue
    if (/^\s*```/.test(line)) {
      fenced = !fenced
      pushToken(tokens, line, "comment")
      continue
    }
    if (fenced) {
      pushToken(tokens, line, "string")
      continue
    }
    const heading = line.match(/^(\s*#{1,6}\s+)(.*)$/)
    if (heading) {
      pushToken(tokens, heading[1]!, "punctuation")
      pushToken(tokens, heading[2]!, "heading")
      continue
    }
    const marker = line.match(/^(\s*(?:>|[-*+] |\d+\. ))(.*)$/)
    if (marker) {
      pushToken(tokens, marker[1]!, "punctuation")
      tokenizeMarkdownInline(marker[2]!, tokens)
      continue
    }
    tokenizeMarkdownInline(line, tokens)
  }
  return tokens
}

export function tokenizeHighlightedText(
  text: string,
  filename = "",
  mode: HighlightMode = "auto",
): HighlightToken[] {
  const resolved = mode === "auto"
    ? (isJson(text) ? "json" : highlightModeForFilename(filename))
    : mode
  if (resolved === "json") return tokenizeJson(text)
  if (resolved === "code") return tokenizeCode(text, filename)
  if (resolved === "config") return tokenizeConfig(text)
  if (resolved === "markdown") return tokenizeMarkdown(text)
  return [{ text, kind: "plain" }]
}

function tokenColor(kind: HighlightKind, baseColor: string): string {
  if (kind === "key") return theme.blue
  if (kind === "string") return theme.green
  if (kind === "number") return theme.orange
  if (kind === "literal" || kind === "keyword") return theme.magenta
  if (kind === "comment" || kind === "punctuation") return theme.faint
  if (kind === "heading") return theme.cyan
  if (kind === "symbol") return theme.blue
  if (kind === "operator") return theme.yellow
  return baseColor
}

export function HighlightedText({
  content,
  filename = "",
  mode = "auto",
  baseColor = theme.muted,
}: {
  content: string
  filename?: string
  mode?: HighlightMode
  baseColor?: string
}) {
  const tokens = tokenizeHighlightedText(content, filename, mode)
  return (
    <text>
      {tokens.map((token, index) => (
        <span
          key={`${index}-${token.kind}`}
          fg={tokenColor(token.kind, baseColor)}
          attributes={token.kind === "heading" ? 1 : 0}
        >
          {token.text}
        </span>
      ))}
    </text>
  )
}
