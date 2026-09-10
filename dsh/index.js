import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import {
  ListToolsResultSchema,
  ToolListChangedNotificationSchema,
} from '@modelcontextprotocol/sdk/types.js'
import { z } from 'zod'

export const name = 'local-shell-mcp-dsh'
export const inject = ['tools', 'systemPrompt', 'webServer', 'agents']

const DEFAULT_URL = 'http://127.0.0.1:8765/mcp'
const DEFAULT_TOOL_CALL_TIMEOUT_MS = 120_000
const DEFAULT_KEEPALIVE_INTERVAL_MS = 30_000
const MAX_SESSION_CONNECTIONS = 64
const MAX_PUBLIC_NAME_LENGTH = 64
const HASH_LENGTH = 12
const INVALID_NAME_CHARS = /[^A-Za-z0-9_-]/g
const RAW_RESULT_SCHEMA = z.record(z.string(), z.unknown())
const LIVE_WORKSPACE_HTML = new URL('../src/local_shell_mcp/ui_static/live-workspace.html', import.meta.url)
const LIVE_VIEW_PATH = '/lsm/live-workspace'
const LIVE_CONFIG_PATH = '/lsm/live-config'
const SESSION_AFFINITY_HEADER = 'x-local-shell-mcp-session-affinity'

function resolveConfig(raw = {}) {
  const url = String(raw.url || DEFAULT_URL)
  const parsed = new URL(url)
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`local-shell-mcp-dsh: url must use http or https, got ${parsed.protocol}`)
  }
  const headers = raw.headers && typeof raw.headers === 'object' && !Array.isArray(raw.headers)
    ? Object.fromEntries(Object.entries(raw.headers).map(([key, value]) => [String(key), String(value)]))
    : {}
  const timeout = Number(raw.toolCallTimeoutMs ?? DEFAULT_TOOL_CALL_TIMEOUT_MS)
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new Error('local-shell-mcp-dsh: toolCallTimeoutMs must be a positive finite number')
  }
  const keepAliveIntervalMs = Number(raw.keepAliveIntervalMs ?? DEFAULT_KEEPALIVE_INTERVAL_MS)
  if (!Number.isFinite(keepAliveIntervalMs) || keepAliveIntervalMs < 5_000) {
    throw new Error('local-shell-mcp-dsh: keepAliveIntervalMs must be at least 5000')
  }
  let browserUrl = null
  if (raw.browserUrl) {
    const browser = new URL(String(raw.browserUrl))
    if (browser.protocol !== 'http:' && browser.protocol !== 'https:') {
      throw new Error(`local-shell-mcp-dsh: browserUrl must use http or https, got ${browser.protocol}`)
    }
    if (browser.username || browser.password) {
      throw new Error('local-shell-mcp-dsh: browserUrl must not contain credentials')
    }
    browserUrl = browser.origin
  }
  return {
    url,
    headers,
    browserUrl,
    toolCallTimeoutMs: timeout,
    keepAliveIntervalMs,
    reconnectInitialDelayMs: Math.max(100, Number(raw.reconnectInitialDelayMs ?? 500)),
    reconnectMaxDelayMs: Math.max(1_000, Number(raw.reconnectMaxDelayMs ?? 30_000)),
  }
}

function publicToolName(rawName) {
  const joined = `mcp__lsm__${rawName}`
  const normalized = joined.replace(INVALID_NAME_CHARS, '_')
  if (normalized === joined && normalized.length <= MAX_PUBLIC_NAME_LENGTH) return normalized
  const hash = createHash('sha256').update(`lsm\0${rawName}`).digest('hex').slice(0, HASH_LENGTH)
  return `${normalized.slice(0, MAX_PUBLIC_NAME_LENGTH - HASH_LENGTH - 1)}_${hash}`
}

function appOnlyTool(tool) {
  const visibility = tool?._meta?.ui?.visibility
  return Array.isArray(visibility) && visibility.length > 0 && !visibility.includes('model')
}

function extractText(content, rawName) {
  const parts = []
  for (const value of content) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
      parts.push('[unsupported content type: unknown]')
      continue
    }
    switch (value.type) {
      case 'text':
        if (typeof value.text === 'string') parts.push(value.text)
        break
      case 'image':
        parts.push(`[image: ${value.mimeType || 'unknown'}, content discarded]`)
        break
      case 'audio':
        parts.push(`[audio: ${value.mimeType || 'unknown'}, content discarded]`)
        break
      case 'resource':
      case 'resource_link':
        parts.push('[resource: content discarded]')
        break
      default:
        parts.push(`[unsupported content type: ${String(value.type || 'unknown')}]`)
    }
  }
  return parts.join('\n') || `(${rawName} returned no text content)`
}

