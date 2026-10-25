<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <header class="app-header">
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
      <RouterLink to="/sign-in">
        Вход
      </RouterLink>
    </nav>
  </header>
  <main class="app-main">
    <RouterView />
  </main>
</template>
