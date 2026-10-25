// `request()` поверх `fetch`: база `/api` (nginx и dev-proxy срезают префикс до gateway),
// Bearer-токен из сессии, разбор ошибок в `ApiError`, разлогин на 401.

import { session, signOut } from './auth'
import { ApiError, parseApiError } from './errors'

export const API_BASE = '/api'

export type QueryValue = string | number | undefined | null
export type Query = Record<string, QueryValue>

export interface RequestOptions {
  body?: unknown
  query?: Query
  headers?: Record<string, string>
}

type UnauthorizedHandler = () => void

// Что делать после разлогина на 401 — ставит приложение (`redirectOnUnauthorized` в router.ts)
let unauthorizedHandler: UnauthorizedHandler = () => {}

export function onUnauthorized(handler: UnauthorizedHandler): void {
  unauthorizedHandler = handler
}

// Query-строка без пустых значений: `undefined`, `null` и `''` не отправляются
export function buildQuery(query: Query = {}): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== '') {
      params.append(key, String(value))
    }
  }
  const encoded = params.toString()
  return encoded ? `?${encoded}` : ''
}

async function readJson(response: Response): Promise<unknown> {
  const raw = await response.text()
  if (raw === '') {
    return undefined
  }
  try {
    return JSON.parse(raw)
  } catch {
    // Не JSON (например, HTML-страница 502 от nginx) — разбор по статусу
    return undefined
  }
}

export async function request<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json', ...options.headers }
  const token = session.token
  if (token !== null) {
    headers.Authorization = `Bearer ${token}`
  }
  let body: string | undefined
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(options.body)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}${buildQuery(options.query)}`, {
      method,
      headers,
      body,
    })
  } catch {
    throw ApiError.network()
  }

  const payload = await readJson(response)
  if (response.ok) {
    return payload as T
  }
  const error = parseApiError(response.status, payload)
  // Разлогин — только если токен был отправлен: 401 у `/auth/sign-in` — неверный пароль,
  // его показывает форма входа. 502/503/504 сессию не трогают.
  if (error.kind === 'unauthorized' && token !== null) {
    signOut()
    unauthorizedHandler()
  }
  throw error
}