function outputFor(rawName) {
  return {
    schema: {
      type: 'object',
      properties: {
        content: { type: 'array', items: {} },
        structuredContent: {},
      },
      required: ['content'],
      additionalProperties: false,
    },
    render(_args, value) {
      return [{ type: 'text', text: extractText(value.content || [], rawName) }]
    },
  }
}

function asArgs(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

async function callRaw(client, rawName, args, { signal, timeout }) {
  return await client.request(
    { method: 'tools/call', params: { name: rawName, arguments: asArgs(args) } },
    RAW_RESULT_SCHEMA,
    { ...(signal ? { signal } : {}), timeout },
  )
}

function normalizeToolResult(result, rawName) {
  if (!Array.isArray(result.content)) {
    const text = 'toolResult' in result ? JSON.stringify(result.toolResult) : '(no output)'
    if (result.isError === true) throw new Error(typeof text === 'string' ? text : '(no output)')
    return {
      content: [{ type: 'text', text: typeof text === 'string' ? text : '(no output)' }],
      ...(result.structuredContent !== undefined ? { structuredContent: result.structuredContent } : {}),
    }
  }
  const content = result.content
  if (result.isError === true) throw new Error(extractText(content, rawName))
  return {
    content,
    ...(result.structuredContent !== undefined ? { structuredContent: result.structuredContent } : {}),
  }
}

async function listTools(client) {
  const tools = []
  let cursor
  do {
    const response = await client.request(
      { method: 'tools/list', ...(cursor === undefined ? {} : { params: { cursor } }) },
      ListToolsResultSchema,
    )
    tools.push(...response.tools)
    cursor = response.nextCursor
  } while (cursor)
  return tools
}

function htmlJson(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026')
}

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload)
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body),
  })
  res.end(body)
}

function validSessionId(value) {
  return typeof value === 'string' && value.length > 0 && value.length <= 256 && !/[\u0000-\u001f\u007f]/.test(value)
}

