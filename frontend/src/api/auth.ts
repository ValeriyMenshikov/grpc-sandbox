// Сессия покупателя: токен и пользователь в памяти (reactive) и в `localStorage`,
// чтобы вход переживал перезагрузку страницы.

import { computed, reactive } from 'vue'

import type { SignInOut, User } from './types'

export const TOKEN_KEY = 'stand.token'
export const USER_KEY = 'stand.user'

interface Session {
  token: string | null
  user: User | null
}

export const session = reactive<Session>({ token: null, user: null })

export const isSignedIn = computed(() => session.token !== null)

function readUser(): User | null {
  const raw = localStorage.getItem(USER_KEY)
  if (raw === null) {
    return null
  }
  try {
    return JSON.parse(raw) as User
  } catch {
    // Испорченная запись — как будто её нет
    localStorage.removeItem(USER_KEY)
    return null
  }
}

// Перечитывает сессию из `localStorage`; вызывается при загрузке модуля и в тестах
export function loadSession(): void {
  session.token = localStorage.getItem(TOKEN_KEY)
  session.user = session.token === null ? null : readUser()
}

export function signIn(result: SignInOut): void {
  session.token = result.access_token
  localStorage.setItem(TOKEN_KEY, result.access_token)
  setUser(result.user)
}

// Обновляет пользователя (ответ `/me`), не трогая токен
export function setUser(user: User): void {
  session.user = user
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function signOut(): void {
  session.token = null
  session.user = null
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

loadSession()
