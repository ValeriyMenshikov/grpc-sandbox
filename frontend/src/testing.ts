// Помощники тестов страниц: приложение целиком на memory-истории роутера.

import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, type Router } from 'vue-router'

import App from './App.vue'
import { createAppRouter } from './router'

export async function mountApp(path: string): Promise<{
  wrapper: ReturnType<typeof mount>
  router: Router
}> {
  const router = createAppRouter(createMemoryHistory())
  await router.push(path)
  await router.isReady()
  const wrapper = mount(App, { global: { plugins: [router] } })
  await flushPromises()
  return { wrapper, router }
}
