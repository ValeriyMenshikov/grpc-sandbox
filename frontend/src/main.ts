import { createApp } from 'vue'

import App from './App.vue'
import { onUnauthorized } from './api/client'
import { createAppRouter } from './router'
import './style.css'

const router = createAppRouter()

// 401 с токеном: сессия уже сброшена клиентом — отправляем на вход с возвратом
onUnauthorized(() => {
  const current = router.currentRoute.value
  if (current.name !== 'sign-in') {
    void router.push({ name: 'sign-in', query: { next: current.fullPath } })
  }
})

createApp(App).use(router).mount('#app')
