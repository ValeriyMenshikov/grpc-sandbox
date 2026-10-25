<script setup lang="ts">
// Вход: после успеха — сессия в `auth.ts` и возврат на исходный маршрут (`?next=`).
import { ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { signIn } from '../api/auth'
import { signInRequest } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import ErrorBox from '../components/ErrorBox.vue'
import { safeNext } from '../navigation'

const route = useRoute()
const router = useRouter()

const email = ref(typeof route.query.email === 'string' ? route.query.email : '')
const password = ref('')
const pending = ref(false)
const error = ref<ApiError | null>(null)

async function submit(): Promise<void> {
  pending.value = true
  error.value = null
  try {
    signIn(await signInRequest({ email: email.value, password: password.value }))
    await router.replace(safeNext(route.query.next))
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="auth-page">
    <h1>Вход</h1>
    <p class="muted">
      Сид-продавец: <code>seller@stand.local</code> / <code>seller-password</code>
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
          autocomplete="username"
          required
        >
      </label>
      <label>
        Пароль
        <input
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
        >
      </label>
      <button
        type="submit"
        :disabled="pending"
      >
        Войти
      </button>
    </form>
    <ErrorBox
      v-if="error"
      :error="error"
    />
    <p>
      Нет аккаунта? <RouterLink to="/sign-up">
        Регистрация
      </RouterLink>
    </p>
  </section>
</template>
