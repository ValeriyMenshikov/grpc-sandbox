import {
  createRouter,
  createWebHistory,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'

import { session } from './api/auth'
import ConfirmPage from './pages/ConfirmPage.vue'
import PlaceholderPage from './pages/PlaceholderPage.vue'
import SignInPage from './pages/SignInPage.vue'
import SignUpPage from './pages/SignUpPage.vue'

declare module 'vue-router' {
  interface RouteMeta {
    // Без токена — редирект на вход с `?next=`
    requiresAuth?: boolean
  }
}

// Маршруты UI; заглушки заменяются страницами по мере готовности.
export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'catalog', component: PlaceholderPage, props: { title: 'Каталог' } },
  {
    path: '/products/:id',
    name: 'product',
    component: PlaceholderPage,
    props: { title: 'Товар' },
  },
  {
    path: '/cart',
    name: 'cart',
    component: PlaceholderPage,
    props: { title: 'Корзина' },
    meta: { requiresAuth: true },
  },
  {
    path: '/orders',
    name: 'orders',
    component: PlaceholderPage,
    props: { title: 'Заказы' },
    meta: { requiresAuth: true },
  },
  {
    path: '/orders/:id',
    name: 'order',
    component: PlaceholderPage,
    props: { title: 'Заказ' },
    meta: { requiresAuth: true },
  },
  { path: '/sign-in', name: 'sign-in', component: SignInPage },
  { path: '/sign-up', name: 'sign-up', component: SignUpPage },
  { path: '/confirm', name: 'confirm', component: ConfirmPage },
]

export function createAppRouter(history: RouterHistory = createWebHistory()) {
  const router = createRouter({ history, routes })
  router.beforeEach((to) => {
    if (to.meta.requiresAuth && session.token === null) {
      return { name: 'sign-in', query: { next: to.fullPath } }
    }
    return true
  })
  return router
}