export async function apply(ctx, rawConfig = {}) {
  const config = resolveConfig(rawConfig)
  let disposed = false
  let catalog = null
  let catalogReconnectTimer = null
  let catalogReconnectDelay = config.reconnectInitialDelayMs
  let toolDisposers = new Map()
  let promptDisposer = null
  let promptText = null
  let catalogSync = Promise.resolve()
  const sessionConnections = new Map()

  function transport(extraHeaders = {}) {
    return new StreamableHTTPClientTransport(new URL(config.url), {
      requestInit: { headers: { ...config.headers, ...extraHeaders } },
    })
  }

  function sessionAffinity(sessionId) {
    return `dsh-${createHash('sha256').update(`session\0${sessionId}`).digest('hex')}`
  }

  async function connectClient(label, onClose, configure, extraHeaders) {
    const client = new Client(
      { name: `local-shell-mcp-dsh-${label}`, version: '4.3.1' },
      { capabilities: {} },
    )
    if (configure) configure(client)
    client.onerror = (error) => {
      if (!disposed) ctx.logger.warn(`local-shell-mcp-dsh(${label}): ${String(error)}`)
    }
    let keepAliveTimer = null
    let keepAliveRunning = false
    const stopKeepAlive = () => {
      if (keepAliveTimer) clearInterval(keepAliveTimer)
      keepAliveTimer = null
    }
    client.onclose = () => {
      stopKeepAlive()
      if (!disposed) onClose?.()
    }
    await client.connect(transport(extraHeaders))
    keepAliveTimer = setInterval(() => {
      if (disposed || keepAliveRunning) return
      keepAliveRunning = true
      void client.ping().catch((error) => {
        if (!disposed) ctx.logger.warn(`local-shell-mcp-dsh(${label}): keepalive failed: ${String(error)}`)
        stopKeepAlive()
        void client.close().catch(() => {})
      }).finally(() => {
        keepAliveRunning = false
      })
    }, config.keepAliveIntervalMs)
    keepAliveTimer.unref?.()
    return client
  }

  function sessionRecordInUse(sessionId, record) {
    return sessionConnections.get(sessionId) === record
  }

  async function closeSessionRecord(sessionId, record) {
    if (sessionRecordInUse(sessionId, record)) sessionConnections.delete(sessionId)
    let client = record.client
    if (!client && record.promise) {
      try { client = await record.promise } catch { return }
    }
    if (!client) return
    try { await client.close() } catch { /* already closed */ }
  }

  async function makeRoomForSession() {
    if (sessionConnections.size < MAX_SESSION_CONNECTIONS) return
    const candidates = [...sessionConnections.entries()]
      .filter(([sessionId]) => ctx.agents.get(sessionId) === undefined)
      .sort((a, b) => a[1].lastUsed - b[1].lastUsed)
    const victim = candidates[0]
    if (!victim) {
      throw new Error(`local-shell-mcp-dsh: ${MAX_SESSION_CONNECTIONS} live DSH sessions already own LSM connections`)
    }
    await closeSessionRecord(victim[0], victim[1])
  }

  async function sessionClient(sessionId) {
    if (!validSessionId(sessionId)) throw new Error('local-shell-mcp-dsh: invalid DSH session id')
    const existing = sessionConnections.get(sessionId)
    if (existing) {
      existing.lastUsed = Date.now()
      return await existing.promise
    }
    await makeRoomForSession()
    const record = { client: null, promise: null, lastUsed: Date.now() }
    const promise = connectClient(`session:${sessionId}`, () => {
      if (sessionRecordInUse(sessionId, record)) sessionConnections.delete(sessionId)
    }, undefined, {
      [SESSION_AFFINITY_HEADER]: sessionAffinity(sessionId),
    }).then((client) => {
      record.client = client
      return client
    }).catch((error) => {
      if (sessionRecordInUse(sessionId, record)) sessionConnections.delete(sessionId)
      throw error
    })
    record.promise = promise
    sessionConnections.set(sessionId, record)
    return await promise
  }

  ctx.on('session/disposed', (session) => {
    const sessionId = String(session.id)
    const record = sessionConnections.get(sessionId)
    if (record) void closeSessionRecord(sessionId, record)
  }, { global: true })

  function updateInstructions(client) {
    const instructions = client.getInstructions()?.trim() || ''
    if (instructions === promptText) return
    promptDisposer?.()
    promptDisposer = null
    promptText = instructions
    if (instructions) {
      promptDisposer = ctx.systemPrompt.section({
        name: 'mcp:local-shell-mcp',
        order: 90,
        text: instructions,
      })
    }
  }

  async function syncTools(client) {
    const remoteTools = await listTools(client)
    const definitions = new Map()
    for (const tool of remoteTools) {
      if (appOnlyTool(tool)) continue
      const rawName = String(tool.name)
      const publicName = publicToolName(rawName)
      if (definitions.has(publicName)) {
        throw new Error(`local-shell-mcp-dsh: duplicate normalized tool name ${publicName}`)
      }
      definitions.set(publicName, {
        name: publicName,
        description: tool.description || '',
        parameters: tool.inputSchema,
        output: outputFor(rawName),
        execute: async (args, exec) => {
          if (tool.execution?.taskSupport === 'required') {
            throw new Error(`Tool "${rawName}" requires task-based execution, which this bridge does not support`)
          }
          const sessionId = exec.agent?.session?.id ? String(exec.agent.session.id) : '__unscoped__'
          const clientForSession = await sessionClient(sessionId)
          const result = await callRaw(clientForSession, rawName, args, {
            signal: exec.signal,
            timeout: config.toolCallTimeoutMs,
          })
          return normalizeToolResult(result, rawName)
        },
      })
    }

    for (const dispose of toolDisposers.values()) dispose()
    const next = new Map()
    try {
      for (const [publicName, definition] of definitions) {
        next.set(publicName, ctx.tools.register(definition))
      }
    } catch (error) {
      for (const dispose of next.values()) dispose()
      toolDisposers = new Map()
      throw error
    }
    toolDisposers = next
    updateInstructions(client)
    ctx.logger.info(`local-shell-mcp-dsh: synchronized ${next.size} LSM tools`)
  }

  function enqueueCatalogSync(client) {
    const run = catalogSync.then(async () => {
      if (disposed || catalog !== client) return
      await syncTools(client)
    })
    catalogSync = run.catch(() => {})
    return run
  }

  function scheduleCatalogReconnect() {
    if (disposed || catalogReconnectTimer) return
    const delay = catalogReconnectDelay
    catalogReconnectDelay = Math.min(config.reconnectMaxDelayMs, Math.max(delay * 2, config.reconnectInitialDelayMs))
    catalogReconnectTimer = setTimeout(() => {
      catalogReconnectTimer = null
      void connectCatalog()
    }, delay)
    catalogReconnectTimer.unref?.()
  }

  async function connectCatalog() {
    if (disposed || catalog) return
    try {
      const client = await connectClient('catalog', () => {
        if (catalog === client) {
          catalog = null
          scheduleCatalogReconnect()
        }
      }, (candidate) => {
        candidate.setNotificationHandler(ToolListChangedNotificationSchema, async () => {
          if (catalog !== candidate || disposed) return
          try {
            await enqueueCatalogSync(candidate)
          } catch (error) {
            ctx.logger.warn(`local-shell-mcp-dsh: tool re-sync failed: ${String(error)}`)
          }
        })
      })
      if (disposed) {
        try { await client.close() } catch { /* already closed */ }
        return
      }
      catalog = client
      await enqueueCatalogSync(client)
      catalogReconnectDelay = config.reconnectInitialDelayMs
    } catch (error) {
      if (!disposed) {
        catalog = null
        ctx.logger.warn(`local-shell-mcp-dsh: initial/catalog connection failed: ${String(error)}`)
        scheduleCatalogReconnect()
      }
    }
  }

  async function liveConfig(sessionId, query) {
    const client = await sessionClient(sessionId)
    const args = {
      machine: query.get('machine') || 'local',
      cwd: query.get('cwd') || '.',
      ...(query.get('live_id') ? { live_id: query.get('live_id') } : {}),
      ...(query.get('session_id') ? { session_id: query.get('session_id') } : {}),
    }
    const result = await callRaw(client, 'live_workspace_reconnect', args, {
      signal: AbortSignal.timeout(config.toolCallTimeoutMs),
      timeout: config.toolCallTimeoutMs,
    })
    if (result.isError === true) throw new Error(extractText(Array.isArray(result.content) ? result.content : [], 'live_workspace_reconnect'))
    const structured = result.structuredContent && typeof result.structuredContent === 'object'
      ? result.structuredContent
      : {}
    const hidden = result._meta?.['local-shell-mcp/live'] || {}
    const token = String(hidden.token || '')
    const apiBase = String(hidden.apiBase || structured.api_base || '')
    if (!token || !apiBase) throw new Error('local-shell-mcp-dsh: LSM did not return Live Workspace credentials')
    return {
      token,
      apiBase: config.browserUrl || apiBase,
      uiPath: String(hidden.uiPath || structured.ui_path || '/ui'),
      liveId: String(hidden.liveId || structured.live_id || ''),
      sessionId: String(structured.session_id || ''),
      machine: String(structured.machine || args.machine),
      cwd: String(structured.cwd || args.cwd),
    }
  }

  const liveHtmlSource = await readFile(LIVE_WORKSPACE_HTML, 'utf8')

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: LIVE_VIEW_PATH,
    handler: async (req, res) => {
      if (req.method !== 'GET' && req.method !== 'HEAD') {
        res.writeHead(405, { allow: 'GET, HEAD' })
        res.end()
        return
      }
      const requestUrl = new URL(req.url || LIVE_VIEW_PATH, 'http://dsh.local')
      const sessionId = requestUrl.searchParams.get('session') || ''
      if (!validSessionId(sessionId)) {
        res.writeHead(400)
        res.end('Invalid DSH session id')
        return
      }
      const bootstrap = `<script>window.__LSM_DSH_BOOTSTRAP__=${htmlJson({ sessionId, configEndpoint: LIVE_CONFIG_PATH })};</script>`
      const html = liveHtmlSource.replace('<body>', `<body>${bootstrap}`)
      res.writeHead(200, {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-store',
        'content-security-policy': "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src http: https: ws: wss:; img-src data: blob: http: https:; font-src data:; worker-src blob:; object-src 'none'; base-uri 'none'; frame-ancestors 'self'",
      })
      if (req.method === 'HEAD') res.end()
      else res.end(html)
    },
  }), 'local-shell-mcp-dsh: Live Workspace view')

  ctx.effect(() => ctx.webServer.register({
    kind: 'exact',
    path: LIVE_CONFIG_PATH,
    handler: async (req, res) => {
      if (req.method !== 'GET') {
        res.writeHead(405, { allow: 'GET' })
        res.end()
        return
      }
      try {
        const requestUrl = new URL(req.url || LIVE_CONFIG_PATH, 'http://dsh.local')
        const sessionId = requestUrl.searchParams.get('session') || ''
        if (!validSessionId(sessionId)) {
          sendJson(res, 400, { ok: false, message: 'Invalid DSH session id' })
          return
        }
        const data = await liveConfig(sessionId, requestUrl.searchParams)
        sendJson(res, 200, { ok: true, data })
      } catch (error) {
        sendJson(res, 502, { ok: false, message: error instanceof Error ? error.message : String(error) })
      }
    },
  }), 'local-shell-mcp-dsh: Live Workspace credentials')

  ctx.effect(() => async () => {
    disposed = true
    if (catalogReconnectTimer) clearTimeout(catalogReconnectTimer)
    catalogReconnectTimer = null
    promptDisposer?.()
    promptDisposer = null
    for (const dispose of toolDisposers.values()) dispose()
    toolDisposers = new Map()
    const currentCatalog = catalog
    catalog = null
    if (currentCatalog) {
      try { await currentCatalog.close() } catch { /* already closed */ }
    }
    const records = [...sessionConnections.entries()]
    sessionConnections.clear()
    await Promise.allSettled(records.map(async ([, record]) => {
      let client = record.client
      if (!client) {
        try { client = await record.promise } catch { return }
      }
      try { await client.close() } catch { /* already closed */ }
    }))
    await catalogSync
  }, 'local-shell-mcp-dsh: connections')

  await connectCatalog()
}
