<script setup lang="ts">
// Список заказов: фильтр по статусу живёт в query-строке URL,
// «Показать ещё» дозагружает страницу по `next_page_token`.
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'

import { listOrders } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import { formatMoney } from '../api/money'
import type { Order, OrderStatus, OrdersQuery } from '../api/types'
import ErrorBox from '../components/ErrorBox.vue'
import { formatDate, isOrderStatus, ORDER_STATUS_LABELS } from '../orders'

const PAGE_SIZE = 10
const STATUSES = Object.entries(ORDER_STATUS_LABELS) as [OrderStatus, string][]

const route = useRoute()
const router = useRouter()

function statusFrom(query: LocationQuery): OrderStatus | '' {
  return isOrderStatus(query.status) ? query.status : ''
}

const status = ref<OrderStatus | ''>(statusFrom(route.query))
const orders = ref<Order[]>([])
const nextPageToken = ref('')
const loading = ref(false)
const error = ref<ApiError | null>(null)
// Номер текущей загрузки: ответ устаревшего запроса (фильтр успел смениться) отбрасывается
let generation = 0

const empty = computed(
  () => !loading.value && error.value === null && orders.value.length === 0,
)

async function load(reset: boolean): Promise<void> {
  const current = ++generation
  const request: OrdersQuery = { page_size: PAGE_SIZE }
  const filter = statusFrom(route.query)
  if (filter) request.status = filter
  if (!reset) request.page_token = nextPageToken.value
  loading.value = true
  error.value = null
  try {
    const page = await listOrders(request)
    if (current !== generation) return
    orders.value = reset ? page.orders : [...orders.value, ...page.orders]
    nextPageToken.value = page.next_page_token
  } catch (e) {
    if (current !== generation) return
    error.value = toApiError(e)
  } finally {
    if (current === generation) loading.value = false
  }
}

// Новый фильтр в URL — первая страница заново
watch(
  () => route.query,
  (query) => {
    status.value = statusFrom(query)
    orders.value = []
    nextPageToken.value = ''
    void load(true)
  },
  { immediate: true },
)

function applyStatus(): void {
  void router.push({ query: status.value ? { status: status.value } : {} })
}

function retry(): void {
  void load(orders.value.length === 0)
}
</script>

<template>
  <section class="orders-page">
    <h1>Заказы</h1>
    <p class="page-sub muted">
      Заказы из order-service. Доставка идёт фоновыми шагами — статус обновляется сам.
    </p>
    <div class="filters">
      <select
        v-model="status"
        name="status"
        @change="applyStatus"
      >
        <option value="">
          Все статусы
        </option>
        <option
          v-for="[value, label] in STATUSES"
          :key="value"
          :value="value"
        >
          {{ label }}
        </option>
      </select>
    </div>

    <table
      v-if="orders.length > 0"
      class="orders-table"
    >
      <thead>
        <tr>
          <th>Заказ</th>
          <th>Статус</th>
          <th>Создан</th>
          <th>Сумма</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="order in orders"
          :key="order.order_id"
          class="order-row"
        >
          <td>
            <RouterLink :to="{ name: 'order', params: { id: order.order_id } }">
              {{ order.order_id }}
            </RouterLink>
          </td>
          <td class="status">
            <span
              class="badge"
              :class="`badge-${order.status.toLowerCase()}`"
            >{{ ORDER_STATUS_LABELS[order.status] }}</span>
          </td>
          <td>{{ formatDate(order.created_at) }}</td>
          <td class="price">
            {{ formatMoney(order.total) }}
          </td>
        </tr>
      </tbody>
    </table>

    <p
      v-if="empty"
      class="empty muted"
    >
      Заказов нет.
    </p>
    <p
      v-if="loading"
      class="loading muted"
    >
      Загрузка…
    </p>
    <ErrorBox
      v-if="error"
      :error="error"
      :retry="retry"
    />
    <button
      v-if="nextPageToken && !loading && !error"
      type="button"
      class="load-more"
      @click="load(false)"
    >
      Показать ещё
    </button>
  </section>
</template>
