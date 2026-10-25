import { createRouter, createWebHistory, type RouterHistory } from 'vue-router'

import PlaceholderPage from './pages/PlaceholderPage.vue'

// Маршруты UI; заглушки заменяются страницами по мере готовности.
export const routes = [
  { path: '/', name: 'catalog', component: PlaceholderPage, props: { title: 'Каталог' } },
  {
    path: '/products/:id',
    name: 'product',
    component: PlaceholderPage,
    props: { title: 'Товар' },
  },
  { path: '/cart', name: 'cart', component: PlaceholderPage, props: { title: 'Корзина' } },
  { path: '/orders', name: 'orders', component: PlaceholderPage, props: { title: 'Заказы' } },
  { path: '/orders/:id', name: 'order', component: PlaceholderPage, props: { title: 'Заказ' } },
  { path: '/sign-in', name: 'sign-in', component: PlaceholderPage, props: { title: 'Вход' } },
  {
    path: '/sign-up',
    name: 'sign-up',
    component: PlaceholderPage,
    props: { title: 'Регистрация' },
  },
  {
    path: '/confirm',
    name: 'confirm',
    component: PlaceholderPage,
    props: { title: 'Подтверждение email' },
  },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  return createRouter({ history, routes })
}
