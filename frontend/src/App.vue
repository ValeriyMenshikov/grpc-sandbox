<script setup lang="ts">
import { RouterView } from 'vue-router'

import AppHeader from './components/AppHeader.vue'
</script>

<template>
  <AppHeader />
  <main class="app-main">
    <RouterView />
  </main>
  <footer class="app-footer">
    Учебный gRPC-стенд маркетплейса. REST-фасад — <code>/api</code>,
    его OpenAPI — <a href="/api/docs">/api/docs</a>.
  </footer>
</template>
