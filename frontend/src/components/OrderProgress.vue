<script setup lang="ts">
// Прогресс доставки: пройденные шаги, текущий и оставшиеся; отменённый заказ — отдельно.
// Порядок шагов приходит с бэка (`delivery_steps`), время шага — из истории статусов;
// пустая история (заказ, оформленный до её появления) — шаги без времени.
import { computed } from 'vue'

import type { OrderStatus, OrderStatusChange } from '../api/types'
import { formatDate, ORDER_STATUS_LABELS } from '../orders'

const props = defineProps<{
  status: OrderStatus
  steps: OrderStatus[]
  history: OrderStatusChange[]
}>()

const items = computed(() => {
  const current = props.steps.indexOf(props.status)
  // Последняя смена в каждый статус: при повторе берётся самая свежая
  const changedAt = new Map(props.history.map((change) => [change.status, change.changed_at]))
  return props.steps.map((step, index) => ({
    status: step,
    label: ORDER_STATUS_LABELS[step],
    state: index < current ? 'done' : index === current ? 'current' : 'pending',
    changedAt: index <= current ? (changedAt.get(step) ?? null) : null,
  }))
})
</script>

<template>
  <p
    v-if="status === 'CANCELLED'"
    class="order-cancelled"
  >
    Заказ отменён
  </p>
  <ol
    v-else
    class="order-progress"
  >
    <li
      v-for="step in items"
      :key="step.status"
      class="step"
      :class="step.state"
      :aria-current="step.state === 'current' ? 'step' : undefined"
    >
      <span class="step-label">{{ step.label }}</span>
      <time
        v-if="step.changedAt !== null"
        class="step-time"
        :datetime="step.changedAt"
      >{{ formatDate(step.changedAt) }}</time>
    </li>
  </ol>
</template>
