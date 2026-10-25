import { afterEach, describe, expect, it, vi } from 'vitest'

import type { Cart } from '../api/types'
import { attemptKey, cartFingerprint, CHECKOUT_KEY_STORAGE, newKey } from './useCheckout'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

const money = { currency_code: 'RUB', units: 100, nanos: 0 }

function cart(...items: [string, number][]): Cart {
  return {
    items: items.map(([product_id, quantity]) => ({
      product_id,
      name: product_id,
      quantity,
      unit_price: money,
      available: 10,
    })),
    total: money,
  }
}

afterEach(() => {
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('ключ попытки оформления', () => {
  it('один на попытку и переживает перезагрузку (sessionStorage)', () => {
    const key = attemptKey(cart(['p1', 2]))

    expect(key).toMatch(UUID_V4)
    expect(attemptKey(cart(['p1', 2]))).toBe(key)
    expect(JSON.parse(sessionStorage.getItem(CHECKOUT_KEY_STORAGE) ?? '')).toEqual({
      key,
      cart: 'p1:2',
    })
  })

  it('корзина изменилась — новый ключ (старый мог уже создать заказ)', () => {
    const key = attemptKey(cart(['p1', 2]))

    expect(attemptKey(cart(['p1', 3]))).not.toBe(key)
    expect(attemptKey(cart(['p1', 2], ['p2', 1]))).not.toBe(key)
  })

  it('слепок не зависит от порядка позиций', () => {
    expect(cartFingerprint(cart(['p2', 1], ['p1', 2]))).toBe(cartFingerprint(cart(['p1', 2], ['p2', 1])))
  })

  it('испорченное значение в sessionStorage — новый ключ', () => {
    sessionStorage.setItem(CHECKOUT_KEY_STORAGE, 'not-json')

    expect(attemptKey(cart(['p1', 1]))).toMatch(UUID_V4)
  })

  it('без randomUUID (не secure context) — UUID v4 из getRandomValues', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })

    const keys = new Set(Array.from({ length: 20 }, newKey))

    expect(keys.size).toBe(20)
    for (const key of keys) expect(key).toMatch(UUID_V4)
  })
})
