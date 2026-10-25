<script setup lang="ts">
// Количество товара: целое ≥ 1. Верхнюю границу (остаток) не навязываем — превышение
// проверяет бэкенд, и его ошибка показывается пользователю.
const quantity = defineModel<number>({ required: true })

defineProps<{ disabled?: boolean }>()

function set(value: number): void {
  quantity.value = Number.isFinite(value) ? Math.max(1, Math.trunc(value)) : 1
}

function onInput(event: Event): void {
  const input = event.target as HTMLInputElement
  set(input.valueAsNumber)
  // Модель могла не измениться (0 → 1 при уже 1) — поле поправляем сами
  input.value = String(quantity.value)
}
</script>

<template>
  <span class="quantity-input">
    <button
      type="button"
      class="decrement"
      aria-label="Меньше"
      :disabled="disabled || quantity <= 1"
      @click="set(quantity - 1)"
    >
      −
    </button>
    <input
      type="number"
      name="quantity"
      min="1"
      step="1"
      :value="quantity"
      :disabled="disabled"
      @change="onInput"
    >
    <button
      type="button"
      class="increment"
      aria-label="Больше"
      :disabled="disabled"
      @click="set(quantity + 1)"
    >
      +
    </button>
  </span>
</template>
