import { createApp } from 'vue'

import App from './App.vue'
import { createAppRouter, redirectOnUnauthorized } from './router'
import './style.css'

const router = createAppRouter()
redirectOnUnauthorized(router)

createApp(App).use(router).mount('#app')
