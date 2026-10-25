<script setup lang="ts">
// Заказ: позиции, итог, даты и прогресс доставки. Статус обновляется поллингом
// `GET /orders/{id}` до `DELIVERED` / `CANCELLED` (gateway стримы не публикует).
import { watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

import { getOrder } from '../api/endpoints'
import { formatMoney } from '../api/money'
import ErrorBox from '../components/ErrorBox.vue'
import OrderProgress from '../components/OrderProgress.vue'
import { usePolling } from '../composables/usePolling'
import { formatDate, isFinalStatus, ORDER_STATUS_LABELS } from '../orders'

const route = useRoute()

function orderId(): string {
  const id = route.params.id
  return typeof id === 'string' ? id : ''
}

const {
  data: order,
  error,
  active,
  start,
} = usePolling(
  () => getOrder(orderId()),
  (value) => isFinalStatus(value.status),
)

// Переход с заказа на заказ — опрос заново; уход со страницы останавливает опрос сам
// (`onUnmounted` в `usePolling`), а смена маршрута до размонтирования опрос не перезапускает
watch(
  () => route.params.id,
  () => {
    if (route.name === 'order' && orderId()) start()
  },
  { immediate: true },
)
</script>

<template>
  <section class="order-page">
    <h1>Заказ</h1>
    <p
      v-if="order === null && active && error === null"
      class="loading muted"
    >
      Загрузка…
    </p>
    <ErrorBox
      v-if="error"
      :error="error"
      :retry="active ? undefined : start"
    />
    <template v-if="order">
      <dl class="order-props">
        <dt>Номер</dt>
        <dd class="order-id">
          {{ order.order_id }}
        </dd>
        <dt>Статус</dt>
        <dd class="status">
          <span
            class="badge"
            :class="`badge-${order.status.toLowerCase()}`"
          >{{ ORDER_STATUS_LABELS[order.status] }}</span>
          <span
            v-if="active"
            class="muted polling"
          >обновляется…</span>
        </dd>
        <dt>Создан</dt>
        <dd class="created-at">
          {{ formatDate(order.created_at) }}
        </dd>
        <dt>Обновлён</dt>
        <dd class="updated-at">
          {{ formatDate(order.updated_at) }}
        </dd>
      </dl>
      <OrderProgress :status="order.status" />
      <table class="cart-table order-items">
        <thead>
          <tr>
            <th>Товар</th>
            <th>Цена</th>
            <th>Количество</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in order.items"
            :key="item.product_id"
            class="order-item"
          >
            <td>
              <RouterLink :to="{ name: 'product', params: { id: item.product_id } }">
                {{ item.name }}
              </RouterLink>
            </td>
            <td>{{ formatMoney(item.unit_price) }}</td>
            <td>{{ item.quantity }}</td>
          </tr>
        </tbody>
      </table>
      <p class="total">
        Итого: <strong>{{ formatMoney(order.total) }}</strong>
      </p>
    </template>
    <p>
      <RouterLink to="/orders">
        Все заказы
      </RouterLink>
    </p>
  </section>
</template>
