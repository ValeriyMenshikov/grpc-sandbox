import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { signIn, signOut } from '../api/auth'
import * as api from '../api/endpoints'
import { parseApiError } from '../api/errors'
import { user } from '../api/testing'
import type { Cart, Money, Order, OrderStatus, OrdersPage } from '../api/types'
import OrderProgress from '../components/OrderProgress.vue'
import { CHECKOUT_KEY_STORAGE } from '../composables/useCheckout'
import { POLL_INTERVAL_MS } from '../composables/usePolling'
import { mountApp } from '../testing'

vi.mock('../api/endpoints')
enableAutoUnmount(afterEach)

function rub(kopecks: number): Money {
  return {
    currency_code: 'RUB',
    units: Math.trunc(kopecks / 100),
    nanos: (kopecks % 100) * 10_000_000,
  }
}

function plain(text: string | undefined): string {
  return (text ?? '').replace(/ /g, ' ')
}

const filledCart: Cart = {
  items: [
    { product_id: 'p1', name: 'Товар p1', quantity: 2, unit_price: rub(10000), available: 5 },
  ],
  total: rub(20000),
}

function order(id: string, status: OrderStatus = 'CREATED'): Order {
  return {
    order_id: id,
    user_id: user.user_id,
    status,
    items: [{ product_id: 'p1', name: 'Товар p1', quantity: 2, unit_price: rub(10000) }],
    total: rub(20000),
    created_at: '2026-10-25T10:00:00Z',
    updated_at: null,
  }
}

function ordersPage(orders: Order[], nextPageToken = ''): OrdersPage {
  return { orders, next_page_token: nextPageToken }
}

const unavailable = () =>
  parseApiError(503, { error: { code: 'UNAVAILABLE', message: 'catalog is unavailable' } })

// Промис, который тест завершает сам — чтобы держать запрос «в полёте»
function deferred<T>() {
  let resolve: (value: T) => void = () => {}
  let reject: (reason: unknown) => void = () => {}
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

beforeEach(() => {
  signIn({ access_token: 't', expires_at: null, user })
  vi.mocked(api.getMe).mockResolvedValue(user)
})

afterEach(() => {
  signOut()
  sessionStorage.clear()
  vi.resetAllMocks()
  vi.useRealTimers()
})

describe('оформление из корзины', () => {
  beforeEach(() => {
    vi.mocked(api.getCart).mockResolvedValue(filledCart)
  })

  it('два клика — один запрос в полёте, кнопка заблокирована', async () => {
    const pending = deferred<Order>()
    vi.mocked(api.checkout).mockReturnValue(pending.promise)
    vi.mocked(api.getOrder).mockReturnValue(new Promise(() => {}))
    const { wrapper } = await mountApp('/cart')

    const button = wrapper.find('.checkout-button')
    await button.trigger('click')
    await button.trigger('click')

    expect(api.checkout).toHaveBeenCalledTimes(1)
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toBe('Оформляем…')
    pending.resolve(order('o1'))
    await flushPromises()
  })

  it('ретрай после 503 идёт с тем же ключом', async () => {
    vi.mocked(api.checkout).mockRejectedValueOnce(unavailable()).mockResolvedValueOnce(order('o1'))
    vi.mocked(api.getOrder).mockReturnValue(new Promise(() => {}))
    const { wrapper } = await mountApp('/cart')

    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role=alert]').text()).toContain('Сервис недоступен')
    expect(wrapper.find('.checkout-button').attributes('disabled')).toBeUndefined()

    await wrapper.find('.error-retry').trigger('click')
    await flushPromises()

    const keys = vi.mocked(api.checkout).mock.calls.map(([key]) => key)
    expect(keys).toHaveLength(2)
    expect(keys[0]).toBeTruthy()
    expect(keys[1]).toBe(keys[0])
  })

  it('повторный клик после ошибки — тот же ключ', async () => {
    vi.mocked(api.checkout)
      .mockRejectedValueOnce(
        parseApiError(400, { error: { code: 'FAILED_PRECONDITION', message: 'Not enough stock' } }),
      )
      .mockReturnValueOnce(new Promise(() => {}))
    const { wrapper } = await mountApp('/cart')

    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()
    await wrapper.find('.checkout-button').trigger('click')

    const [first, second] = vi.mocked(api.checkout).mock.calls.map(([key]) => key)
    expect(second).toBe(first)
  })

  it('ключ из sessionStorage переживает перезагрузку посреди попытки', async () => {
    sessionStorage.setItem(
      CHECKOUT_KEY_STORAGE,
      JSON.stringify({ key: 'key-before-reload', cart: 'p1:2' }),
    )
    vi.mocked(api.checkout).mockReturnValue(new Promise(() => {}))
    const { wrapper } = await mountApp('/cart')

    await wrapper.find('.checkout-button').trigger('click')

    expect(api.checkout).toHaveBeenCalledWith('key-before-reload')
  })

  it('ответ потерян, корзина изменилась — новый ключ, старый заказ не переигрывается', async () => {
    vi.mocked(api.checkout)
      .mockRejectedValueOnce(
        parseApiError(504, { error: { code: 'DEADLINE_EXCEEDED', message: 'deadline' } }),
      )
      .mockReturnValueOnce(new Promise(() => {}))
    const { wrapper, router } = await mountApp('/cart')
    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()

    vi.mocked(api.getCart).mockResolvedValue({
      ...filledCart,
      items: [{ ...filledCart.items[0], quantity: 3 }],
    })
    await router.push('/sign-up')
    await router.push('/cart')
    await flushPromises()
    await wrapper.find('.checkout-button').trigger('click')

    const [first, second] = vi.mocked(api.checkout).mock.calls.map(([key]) => key)
    expect(second).not.toBe(first)
  })

  it('успех ведёт на заказ и сбрасывает ключ', async () => {
    vi.mocked(api.checkout).mockResolvedValue(order('o1'))
    vi.mocked(api.getOrder).mockReturnValue(new Promise(() => {}))
    const { wrapper, router } = await mountApp('/cart')

    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/orders/o1')
    expect(sessionStorage.getItem(CHECKOUT_KEY_STORAGE)).toBeNull()
  })

  it('следующее оформление после успеха — с новым ключом', async () => {
    vi.mocked(api.checkout).mockResolvedValue(order('o1'))
    vi.mocked(api.getOrder).mockReturnValue(new Promise(() => {}))
    const { wrapper, router } = await mountApp('/cart')
    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()

    await router.push('/cart')
    await flushPromises()
    await wrapper.find('.checkout-button').trigger('click')
    await flushPromises()

    const [first, second] = vi.mocked(api.checkout).mock.calls.map(([key]) => key)
    expect(second).not.toBe(first)
  })
})

