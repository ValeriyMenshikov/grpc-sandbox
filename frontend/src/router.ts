import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
  type RouteRecordRaw,
} from 'vue-router'

import { session } from './api/auth'
import { onUnauthorized } from './api/client'
import CartPage from './pages/CartPage.vue'
import CatalogPage from './pages/CatalogPage.vue'
import ConfirmPage from './pages/ConfirmPage.vue'
import OrderPage from './pages/OrderPage.vue'
import OrdersPage from './pages/OrdersPage.vue'
import ProductPage from './pages/ProductPage.vue'
import SignInPage from './pages/SignInPage.vue'
import SignUpPage from './pages/SignUpPage.vue'

declare module 'vue-router' {
  interface RouteMeta {
    // Без токена — редирект на вход с `?next=`
    requiresAuth?: boolean
  }
}

// Маршруты UI.
export const routes: RouteRecordRaw[] = [
  { path: '/', name: 'catalog', component: CatalogPage },
  { path: '/products/:id', name: 'product', component: ProductPage },
  { path: '/cart', name: 'cart', component: CartPage, meta: { requiresAuth: true } },
  { path: '/orders', name: 'orders', component: OrdersPage, meta: { requiresAuth: true } },
  { path: '/orders/:id', name: 'order', component: OrderPage, meta: { requiresAuth: true } },
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

// 401 с токеном: сессия уже сброшена клиентом. Со страницы, требующей входа, — на вход с
// возвратом; публичная (каталог, товар) остаётся на месте, просто без входа
export function redirectOnUnauthorized(router: Router): void {
  onUnauthorized(() => {
    const current = router.currentRoute.value
    if (current.meta.requiresAuth) {
      void router.push({ name: 'sign-in', query: { next: current.fullPath } })
    }
  })
}
