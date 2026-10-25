// JSON-модели gateway 1:1 с `services/gateway/src/gateway/schemas.py`.
// Даты — ISO 8601 UTC строкой, незаданные — `null`.

export type Role = 'BUYER' | 'SELLER'

export type OrderStatus =
  | 'CREATED'
  | 'PAID'
  | 'ASSEMBLING'
  | 'HANDED_TO_COURIER'
  | 'DELIVERED'
  | 'CANCELLED'

export type ProductSort = 'name' | 'price_asc' | 'price_desc' | 'newest'

// --- Запросы ---

export interface SignUpIn {
  email: string
  password: string
  display_name?: string
  role?: Role
}

export interface ConfirmIn {
  email: string
  code: string
}

export interface SignInIn {
  email: string
  password: string
}

export interface AddCartItemIn {
  product_id: string
  quantity: number
}

// Query-строка `GET /products`; незаданные поля в запрос не попадают
export interface ProductsQuery {
  query?: string
  category?: string
  min_price_kopecks?: number
  max_price_kopecks?: number
  sort?: ProductSort
  page_size?: number
  page_token?: string
}

// Query-строка `GET /orders`
export interface OrdersQuery {
  status?: OrderStatus
  page_size?: number
  page_token?: string
}

// --- Ответы ---

// `units` — рубли, `nanos` — доли рубля (1 копейка = 10_000_000 nanos), знаки совпадают
export interface Money {
  currency_code: string
  units: number
  nanos: number
}

export interface User {
  user_id: string
  email: string
  display_name: string
  phone: string | null
  // Роль и статус gateway отдаёт строкой (`BUYER`, `ACTIVE`, ...), не сужаем
  role: string
  status: string
  created_at: string | null
  updated_at: string | null
}

export interface SignInOut {
  access_token: string
  expires_at: string | null
  user: User
}

export interface Product {
  product_id: string
  seller_id: string
  offer_id: string
  name: string
  category: string
  price: Money
  stock: number
  created_at: string | null
  updated_at: string | null
}

export interface ProductsPage {
  products: Product[]
  // Пустой — страниц больше нет
  next_page_token: string
}

export interface CartItem {
  product_id: string
  name: string
  quantity: number
  unit_price: Money
  available: number
}

export interface Cart {
  items: CartItem[]
  total: Money
}

export interface OrderItem {
  product_id: string
  name: string
  quantity: number
  unit_price: Money
}

export interface Order {
  order_id: string
  user_id: string
  status: OrderStatus
  items: OrderItem[]
  total: Money
  created_at: string | null
  updated_at: string | null
}

export interface OrdersPage {
  orders: Order[]
  next_page_token: string
}

export interface Health {
  status: 'ok'
}
