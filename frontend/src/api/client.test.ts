import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { loadSession, session, signIn } from './auth'
import { buildQuery, onUnauthorized, request } from './client'
import { ApiError } from './errors'
import { fetchCall, jsonResponse, mockFetch, user } from './testing'

describe('buildQuery', () => {
  it('пропускает пустые значения', () => {
    expect(buildQuery({ a: 'x', b: '', c: undefined, d: null, e: 0 })).toBe('?a=x&e=0')
  })

  it('пустой набор — без «?»', () => {
    expect(buildQuery({})).toBe('')
  })
})

describe('request', () => {
  let unauthorized: Mock<() => void>

  beforeEach(() => {
    localStorage.clear()
    loadSession()
    unauthorized = vi.fn<() => void>()
    onUnauthorized(unauthorized)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('ходит на /api и разбирает JSON', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { status: 'ok' }))

    await expect(request('GET', '/healthz')).resolves.toEqual({ status: 'ok' })
    expect(fetchCall(fetchMock).url).toBe('/api/healthz')
    expect(fetchCall(fetchMock).init.method).toBe('GET')
  })

  it('без токена заголовка Authorization нет', async () => {
    const fetchMock = mockFetch(jsonResponse(200, {}))
    await request('GET', '/products')
    expect(fetchCall(fetchMock).headers.has('Authorization')).toBe(false)
  })

  it('с токеном подставляет Authorization: Bearer', async () => {
    signIn({ access_token: 'secret', expires_at: null, user })
    const fetchMock = mockFetch(jsonResponse(200, {}))

    await request('GET', '/me')

    expect(fetchCall(fetchMock).headers.get('Authorization')).toBe('Bearer secret')
  })

  it('тело — JSON с Content-Type', async () => {
    const fetchMock = mockFetch(jsonResponse(200, {}))
    await request('POST', '/cart/items', { body: { product_id: 'p1', quantity: 2 } })

    const call = fetchCall(fetchMock)
    expect(call.headers.get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(call.init.body))).toEqual({ product_id: 'p1', quantity: 2 })
  })

  it('ошибка — ApiError с разбором тела', async () => {
    mockFetch(jsonResponse(404, { error: { code: 'NOT_FOUND', message: 'nope', details: [] } }))

    const error = await request('GET', '/orders/x').catch((e: unknown) => e)

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('NOT_FOUND')
  })

  it('401 с токеном — разлогин и редирект на вход', async () => {
    signIn({ access_token: 'expired', expires_at: null, user })
    mockFetch(
      jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'expired', details: [] } }),
    )

    await expect(request('GET', '/me')).rejects.toMatchObject({ kind: 'unauthorized' })
    expect(session.token).toBeNull()
    expect(session.user).toBeNull()
    expect(unauthorized).toHaveBeenCalledOnce()
  })

  it('401 без токена (неверный пароль) — без редиректа', async () => {
    mockFetch(
      jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'bad', details: [] } }),
    )

    await expect(request('POST', '/auth/sign-in', { body: {} })).rejects.toMatchObject({
      kind: 'unauthorized',
    })
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it.each([503, 504])('%d — без разлогина', async (status) => {
    signIn({ access_token: 'secret', expires_at: null, user })
    mockFetch(
      jsonResponse(status, { error: { code: 'UNAVAILABLE', message: 'down', details: [] } }),
    )

    await expect(request('GET', '/cart')).rejects.toMatchObject({ kind: 'unavailable' })
    expect(session.token).toBe('secret')
    expect(unauthorized).not.toHaveBeenCalled()
  })

  it('не-JSON ответ (HTML 502 от nginx) — unavailable', async () => {
    mockFetch(new Response('<html>Bad Gateway</html>', { status: 502 }))
    await expect(request('GET', '/products')).rejects.toMatchObject({ kind: 'unavailable' })
  })

  it('fetch упал — network', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(request('GET', '/products')).rejects.toMatchObject({ kind: 'network' })
  })
})
