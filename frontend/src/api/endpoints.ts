// Эндпоинты gateway (`services/gateway/src/gateway/routers/*.py`) — по функции на каждый.

import { request } from './client'
import type {
  AddCartItemIn,
  Cart,
  ConfirmIn,
  Health,
  Order,
  OrderDetail,
  OrdersPage,
  OrdersQuery,
  Product,
  ProductsPage,
  ProductsQuery,
  SignInIn,
  SignInOut,
  SignUpIn,
  User,
} from './types'

const segment = encodeURIComponent

export function healthz(): Promise<Health> {
  return request('GET', '/healthz')
}

// --- users ---

export function signUp(body: SignUpIn): Promise<User> {
  return request('POST', '/auth/sign-up', { body })
}

export function confirmEmail(body: ConfirmIn): Promise<User> {
  return request('POST', '/auth/confirm', { body })
}

export function signInRequest(body: SignInIn): Promise<SignInOut> {
  return request('POST', '/auth/sign-in', { body })
}

export function getMe(): Promise<User> {
  return request('GET', '/me')
}

// --- catalog ---

export function searchProducts(query: ProductsQuery = {}): Promise<ProductsPage> {
  return request('GET', '/products', { query: { ...query } })
}

export function getProduct(productId: string): Promise<Product> {
  return request('GET', `/products/${segment(productId)}`)
}

// --- cart ---

export function getCart(): Promise<Cart> {
  return request('GET', '/cart')
}

export function addCartItem(body: AddCartItemIn): Promise<Cart> {
  return request('POST', '/cart/items', { body })
}

export function removeCartItem(productId: string): Promise<Cart> {
  return request('DELETE', `/cart/items/${segment(productId)}`)
}

// --- orders ---

// Ключ генерирует вызывающий (на попытку оформления) и переиспользует при ретрае
export function checkout(idempotencyKey: string): Promise<Order> {
  return request('POST', '/checkout', { headers: { 'Idempotency-Key': idempotencyKey } })
}

export function listOrders(query: OrdersQuery = {}): Promise<OrdersPage> {
  return request('GET', '/orders', { query: { ...query } })
}

export function getOrder(orderId: string): Promise<OrderDetail> {
  return request('GET', `/orders/${segment(orderId)}`)
}
