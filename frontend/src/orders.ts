// Статусы заказа для UI: подписи и формат дат; порядок шагов доставки приходит с бэка.

import type { OrderStatus } from './api/types'

export const ORDER_STATUS_LABELS: Record<OrderStatus, string> = {
  CREATED: 'Создан',
  PAID: 'Оплачен',
  ASSEMBLING: 'Собирается',
  HANDED_TO_COURIER: 'Передан курьеру',
  DELIVERED: 'Доставлен',
  CANCELLED: 'Отменён',
}

// Дальше статус не меняется — поллинг можно останавливать
export function isFinalStatus(status: OrderStatus): boolean {
  return status === 'DELIVERED' || status === 'CANCELLED'
}

export function isOrderStatus(value: unknown): value is OrderStatus {
  return typeof value === 'string' && value in ORDER_STATUS_LABELS
}

// ISO 8601 UTC → местное время; незаданная дата — прочерк
export function formatDate(value: string | null): string {
  if (value === null) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ru-RU', { dateStyle: 'short', timeStyle: 'medium' })
}
