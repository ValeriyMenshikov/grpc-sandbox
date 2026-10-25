<script setup lang="ts">
// Каталог: фильтры живут в query-строке URL (цена — в рублях, как ввёл пользователь),
// в запрос уходят копейки; «Показать ещё» дозагружает страницу по `next_page_token`.
import { computed, reactive, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter, type LocationQuery } from 'vue-router'

import { searchProducts } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import { formatMoney, rublesToKopecks } from '../api/money'
import type { Product, ProductSort, ProductsQuery } from '../api/types'
import ErrorBox from '../components/ErrorBox.vue'

const SORTS: { value: ProductSort; label: string }[] = [
  { value: 'name', label: 'По названию' },
  { value: 'price_asc', label: 'Сначала дешёвые' },
  { value: 'price_desc', label: 'Сначала дорогие' },
  { value: 'newest', label: 'Сначала новые' },
]
// Категории сид-данных (`catalog_service/schema.sql`) — подсказки, ввод свободный
const CATEGORIES = ['electronics', 'books', 'home']
const PAGE_SIZE = 10

interface Filters {
  query: string
  category: string
  min_price: string
  max_price: string
  sort: ProductSort
}

const route = useRoute()
const router = useRouter()

function queryString(query: LocationQuery, key: string): string {
  const value = query[key]
  return typeof value === 'string' ? value : ''
}

function filtersFrom(query: LocationQuery): Filters {
  const sort = queryString(query, 'sort')
  return {
    query: queryString(query, 'query'),
    category: queryString(query, 'category'),
    min_price: queryString(query, 'min_price'),
    max_price: queryString(query, 'max_price'),
    sort: SORTS.some((s) => s.value === sort) ? (sort as ProductSort) : 'name',
  }
}

// Фильтры в запрос gateway; некорректная сумма — исключение `MoneyInputError`
function toRequest(filters: Filters): ProductsQuery {
  const request: ProductsQuery = { sort: filters.sort, page_size: PAGE_SIZE }
  const query = filters.query.trim()
  const category = filters.category.trim()
  const min = rublesToKopecks(filters.min_price)
  const max = rublesToKopecks(filters.max_price)
  if (query) request.query = query
  if (category) request.category = category
  if (min !== undefined) request.min_price_kopecks = min
  if (max !== undefined) request.max_price_kopecks = max
  return request
}

const form = reactive<Filters>(filtersFrom(route.query))
const products = ref<Product[]>([])
const nextPageToken = ref('')
const loading = ref(false)
const error = ref<ApiError | null>(null)
const inputError = ref('')
// Номер текущей загрузки: ответ устаревшего запроса (фильтры успели смениться) отбрасывается
let generation = 0

const empty = computed(
  () => !loading.value && error.value === null && inputError.value === '' && products.value.length === 0,
)

async function load(reset: boolean): Promise<void> {
  const current = ++generation
  let request: ProductsQuery
  try {
    request = toRequest(filtersFrom(route.query))
  } catch (e) {
    inputError.value = e instanceof Error ? e.message : String(e)
    products.value = []
    nextPageToken.value = ''
    return
  }
  inputError.value = ''
  if (!reset) request.page_token = nextPageToken.value
  loading.value = true
  error.value = null
  try {
    const page = await searchProducts(request)
    if (current !== generation) return
    products.value = reset ? page.products : [...products.value, ...page.products]
    nextPageToken.value = page.next_page_token
  } catch (e) {
    if (current !== generation) return
    error.value = toApiError(e)
  } finally {
    if (current === generation) loading.value = false
  }
}

// Новый набор фильтров в URL — первая страница заново
watch(
  () => route.query,
  (query) => {
    Object.assign(form, filtersFrom(query))
    products.value = []
    nextPageToken.value = ''
    void load(true)
  },
  { immediate: true },
)

function apply(): void {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(form)) {
    const trimmed = value.trim()
    if (trimmed && !(key === 'sort' && trimmed === 'name')) query[key] = trimmed
  }
  void router.push({ query })
}

function retry(): void {
  void load(products.value.length === 0)
}
</script>

<template>
  <section class="catalog-page">
    <h1>Каталог</h1>
    <form
      class="filters"
      @submit.prevent="apply"
    >
      <input
        v-model="form.query"
        name="query"
        type="search"
        placeholder="Поиск по названию"
      >
      <input
        v-model="form.category"
        name="category"
        type="text"
        list="categories"
        placeholder="Категория"
      >
      <datalist id="categories">
        <option
          v-for="category in CATEGORIES"
          :key="category"
          :value="category"
        />
      </datalist>
      <input
        v-model="form.min_price"
        name="min_price"
        type="text"
        inputmode="decimal"
        placeholder="Цена от, ₽"
      >
      <input
        v-model="form.max_price"
        name="max_price"
        type="text"
        inputmode="decimal"
        placeholder="до, ₽"
      >
      <select
        v-model="form.sort"
        name="sort"
        @change="apply"
      >
        <option
          v-for="sort in SORTS"
          :key="sort.value"
          :value="sort.value"
        >
          {{ sort.label }}
        </option>
      </select>
      <button type="submit">
        Найти
      </button>
    </form>

    <p
      v-if="inputError"
      class="input-error"
      role="alert"
    >
      {{ inputError }}
    </p>

    <ul
      v-if="products.length > 0"
      class="product-list"
    >
      <li
        v-for="product in products"
        :key="product.product_id"
        class="product-item"
      >
        <RouterLink :to="{ name: 'product', params: { id: product.product_id } }">
          {{ product.name }}
        </RouterLink>
        <span class="muted">{{ product.category }}</span>
        <span class="price">{{ formatMoney(product.price) }}</span>
      </li>
    </ul>

    <p
      v-if="empty"
      class="empty muted"
    >
      Ничего не найдено.
    </p>
    <p
      v-if="loading"
      class="loading muted"
    >
      Загрузка…
    </p>
    <ErrorBox
      v-if="error"
      :error="error"
      :retry="retry"
    />
    <button
      v-if="nextPageToken && !loading && !error"
      type="button"
      class="load-more"
      @click="load(false)"
    >
      Показать ещё
    </button>
  </section>
</template>
