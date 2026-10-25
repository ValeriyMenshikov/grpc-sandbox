<script setup lang="ts">
// Временная заглушка маршрута: настоящие страницы появятся в следующих задачах.
defineProps<{ title: string }>()
</script>

<template>
  <section>
    <h1>{{ title }}</h1>
    <p class="muted">
      Страница в разработке.
    </p>
  </section>
</template>
