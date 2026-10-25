<script setup lang="ts">
// Шапка: навигация, текущий пользователь (обновляется через `/me` при входе), выход.
import { watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'

import { isSignedIn, session, setUser, signOut } from '../api/auth'
import { getMe } from '../api/endpoints'

const router = useRouter()

async function refreshUser(): Promise<void> {
  try {
    setUser(await getMe())
  } catch {
    // 401 уже разлогинил клиент; прочие сбои — остаётся пользователь из сессии
  }
}

watch(
  () => session.token,
  (token) => {
    if (token !== null) {
      void refreshUser()
    }
  },
  { immediate: true },
)

function onSignOut(): void {
  signOut()
  void router.push({ name: 'sign-in' })
}
</script>

<template>
  <header class="app-header">
    <div class="header-inner">
      <RouterLink
        to="/"
        class="brand"
      >
        Стенд маркетплейса
      </RouterLink>
      <nav>
        <RouterLink to="/">
          Каталог
        </RouterLink>
        <RouterLink to="/cart">
          Корзина
        </RouterLink>
        <RouterLink to="/orders">
          Заказы
        </RouterLink>
      </nav>
      <div class="account">
        <template v-if="isSignedIn">
          <span
            v-if="session.user"
            class="user"
          >
            {{ session.user.display_name || session.user.email }}
            <span class="muted">{{ session.user.email }} · {{ session.user.role }}</span>
          </span>
          <button
            type="button"
            class="sign-out"
            @click="onSignOut"
          >
            Выйти
          </button>
        </template>
        <template v-else>
          <RouterLink to="/sign-in">
            Вход
          </RouterLink>
          <RouterLink to="/sign-up">
            Регистрация
          </RouterLink>
        </template>
      </div>
    </div>
  </header>
</template>
