import { beforeEach, describe, expect, it } from 'vitest'

import {
  isSignedIn,
  loadSession,
  session,
  setUser,
  signIn,
  signOut,
  TOKEN_KEY,
  USER_KEY,
} from './auth'
import { user } from './testing'

describe('auth', () => {
  beforeEach(() => {
    localStorage.clear()
    loadSession()
  })

  it('signIn сохраняет токен и пользователя в памяти и localStorage', () => {
    signIn({ access_token: 't1', expires_at: null, user })

    expect(session.token).toBe('t1')
    expect(session.user).toEqual(user)
    expect(isSignedIn.value).toBe(true)
    expect(localStorage.getItem(TOKEN_KEY)).toBe('t1')
    expect(JSON.parse(localStorage.getItem(USER_KEY) ?? '')).toEqual(user)
  })

  it('сессия переживает перезагрузку', () => {
    signIn({ access_token: 't1', expires_at: null, user })
    session.token = null
    session.user = null

    loadSession()

    expect(session.token).toBe('t1')
    expect(session.user).toEqual(user)
  })

  it('setUser обновляет пользователя, не трогая токен', () => {
    signIn({ access_token: 't1', expires_at: null, user })
    setUser({ ...user, display_name: 'Renamed' })

    expect(session.token).toBe('t1')
    expect(session.user?.display_name).toBe('Renamed')
  })

  it('signOut очищает память и localStorage', () => {
    signIn({ access_token: 't1', expires_at: null, user })
    signOut()

    expect(session.token).toBeNull()
    expect(session.user).toBeNull()
    expect(isSignedIn.value).toBe(false)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(localStorage.getItem(USER_KEY)).toBeNull()
  })

  it('испорченный пользователь в localStorage игнорируется', () => {
    localStorage.setItem(TOKEN_KEY, 't1')
    localStorage.setItem(USER_KEY, '{oops')

    loadSession()

    expect(session.token).toBe('t1')
    expect(session.user).toBeNull()
  })
})
