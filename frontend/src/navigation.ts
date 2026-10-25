// Помощники навигации, общие для страниц и роутера.

import type { LocationQueryValue } from 'vue-router'

// Куда вернуться после входа: только свой путь (`/...`, не `//host`), иначе — каталог
export function safeNext(next: LocationQueryValue | LocationQueryValue[] | undefined): string {
  if (typeof next === 'string' && next.startsWith('/') && !next.startsWith('//')) {
    return next
  }
  return '/'
}
