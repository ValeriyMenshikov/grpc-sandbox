<script setup lang="ts">
// Регистрация: после 201 — экран подтверждения кода из Redis.
import { ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { signUp } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import type { Role } from '../api/types'
import ErrorBox from '../components/ErrorBox.vue'

const router = useRouter()

const email = ref('')
const password = ref('')
const displayName = ref('')
const role = ref<Role>('BUYER')
const pending = ref(false)
const error = ref<ApiError | null>(null)

async function submit(): Promise<void> {
  pending.value = true
  error.value = null
  try {
    const user = await signUp({
      email: email.value,
      password: password.value,
      display_name: displayName.value,
      role: role.value,
    })
    await router.push({ name: 'confirm', query: { email: user.email } })
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <section class="auth-page">
    <h1>Регистрация</h1>
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
          autocomplete="new-password"
          required
        >
      </label>
      <label>
        Имя
        <input
          v-model="displayName"
          name="display_name"
          type="text"
          autocomplete="name"
        >
      </label>
      <fieldset>
        <legend>Роль</legend>
        <label>
          <input
            v-model="role"
            type="radio"
            name="role"
            value="BUYER"
          >
          Покупатель
        </label>
        <label>
          <input
            v-model="role"
            type="radio"
            name="role"
            value="SELLER"
          >
          Продавец
        </label>
      </fieldset>
      <button
        type="submit"
        :disabled="pending"
      >
        Зарегистрироваться
      </button>
    </form>
    <ErrorBox
      v-if="error"
      :error="error"
    />
    <p>
      Уже есть аккаунт? <RouterLink to="/sign-in">
        Вход
      </RouterLink>
    </p>
  </section>
</template>
