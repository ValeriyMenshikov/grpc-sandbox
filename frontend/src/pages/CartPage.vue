<script setup lang="ts">
// Корзина: позиции с ценой за единицу и доступным остатком (нехватка подсвечивается), итог,
// удаление позиции, оформление заказа. Ответ `DELETE` — уже обновлённая корзина.
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { getCart, removeCartItem } from '../api/endpoints'
import { ApiError, toApiError } from '../api/errors'
import { formatMoney } from '../api/money'
import type { Cart } from '../api/types'
import ErrorBox from '../components/ErrorBox.vue'
import { useCheckout } from '../composables/useCheckout'

const cart = ref<Cart | null>(null)
const loading = ref(false)
const error = ref<ApiError | null>(null)
// product_id позиции, которая сейчас удаляется
const removing = ref<string | null>(null)
const {
  pending: checkoutPending,
  error: checkoutError,
  submit: submitCheckout,
} = useCheckout(cart)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    cart.value = await getCart()
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    loading.value = false
  }
}

async function remove(productId: string): Promise<void> {
  removing.value = productId
  error.value = null
  try {
    cart.value = await removeCartItem(productId)
  } catch (e) {
    error.value = toApiError(e)
  } finally {
    removing.value = null
  }
}

onMounted(load)
</script>

<template>
  <section class="cart-page">
    <h1>Корзина</h1>
    <p
      v-if="loading && cart === null"
      class="loading muted"
    >
      Загрузка…
    </p>
    <ErrorBox
      v-if="error"
      :error="error"
      :retry="load"
    />
    <template v-if="cart">
      <p
        v-if="cart.items.length === 0"
        class="empty muted"
      >
        Корзина пуста. <RouterLink to="/">
          В каталог
        </RouterLink>
      </p>
      <template v-else>
        <table class="cart-table">
          <thead>
            <tr>
              <th>Товар</th>
              <th>Цена</th>
              <th>Количество</th>
              <th>Доступно</th>
              <th />
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in cart.items"
              :key="item.product_id"
              class="cart-item"
              :class="{ shortage: item.quantity > item.available }"
            >
              <td>
                <RouterLink :to="{ name: 'product', params: { id: item.product_id } }">
                  {{ item.name }}
                </RouterLink>
              </td>
              <td>{{ formatMoney(item.unit_price) }}</td>
              <td>{{ item.quantity }}</td>
              <td class="available">
                {{ item.available }}
                <span
                  v-if="item.quantity > item.available"
                  class="shortage-note"
                >не хватает {{ item.quantity - item.available }}</span>
              </td>
              <td>
                <button
                  type="button"
                  class="remove"
                  :disabled="removing !== null"
                  @click="remove(item.product_id)"
                >
                  Удалить
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p class="total">
          Итого: <strong>{{ formatMoney(cart.total) }}</strong>
        </p>
        <ErrorBox
          v-if="checkoutError"
          :error="checkoutError"
          :retry="submitCheckout"
        />
        <p class="checkout">
          <button
            type="button"
            class="checkout-button"
            :disabled="checkoutPending || removing !== null"
            @click="submitCheckout"
          >
            {{ checkoutPending ? 'Оформляем…' : 'Оформить заказ' }}
          </button>
        </p>
      </template>
    </template>
  </section>
</template>
