import { afterEach, describe, expect, it, vi } from 'vitest'

import { attemptKey, CHECKOUT_KEY_STORAGE, newKey } from './useCheckout'

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

afterEach(() => {
  sessionStorage.clear()
  vi.unstubAllGlobals()
})

describe('ключ попытки оформления', () => {
  it('один на попытку и переживает перезагрузку (sessionStorage)', () => {
    const key = attemptKey()

    expect(key).toMatch(UUID_V4)
    expect(attemptKey()).toBe(key)
    expect(sessionStorage.getItem(CHECKOUT_KEY_STORAGE)).toBe(key)
  })

  it('без randomUUID (не secure context) — UUID v4 из getRandomValues', () => {
    vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })

    const keys = new Set(Array.from({ length: 20 }, newKey))

    expect(keys.size).toBe(20)
    for (const key of keys) expect(key).toMatch(UUID_V4)
  })
})
