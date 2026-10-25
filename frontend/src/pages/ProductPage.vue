<script setup lang="ts">
// Карточка товара и «В корзину». Остаток на клиенте не проверяем: превышение отклоняет
// order-service, и его ошибка с details показывается через `ErrorBox`.
import { ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import { session } from '../api/auth'
import { addCartItem, getProduct } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import { formatMoney } from '../api/money'
import type { Product } from '../api/types'
import ErrorBox from '../components/ErrorBox.vue'
import QuantityInput from '../components/QuantityInput.vue'

const route = useRoute()
const router = useRouter()

const product = ref<Product | null>(null)
const loading = ref(false)
const loadError = ref<ApiError | null>(null)
const quantity = ref(1)
const adding = ref(false)
const added = ref(false)
const addError = ref<ApiError | null>(null)

async function load(): Promise<void> {
  loading.value = true
  loadError.value = null
  try {
    product.value = await getProduct(String(route.params.id))
  } catch (e) {
    loadError.value = toApiError(e)
  } finally {
    loading.value = false
  }
}

watch(
  () => route.params.id,
  () => {
    product.value = null
    quantity.value = 1
    added.value = false
    addError.value = null
    void load()
  },
  { immediate: true },
)

async function addToCart(): Promise<void> {
  if (product.value === null) return
  if (session.token === null) {
    await router.push({ name: 'sign-in', query: { next: route.fullPath } })
    return
  }
  adding.value = true
  added.value = false
  addError.value = null
  try {
    await addCartItem({ product_id: product.value.product_id, quantity: quantity.value })
    added.value = true
  } catch (e) {
    addError.value = toApiError(e)
  } finally {
    adding.value = false
  }
}
</script>

<template>
  <section class="product-page">
    <template v-if="product">
      <h1>{{ product.name }}</h1>
      <dl class="product-props">
        <dt>Цена</dt>
        <dd class="price">
          {{ formatMoney(product.price) }}
        </dd>
        <dt>Категория</dt>
        <dd>{{ product.category }}</dd>
        <dt>В наличии</dt>
        <dd class="stock">
          {{ product.stock }} шт.
        </dd>
        <dt>Артикул продавца</dt>
        <dd><code>{{ product.offer_id }}</code></dd>
      </dl>
      <form
        class="add-to-cart"
        @submit.prevent="addToCart"
      >
        <QuantityInput
          v-model="quantity"
          :disabled="adding"
        />
        <button
          type="submit"
          :disabled="adding"
        >
          В корзину
        </button>
      </form>
      <p
        v-if="added"
        class="added"
      >
        Добавлено в корзину. <RouterLink to="/cart">
          Перейти в корзину
        </RouterLink>
      </p>
      <ErrorBox
        v-if="addError"
        :error="addError"
      />
    </template>
    <template v-else>
      <h1>Товар</h1>
      <p
        v-if="loading"
        class="loading muted"
      >
        Загрузка…
      </p>
      <ErrorBox
        v-if="loadError"
        :error="loadError"
        :retry="load"
      />
    </template>
  </section>
</template>
