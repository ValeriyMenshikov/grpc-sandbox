import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { session, signIn, signOut } from '../api/auth'
import * as api from '../api/endpoints'
import { parseApiError } from '../api/errors'
import { user } from '../api/testing'
import { mountApp } from '../testing'

vi.mock('../api/endpoints')
enableAutoUnmount(afterEach)

beforeEach(signOut)

afterEach(() => {
  signOut()
  vi.resetAllMocks()
})

describe('AppHeader', () => {
  it('без входа: ссылки на вход и регистрацию, /me не зовётся', async () => {
    const { wrapper } = await mountApp('/')

    const header = wrapper.find('header')
    expect(header.text()).toContain('Каталог')
    expect(header.text()).toContain('Корзина')
    expect(header.text()).toContain('Заказы')
    expect(header.text()).toContain('Вход')
    expect(header.find('.sign-out').exists()).toBe(false)
    expect(api.getMe).not.toHaveBeenCalled()
  })

  it('при входе зовёт /me и показывает имя, email и роль', async () => {
    signIn({ access_token: 't', expires_at: null, user: { ...user, display_name: 'Старое' } })
    vi.mocked(api.getMe).mockResolvedValue({ ...user, display_name: 'Продавец' })

    const { wrapper } = await mountApp('/')

    expect(api.getMe).toHaveBeenCalledOnce()
    const text = wrapper.find('.user').text()
    expect(text).toContain('Продавец')
    expect(text).toContain('seller@stand.local')
    expect(text).toContain('SELLER')
  })

  it('вход на странице подтягивает /me', async () => {
    vi.mocked(api.getMe).mockResolvedValue(user)
    const { wrapper } = await mountApp('/')

    signIn({ access_token: 't', expires_at: null, user })
    await flushPromises()

    expect(api.getMe).toHaveBeenCalledOnce()
    expect(wrapper.find('.sign-out').exists()).toBe(true)
  })

  it('сбой /me не ломает шапку: остаётся пользователь из сессии', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    vi.mocked(api.getMe).mockRejectedValue(parseApiError(503, undefined))

    const { wrapper } = await mountApp('/')

    expect(wrapper.find('.user').text()).toContain('Seller')
  })

  it('выход сбрасывает сессию и ведёт на вход', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    vi.mocked(api.getMe).mockResolvedValue(user)
    const { wrapper, router } = await mountApp('/')

    await wrapper.find('.sign-out').trigger('click')
    await flushPromises()

    expect(session.token).toBeNull()
    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(wrapper.find('.sign-out').exists()).toBe(false)
  })
})
