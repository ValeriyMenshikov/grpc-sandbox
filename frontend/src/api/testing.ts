// Помощники тестов API: подмена `fetch` и разбор его вызова.

import { vi, type Mock } from 'vitest'

import type { Order, OrderDetail, OrderStatus, OrderStatusChange, User } from './types'

export const user: User = {
  user_id: 'u1',
  email: 'seller@stand.local',
  display_name: 'Seller',
  phone: null,
  role: 'SELLER',
  status: 'ACTIVE',
  created_at: null,
  updated_at: null,
}

// Порядок шагов доставки, как его отдаёт `GET /orders/{id}`
export const deliverySteps: OrderStatus[] = [
  'CREATED',
  'PAID',
  'ASSEMBLING',
  'HANDED_TO_COURIER',
  'DELIVERED',
]

// Заказ со страницы заказа; без `history` — как заказ, оформленный до появления истории
export function orderDetail(
  order: Order,
  history: OrderStatusChange[] = [],
  steps: OrderStatus[] = deliverySteps,
): OrderDetail {
  return { ...order, history, delivery_steps: steps }
}

export function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

// Подменяет глобальный `fetch`; ответы отдаются по очереди, последний — повторяется.
// Каждый вызов получает свою копию: тело `Response` читается один раз
export function mockFetch(...responses: Response[]): Mock {
  const fetchMock = vi.fn()
  const last = responses.at(-1)
  const spare = last?.clone()
  for (const response of responses) {
    fetchMock.mockResolvedValueOnce(response)
  }
  if (spare !== undefined) {
    fetchMock.mockImplementation(() => Promise.resolve(spare.clone()))
  }
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

export interface FetchCall {
  url: string
  init: RequestInit
  headers: Headers
}

export function fetchCall(fetchMock: Mock, index = 0): FetchCall {
  const [url, init = {}] = fetchMock.mock.calls[index] as [string, RequestInit | undefined]
  return { url, init, headers: new Headers(init.headers) }
}
