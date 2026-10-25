// Оформление заказа: один `Idempotency-Key` на попытку — повторный клик и ретрай после ошибки
// идут с тем же ключом, новый ключ появляется только после успеха. Ключ лежит в
// `sessionStorage`, чтобы перезагрузка посреди попытки не создала второй заказ.
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { checkout } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'

export const CHECKOUT_KEY_STORAGE = 'stand.checkout.idempotency-key'

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

// Ключ текущей попытки; нет — заводится новый
export function attemptKey(): string {
  let key = sessionStorage.getItem(CHECKOUT_KEY_STORAGE)
  if (key === null) {
    key = newKey()
    sessionStorage.setItem(CHECKOUT_KEY_STORAGE, key)
  }
  return key
}

export function useCheckout() {
  const router = useRouter()
  const pending = ref(false)
  const error = ref<ApiError | null>(null)

  async function submit(): Promise<void> {
    // Запрос уже в полёте — второй не шлём (кнопка тоже заблокирована)
    if (pending.value) return
    const key = attemptKey()
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
