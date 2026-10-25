import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { loadSession } from './auth'
import * as api from './endpoints'
import { fetchCall, jsonResponse, mockFetch } from './testing'

describe('endpoints', () => {
  beforeEach(() => {
    localStorage.clear()
    loadSession()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('searchProducts: все параметры в query-строке', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { products: [], next_page_token: '' }))

    await api.searchProducts({
      query: 'чай',
      category: 'food',
      min_price_kopecks: 10_000,
      max_price_kopecks: 50_000,
      sort: 'price_asc',
      page_size: 20,
      page_token: 'abc',
    })

    const url = new URL(fetchCall(fetchMock).url, 'http://front')
    expect(url.pathname).toBe('/api/products')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      query: 'чай',
      category: 'food',
      min_price_kopecks: '10000',
      max_price_kopecks: '50000',
      sort: 'price_asc',
      page_size: '20',
      page_token: 'abc',
    })
  })

  it('searchProducts: пустые значения не отправляются', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { products: [], next_page_token: '' }))

    await api.searchProducts({ query: '', category: undefined, min_price_kopecks: 0, page_token: '' })

    expect(fetchCall(fetchMock).url).toBe('/api/products?min_price_kopecks=0')
  })

  it('listOrders: статус и токен страницы', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { orders: [], next_page_token: '' }))

    await api.listOrders({ status: 'DELIVERED', page_token: 'next' })

    expect(fetchCall(fetchMock).url).toBe('/api/orders?status=DELIVERED&page_token=next')
  })

  it('listOrders без фильтра — без query-строки', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { orders: [], next_page_token: '' }))
    await api.listOrders()
    expect(fetchCall(fetchMock).url).toBe('/api/orders')
  })

  it('checkout передаёт Idempotency-Key', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { order_id: 'o1' }))

    await api.checkout('key-123')

    const call = fetchCall(fetchMock)
    expect(call.url).toBe('/api/checkout')
    expect(call.init.method).toBe('POST')
    expect(call.headers.get('Idempotency-Key')).toBe('key-123')
    expect(call.init.body).toBeUndefined()
  })

  it.each([
    ['healthz', () => api.healthz(), 'GET', '/api/healthz', undefined],
    [
      'signUp',
      () => api.signUp({ email: 'a@b.c', password: 'p', role: 'BUYER' }),
      'POST',
      '/api/auth/sign-up',
      { email: 'a@b.c', password: 'p', role: 'BUYER' },
    ],
    [
      'confirmEmail',
      () => api.confirmEmail({ email: 'a@b.c', code: '123456' }),
      'POST',
      '/api/auth/confirm',
      { email: 'a@b.c', code: '123456' },
    ],
    [
      'signInRequest',
      () => api.signInRequest({ email: 'a@b.c', password: 'p' }),
      'POST',
      '/api/auth/sign-in',
      { email: 'a@b.c', password: 'p' },
    ],
    ['getMe', () => api.getMe(), 'GET', '/api/me', undefined],
    ['getProduct', () => api.getProduct('p/1'), 'GET', '/api/products/p%2F1', undefined],
    ['getCart', () => api.getCart(), 'GET', '/api/cart', undefined],
    [
      'addCartItem',
      () => api.addCartItem({ product_id: 'p1', quantity: 3 }),
      'POST',
      '/api/cart/items',
      { product_id: 'p1', quantity: 3 },
    ],
    ['removeCartItem', () => api.removeCartItem('p1'), 'DELETE', '/api/cart/items/p1', undefined],
    ['getOrder', () => api.getOrder('o1'), 'GET', '/api/orders/o1', undefined],
  ])('%s → %s %s', async (_name, call, method, url, body) => {
    const fetchMock = mockFetch(jsonResponse(200, {}))

    await call()

    const made = fetchCall(fetchMock)
    expect(made.init.method).toBe(method)
    expect(made.url).toBe(url)
    expect(made.init.body === undefined ? undefined : JSON.parse(String(made.init.body))).toEqual(
      body,
    )
  })
})