describe('OrderProgress', () => {
  const steps: OrderStatus[] = ['CREATED', 'PAID', 'ASSEMBLING', 'HANDED_TO_COURIER', 'DELIVERED']

  it.each(steps.map((status, index) => [status, index] as const))(
    '%s: пройденные, текущий и оставшиеся шаги',
    (status, index) => {
      const wrapper = mount(OrderProgress, { props: { status } })

      const states = wrapper.findAll('.step').map((li) => li.classes().at(-1))
      expect(states).toEqual(
        steps.map((_, i) => (i < index ? 'done' : i === index ? 'current' : 'pending')),
      )
      expect(wrapper.find('[aria-current=step]').text()).toBe(
        ['Создан', 'Оплачен', 'Собирается', 'Передан курьеру', 'Доставлен'][index],
      )
      expect(wrapper.find('.order-cancelled').exists()).toBe(false)
    },
  )

  it('CANCELLED — отдельное состояние без шагов', () => {
    const wrapper = mount(OrderProgress, { props: { status: 'CANCELLED' } })

    expect(wrapper.find('.order-cancelled').text()).toBe('Заказ отменён')
    expect(wrapper.find('.order-progress').exists()).toBe(false)
  })
})

describe('OrdersPage', () => {
  it('фильтр по статусу из URL уходит в запрос', async () => {
    vi.mocked(api.listOrders).mockResolvedValue(ordersPage([order('o1', 'PAID')]))
    const { wrapper } = await mountApp('/orders?status=PAID')

    expect(api.listOrders).toHaveBeenCalledWith({ status: 'PAID', page_size: 10 })
    expect(wrapper.find('select[name=status]').element).toHaveProperty('value', 'PAID')
    const row = wrapper.find('.order-row')
    expect(row.find('a').text()).toBe('o1')
    expect(row.find('.status').text()).toBe('Оплачен')
    expect(plain(row.find('.price').text())).toBe('200,00 ₽')
  })

  it('неизвестный статус в URL игнорируется', async () => {
    vi.mocked(api.listOrders).mockResolvedValue(ordersPage([]))
    await mountApp('/orders?status=LOST')

    expect(api.listOrders).toHaveBeenCalledWith({ page_size: 10 })
  })

  it('выбор статуса кладёт его в URL и грузит первую страницу заново', async () => {
    vi.mocked(api.listOrders)
      .mockResolvedValueOnce(ordersPage([order('o1')], 'token-2'))
      .mockResolvedValueOnce(ordersPage([order('o9', 'DELIVERED')]))
    const { wrapper, router } = await mountApp('/orders')

    await wrapper.find('select[name=status]').setValue('DELIVERED')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ status: 'DELIVERED' })
    expect(vi.mocked(api.listOrders).mock.calls[1]?.[0]).toEqual({
      status: 'DELIVERED',
      page_size: 10,
    })
    expect(wrapper.findAll('.order-row').map((row) => row.find('a').text())).toEqual(['o9'])
  })

  it('«Все статусы» убирает фильтр из URL', async () => {
    vi.mocked(api.listOrders).mockResolvedValue(ordersPage([]))
    const { wrapper, router } = await mountApp('/orders?status=PAID')

    await wrapper.find('select[name=status]').setValue('')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({})
    expect(api.listOrders).toHaveBeenLastCalledWith({ page_size: 10 })
  })

  it('«Показать ещё» дозагружает по токену и скрывается на пустом', async () => {
    vi.mocked(api.listOrders)
      .mockResolvedValueOnce(ordersPage([order('o1')], 'token-2'))
      .mockResolvedValueOnce(ordersPage([order('o2')]))
    const { wrapper } = await mountApp('/orders?status=CREATED')

    await wrapper.find('.load-more').trigger('click')
    await flushPromises()

    expect(vi.mocked(api.listOrders).mock.calls[1]?.[0]).toEqual({
      status: 'CREATED',
      page_size: 10,
      page_token: 'token-2',
    })
    expect(wrapper.findAll('.order-row').map((row) => row.find('a').text())).toEqual(['o1', 'o2'])
    expect(wrapper.find('.load-more').exists()).toBe(false)
  })

  it('пустой список и ошибка с повтором', async () => {
    vi.mocked(api.listOrders)
      .mockRejectedValueOnce(unavailable())
      .mockResolvedValueOnce(ordersPage([]))
    const { wrapper } = await mountApp('/orders')

    expect(wrapper.find('[role=alert]').text()).toContain('Сервис недоступен')
    expect(wrapper.find('.empty').exists()).toBe(false)
    await wrapper.find('.error-retry').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    expect(wrapper.find('.empty').text()).toBe('Заказов нет.')
  })
})

