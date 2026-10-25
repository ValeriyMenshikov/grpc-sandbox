<script setup lang="ts">
// Прогресс доставки: пройденные шаги, текущий и оставшиеся; отменённый заказ — отдельно.
import { computed } from 'vue'

import type { OrderStatus } from '../api/types'
import { DELIVERY_STEPS, ORDER_STATUS_LABELS } from '../orders'

const props = defineProps<{ status: OrderStatus }>()

const steps = computed(() => {
  const current = DELIVERY_STEPS.indexOf(props.status)
  return DELIVERY_STEPS.map((step, index) => ({
    status: step,
    label: ORDER_STATUS_LABELS[step],
    state: index < current ? 'done' : index === current ? 'current' : 'pending',
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
      v-for="step in steps"
      :key="step.status"
      class="step"
      :class="step.state"
      :aria-current="step.state === 'current' ? 'step' : undefined"
    >
      {{ step.label }}
    </li>
  </ol>
</template>
