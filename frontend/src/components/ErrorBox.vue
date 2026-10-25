<script setup lang="ts">
// Показ `ApiError`: сообщение, rich details поштучно, поля 422 FastAPI,
// для недоступности — кнопка повтора (если передан колбэк).
import { computed } from 'vue'

import { ApiError, describeDetails, describeValidation } from '../api/errors'

const props = defineProps<{
  error: ApiError
  retry?: () => void
}>()

const lines = computed(() => [
  ...describeDetails(props.error.details),
  ...describeValidation(props.error.validation),
])

// Повтор имеет смысл только для временных сбоев
const canRetry = computed(
  () =>
    props.retry !== undefined &&
    (props.error.kind === 'unavailable' || props.error.kind === 'network'),
)
</script>

<template>
  <div
    class="error-box"
    role="alert"
  >
    <p class="error-message">
      {{ error.message }}
      <span
        v-if="error.code"
        class="error-code"
      >{{ error.code }}</span>
    </p>
    <ul
      v-if="lines.length > 0"
      class="error-details"
    >
      <li
        v-for="(line, index) in lines"
        :key="index"
      >
        {{ line }}
      </li>
    </ul>
    <button
      v-if="canRetry"
      type="button"
      class="error-retry"
      @click="retry?.()"
    >
      Повторить
    </button>
  </div>
</template>
