import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { session, signOut } from '../api/auth'
import * as api from '../api/endpoints'
import { parseApiError } from '../api/errors'
import { user } from '../api/testing'
import { mountApp } from '../testing'

vi.mock('../api/endpoints')
enableAutoUnmount(afterEach)

beforeEach(() => {
  signOut()
  vi.mocked(api.getMe).mockResolvedValue(user)
})

afterEach(() => {
  signOut()
  vi.resetAllMocks()
})

describe('SignInPage', () => {
  it('подсказывает сид-продавца', async () => {
    const { wrapper } = await mountApp('/sign-in')

    expect(wrapper.text()).toContain('seller@stand.local')
    expect(wrapper.text()).toContain('seller-password')
  })

  it('вход сохраняет токен и возвращает на исходный маршрут', async () => {
    vi.mocked(api.signInRequest).mockResolvedValue({
      access_token: 'token-1',
      expires_at: null,
      user,
    })
    const { wrapper, router } = await mountApp('/cart')
    expect(router.currentRoute.value.fullPath).toBe('/sign-in?next=/cart')

    await wrapper.find('input[name=email]').setValue('seller@stand.local')
    await wrapper.find('input[name=password]').setValue('seller-password')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.signInRequest).toHaveBeenCalledWith({
      email: 'seller@stand.local',
      password: 'seller-password',
    })
    expect(session.token).toBe('token-1')
    expect(localStorage.getItem('stand.token')).toBe('token-1')
    expect(router.currentRoute.value.fullPath).toBe('/cart')
  })

  it('без next ведёт в каталог', async () => {
    vi.mocked(api.signInRequest).mockResolvedValue({ access_token: 't', expires_at: null, user })
    const { wrapper, router } = await mountApp('/sign-in')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('catalog')
  })

  it('ошибка входа показывается, сессия не создаётся', async () => {
    vi.mocked(api.signInRequest).mockRejectedValue(
      parseApiError(400, {
        error: {
          code: 'FAILED_PRECONDITION',
          message: 'Email is not confirmed',
          details: [
            {
              '@type': 'type.googleapis.com/google.rpc.PreconditionFailure',
              violations: [
                { type: 'EMAIL_NOT_CONFIRMED', subject: 'user:a@b.c', description: 'confirm email' },
              ],
            },
          ],
        },
      }),
    )
    const { wrapper, router } = await mountApp('/sign-in')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const box = wrapper.find('[role=alert]')
    expect(box.text()).toContain('Email is not confirmed')
    expect(box.text()).toContain('EMAIL_NOT_CONFIRMED')
    expect(session.token).toBeNull()
    expect(router.currentRoute.value.name).toBe('sign-in')
  })
})

describe('SignUpPage', () => {
  it('регистрация ведёт на подтверждение с email', async () => {
    vi.mocked(api.signUp).mockResolvedValue({ ...user, email: 'new@stand.local', role: 'BUYER' })
    const { wrapper, router } = await mountApp('/sign-up')

    await wrapper.find('input[name=email]').setValue('new@stand.local')
    await wrapper.find('input[name=password]').setValue('secret-123')
    await wrapper.find('input[name=display_name]').setValue('Новый')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.signUp).toHaveBeenCalledWith({
      email: 'new@stand.local',
      password: 'secret-123',
      display_name: 'Новый',
      role: 'BUYER',
    })
    expect(router.currentRoute.value.name).toBe('confirm')
    expect(router.currentRoute.value.query.email).toBe('new@stand.local')
  })

  it('выбранная роль SELLER уходит в запрос', async () => {
    vi.mocked(api.signUp).mockResolvedValue(user)
    const { wrapper } = await mountApp('/sign-up')

    await wrapper.find('input[value=SELLER]').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(vi.mocked(api.signUp).mock.calls[0]?.[0].role).toBe('SELLER')
  })

  it('ошибка регистрации показывается', async () => {
    vi.mocked(api.signUp).mockRejectedValue(
      parseApiError(409, { error: { code: 'ALREADY_EXISTS', message: 'User already exists' } }),
    )
    const { wrapper, router } = await mountApp('/sign-up')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role=alert]').text()).toContain('User already exists')
    expect(router.currentRoute.value.name).toBe('sign-up')
  })
})

describe('ConfirmPage', () => {
  it('ссылка на ящик стенда и email из query, без redis-cli', async () => {
    const { wrapper } = await mountApp('/confirm?email=new@stand.local')

    const link = wrapper.find('a[href="/mail/"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('target')).toBe('_blank')
    expect(wrapper.find('.mail-note').text()).toContain('отправлено на new@stand.local')
    expect(wrapper.text()).toContain('15 минут')
    expect(wrapper.text()).not.toContain('redis-cli')
    expect(wrapper.text()).not.toContain('Redis')
  })

  it('успешный код ведёт на вход', async () => {
    vi.mocked(api.confirmEmail).mockResolvedValue(user)
    const { wrapper, router } = await mountApp('/confirm?email=new@stand.local')

    await wrapper.find('input[name=code]').setValue(' 123456 ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(api.confirmEmail).toHaveBeenCalledWith({ email: 'new@stand.local', code: '123456' })
    expect(router.currentRoute.value.name).toBe('sign-in')
    expect(wrapper.find('input[name=email]').element).toHaveProperty('value', 'new@stand.local')
  })

  it('неверный код показывает ошибку', async () => {
    vi.mocked(api.confirmEmail).mockRejectedValue(
      parseApiError(400, { error: { code: 'INVALID_ARGUMENT', message: 'Invalid code' } }),
    )
    const { wrapper } = await mountApp('/confirm?email=new@stand.local')

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role=alert]').text()).toContain('Invalid code')
  })
})
