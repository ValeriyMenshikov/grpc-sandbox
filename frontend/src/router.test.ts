import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import { signIn, signOut } from './api/auth'
import { user } from './api/testing'
import { safeNext } from './navigation'
import { createAppRouter } from './router'

describe('guard роутера', () => {
  beforeEach(signOut)
  afterEach(signOut)

  it.each(['/cart', '/orders', '/orders/42?x=1'])('без токена %s → вход с next', async (path) => {
    const router = createAppRouter(createMemoryHistory())

    await router.push(path)

    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(router.currentRoute.value.query.next).toBe(path)
  })

  it('с токеном пускает на защищённый маршрут', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    const router = createAppRouter(createMemoryHistory())

    await router.push('/orders/42')

    expect(router.currentRoute.value.name).toBe('order')
  })

  it('открытые маршруты доступны без токена', async () => {
    const router = createAppRouter(createMemoryHistory())

    await router.push('/products/p1')

    expect(router.currentRoute.value.name).toBe('product')
  })
})

describe('safeNext', () => {
  it('пропускает только свой путь', () => {
    expect(safeNext('/orders/1?a=b')).toBe('/orders/1?a=b')
    expect(safeNext('//evil.example')).toBe('/')
    expect(safeNext('https://evil.example')).toBe('/')
    expect(safeNext(undefined)).toBe('/')
    expect(safeNext(['/cart'])).toBe('/')
  })
})
