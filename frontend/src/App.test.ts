import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'

import App from './App.vue'
import { createAppRouter } from './router'

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
