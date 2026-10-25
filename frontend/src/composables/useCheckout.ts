// Оформление заказа: один `Idempotency-Key` на попытку — повторный клик и ретрай после ошибки
// идут с тем же ключом, новый ключ появляется после успеха или когда корзина изменилась.
// Ключ лежит в `sessionStorage` вместе со слепком корзины, чтобы перезагрузка посреди попытки
// не создала второй заказ, а ключ потерянного ответа не переиграл старый заказ для новой корзины.
import { ref, type Ref } from 'vue'
import { useRouter } from 'vue-router'

import { checkout } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import type { Cart } from '../api/types'

export const CHECKOUT_KEY_STORAGE = 'stand.checkout.idempotency-key'

interface StoredAttempt {
  key: string
  cart: string
}

// UUID v4. `crypto.randomUUID` есть только в secure context (https, localhost) — стенд,
// открытый по IP из локальной сети, им не является, там ключ собирается из `getRandomValues`
export function newKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

// Слепок корзины: позиции и количества, без цен (цены не делают попытку другой)
export function cartFingerprint(cart: Cart): string {
  return cart.items
    .map((item) => `${item.product_id}:${item.quantity}`)
    .sort()
    .join(',')
}

function storedAttempt(): StoredAttempt | null {
  const raw = sessionStorage.getItem(CHECKOUT_KEY_STORAGE)
  if (raw === null) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      typeof (parsed as StoredAttempt).key === 'string' &&
      typeof (parsed as StoredAttempt).cart === 'string'
    ) {
      return parsed as StoredAttempt
    }
  } catch {
    // Испорченное значение — как будто ключа нет
  }
  return null
}

// Ключ текущей попытки для этой корзины; нет или корзина другая — заводится новый
export function attemptKey(cart: Cart): string {
  const fingerprint = cartFingerprint(cart)
  const stored = storedAttempt()
  if (stored !== null && stored.cart === fingerprint) return stored.key
  const attempt: StoredAttempt = { key: newKey(), cart: fingerprint }
  sessionStorage.setItem(CHECKOUT_KEY_STORAGE, JSON.stringify(attempt))
  return attempt.key
}

export function useCheckout(cart: Ref<Cart | null>) {
  const router = useRouter()
  const pending = ref(false)
  const error = ref<ApiError | null>(null)

  async function submit(): Promise<void> {
    // Запрос уже в полёте — второй не шлём (кнопка тоже заблокирована)
    if (pending.value || cart.value === null) return
    const key = attemptKey(cart.value)
    pending.value = true
    error.value = null
    try {
      const order = await checkout(key)
      // order-service освобождает ключ при любой ошибке, поэтому держим его до успеха
      sessionStorage.removeItem(CHECKOUT_KEY_STORAGE)
      await router.push({ name: 'order', params: { id: order.order_id } })
    } catch (e) {
      error.value = toApiError(e)
    } finally {
      pending.value = false
    }
  }

  return { pending, error, submit }
}