describe('OrderPage', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  })

  it('позиции, итог, даты и прогресс', async () => {
    vi.mocked(api.getOrder).mockResolvedValue(order('o1', 'ASSEMBLING'))
    const { wrapper } = await mountApp('/orders/o1')

    expect(api.getOrder).toHaveBeenCalledWith('o1')
    expect(wrapper.find('.order-id').text()).toBe('o1')
    expect(wrapper.find('.status').text()).toContain('Собирается')
    expect(wrapper.find('.created-at').text()).not.toBe('—')
    expect(wrapper.find('.updated-at').text()).toBe('—')
    expect(wrapper.find('.order-item').text()).toContain('Товар p1')
    expect(plain(wrapper.find('.total').text())).toBe('Итого: 200,00 ₽')
    expect(wrapper.find('[aria-current=step]').text()).toBe('Собирается')
  })

  it('поллинг доводит до DELIVERED, переживает 503 и останавливается', async () => {
    vi.mocked(api.getOrder)
      .mockResolvedValueOnce(order('o1', 'CREATED'))
      .mockRejectedValueOnce(unavailable())
      .mockResolvedValueOnce(order('o1', 'HANDED_TO_COURIER'))
      .mockResolvedValue(order('o1', 'DELIVERED'))
    const { wrapper } = await mountApp('/orders/o1')
    expect(wrapper.find('.status').text()).toContain('Создан')
    expect(wrapper.find('.polling').exists()).toBe(true)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(wrapper.find('[role=alert]').text()).toContain('Сервис недоступен')
    // повтор не нужен — опрос продолжается сам
    expect(wrapper.find('.error-retry').exists()).toBe(false)
    expect(wrapper.find('.status').text()).toContain('Создан')

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    expect(wrapper.find('.status').text()).toContain('Передан курьеру')

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(wrapper.find('.status').text()).toContain('Доставлен')
    expect(wrapper.find('.polling').exists()).toBe(false)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(api.getOrder).toHaveBeenCalledTimes(4)
  })

  it('CANCELLED останавливает поллинг', async () => {
    vi.mocked(api.getOrder).mockResolvedValue(order('o1', 'CANCELLED'))
    const { wrapper } = await mountApp('/orders/o1')

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)

    expect(api.getOrder).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.order-cancelled').exists()).toBe(true)
  })

  it('уход со страницы останавливает поллинг', async () => {
    vi.mocked(api.getOrder).mockResolvedValue(order('o1', 'PAID'))
    vi.mocked(api.listOrders).mockResolvedValue(ordersPage([]))
    const { router } = await mountApp('/orders/o1')
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(api.getOrder).toHaveBeenCalledTimes(2)

    await router.push('/orders')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)

    expect(api.getOrder).toHaveBeenCalledTimes(2)
  })

  it('переход на другой заказ перезапускает поллинг', async () => {
    vi.mocked(api.getOrder).mockImplementation((id) => Promise.resolve(order(id, 'PAID')))
    const { wrapper, router } = await mountApp('/orders/o1')

    await router.push('/orders/o2')
    await flushPromises()

    expect(api.getOrder).toHaveBeenLastCalledWith('o2')
    expect(wrapper.find('.order-id').text()).toBe('o2')
  })

  it('несуществующий заказ — ошибка, опроса нет', async () => {
    vi.mocked(api.getOrder).mockRejectedValue(
      parseApiError(404, { error: { code: 'NOT_FOUND', message: 'order "x" not found' } }),
    )
    const { wrapper } = await mountApp('/orders/x')

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)

    expect(api.getOrder).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role=alert]').text()).toContain('not found')
  })
})
