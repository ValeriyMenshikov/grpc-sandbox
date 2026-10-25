import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import * as api from './api/endpoints'
import App from './App.vue'
import { createAppRouter } from './router'

// Страницы ходят в API при монтировании — здесь достаточно, чтобы запросы не завершались
vi.mock('./api/endpoints')
vi.mocked(api.searchProducts).mockReturnValue(new Promise(() => {}))
vi.mocked(api.getProduct).mockReturnValue(new Promise(() => {}))

describe('App', () => {
  it('монтируется и рендерит главную через роутер', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })

    expect(wrapper.find('header').text()).toContain('Стенд маркетплейса')
    expect(wrapper.find('main h1').text()).toBe('Каталог')
  })

  it('рендерит страницу по пути', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/products/42')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })

    expect(wrapper.find('main h1').text()).toBe('Товар')
  })

  it('защищённый маршрут без входа показывает форму входа', async () => {
    const router = createAppRouter(createMemoryHistory())
    await router.push('/orders/42')
    await router.isReady()

    const wrapper = mount(App, { global: { plugins: [router] } })

    expect(wrapper.find('main h1').text()).toBe('Вход')
  })
})
