<script setup lang="ts">
// Подтверждение email кодом. Код приходит письмом: users-service публикует событие,
// notification-service отправляет его в Mailpit — ящик стенда проксируется nginx как /mail/.
// Код живёт 15 минут (`confirm_code_ttl_s` users-service).
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { confirmEmail } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import ErrorBox from '../components/ErrorBox.vue'

const route = useRoute()
const router = useRouter()

const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const code = ref('')
const pending = ref(false)
const error = ref<ApiError | null>(null)

async function submit(): Promise<void> {
  pending.value = true
  error.value = null
  try {
    await confirmEmail({ email: email.value, code: code.value.trim() })
    await router.push({ name: 'sign-in', query: { email: email.value } })
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="auth-page">
    <h1>Подтверждение email</h1>
    <p class="muted mail-note">
      Письмо с кодом отправлено на <strong>{{ email || 'указанный email' }}</strong>.
      Код действует 15 минут. Письма стенда лежат в
      <a
        href="/mail/"
        target="_blank"
        rel="noopener"
      >почтовом ящике стенда</a>.
    </p>
    <form
      class="form"
      @submit.prevent="submit"
    >
      <label>
        Email
        <input
          v-model="email"
          name="email"
          type="email"
          required
        >
      </label>
      <label>
        Код
        <input
          v-model="code"
          name="code"
          type="text"
          inputmode="numeric"
          autocomplete="one-time-code"
          required
        >
      </label>
      <button
        type="submit"
        :disabled="pending"
      >
        Подтвердить
      </button>
    </form>
    <ErrorBox
      v-if="error"
      :error="error"
    />
  </section>
</template>
