import { enableAutoUnmount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { signIn, signOut } from '../api/auth'
import * as api from '../api/endpoints'
import { parseApiError } from '../api/errors'
import { user } from '../api/testing'
import type { Cart, CartItem, Money, Product, ProductsPage } from '../api/types'
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

function product(id: string, overrides: Partial<Product> = {}): Product {
  return {
    product_id: id,
    seller_id: 's1',
    offer_id: `OF-${id}`,
    name: `Товар ${id}`,
    category: 'books',
    price: rub(159000),
    stock: 5,
    created_at: null,
    updated_at: null,
    ...overrides,
  }
}

// Текст без неразрывных пробелов `formatMoney` — чтобы сравнивать с обычными литералами
function plain(text: string | undefined): string {
  return (text ?? '').replace(/\u00a0/g, ' ')
}

function page(products: Product[], nextPageToken = ''): ProductsPage {
  return { products, next_page_token: nextPageToken }
}

function cartItem(id: string, overrides: Partial<CartItem> = {}): CartItem {
  return {
    product_id: id,
    name: `Товар ${id}`,
    quantity: 1,
    unit_price: rub(10000),
    available: 5,
    ...overrides,
  }
}

function cart(items: CartItem[], totalKopecks: number): Cart {
  return { items, total: rub(totalKopecks) }
}

beforeEach(() => {
  signOut()
  vi.mocked(api.getMe).mockResolvedValue(user)
})

afterEach(() => {
  signOut()
  vi.resetAllMocks()
})

describe('CatalogPage', () => {
  it('фильтры из URL уходят в запрос, цена — в копейках', async () => {
    vi.mocked(api.searchProducts).mockResolvedValue(page([product('p1')]))

    const { wrapper } = await mountApp(
      '/?query=книга&category=books&min_price=100,5&max_price=2000&sort=price_desc',
    )

    expect(api.searchProducts).toHaveBeenCalledWith({
      query: 'книга',
      category: 'books',
      min_price_kopecks: 10050,
      max_price_kopecks: 200000,
      sort: 'price_desc',
      page_size: 10,
    })
    expect(wrapper.find('input[name=min_price]').element).toHaveProperty('value', '100,5')
    expect(wrapper.find('.product-item').text()).toContain('Товар p1')
    expect(plain(wrapper.find('.product-item').text())).toContain('1 590,00 ₽')
  })

  it('форма кладёт фильтры в URL без пустых значений', async () => {
    vi.mocked(api.searchProducts).mockResolvedValue(page([]))
    const { wrapper, router } = await mountApp('/')

    await wrapper.find('input[name=query]').setValue(' чайник ')
    await wrapper.find('input[name=max_price]').setValue('3 500')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(router.currentRoute.value.query).toEqual({ query: 'чайник', max_price: '3 500' })
    expect(api.searchProducts).toHaveBeenLastCalledWith({
      query: 'чайник',
      max_price_kopecks: 350000,
      sort: 'name',
      page_size: 10,
    })
  })

  it('некорректная цена — сообщение, запроса нет', async () => {
    const { wrapper } = await mountApp('/?min_price=abc')

    expect(api.searchProducts).not.toHaveBeenCalled()
    expect(wrapper.find('.input-error').text()).toContain('Некорректная сумма «abc»')
    expect(wrapper.find('.empty').exists()).toBe(false)
  })

  it('«Показать ещё» дозагружает по токену, кнопка скрывается на пустом токене', async () => {
    vi.mocked(api.searchProducts)
      .mockResolvedValueOnce(page([product('p1')], 'token-2'))
      .mockResolvedValueOnce(page([product('p2')], ''))
    const { wrapper } = await mountApp('/?category=books')

    await wrapper.find('.load-more').trigger('click')
    await flushPromises()

    expect(vi.mocked(api.searchProducts).mock.calls[1]?.[0]).toEqual({
      category: 'books',
      sort: 'name',
      page_size: 10,
      page_token: 'token-2',
    })
    expect(wrapper.findAll('.product-item').map((li) => li.find('a').text())).toEqual([
      'Товар p1',
      'Товар p2',
    ])
    expect(wrapper.find('.load-more').exists()).toBe(false)
  })

  it('смена фильтров сбрасывает список и токен', async () => {
    vi.mocked(api.searchProducts)
      .mockResolvedValueOnce(page([product('p1')], 'token-2'))
      .mockResolvedValueOnce(page([product('p9')], ''))
    const { wrapper, router } = await mountApp('/')

    await router.push('/?sort=newest')
    await flushPromises()

    expect(vi.mocked(api.searchProducts).mock.calls[1]?.[0]).toEqual({
      sort: 'newest',
      page_size: 10,
    })
    expect(wrapper.findAll('.product-item')).toHaveLength(1)
    expect(wrapper.find('.product-item a').text()).toBe('Товар p9')
    expect(wrapper.find('select[name=sort]').element).toHaveProperty('value', 'newest')
  })

  it('пустой результат', async () => {
    vi.mocked(api.searchProducts).mockResolvedValue(page([]))
    const { wrapper } = await mountApp('/?query=нет-такого')

    expect(wrapper.find('.empty').text()).toBe('Ничего не найдено.')
    expect(wrapper.find('.load-more').exists()).toBe(false)
  })

  it('состояние загрузки', async () => {
    vi.mocked(api.searchProducts).mockReturnValue(new Promise(() => {}))
    const { wrapper } = await mountApp('/')

    expect(wrapper.find('.loading').exists()).toBe(true)
    expect(wrapper.find('.empty').exists()).toBe(false)
  })

  it('недоступный каталог — ошибка с повтором', async () => {
    vi.mocked(api.searchProducts)
      .mockRejectedValueOnce(parseApiError(503, { error: { code: 'UNAVAILABLE', message: 'x' } }))
      .mockResolvedValueOnce(page([product('p1')]))
    const { wrapper } = await mountApp('/')

    expect(wrapper.find('[role=alert]').text()).toContain('Сервис недоступен')
    await wrapper.find('.error-retry').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role=alert]').exists()).toBe(false)
    expect(wrapper.find('.product-item').exists()).toBe(true)
  })
})

describe('ProductPage', () => {
  it('показывает карточку', async () => {
    vi.mocked(api.getProduct).mockResolvedValue(product('p1', { stock: 7 }))
    const { wrapper } = await mountApp('/products/p1')

    expect(api.getProduct).toHaveBeenCalledWith('p1')
    expect(wrapper.find('h1').text()).toBe('Товар p1')
    expect(plain(wrapper.find('.price').text())).toBe('1 590,00 ₽')
    expect(wrapper.find('.stock').text()).toBe('7 шт.')
    expect(wrapper.text()).toContain('books')
    expect(wrapper.text()).toContain('OF-p1')
  })

  it('«В корзину» отправляет product_id и quantity', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    vi.mocked(api.getProduct).mockResolvedValue(product('p1'))
    vi.mocked(api.addCartItem).mockResolvedValue(cart([cartItem('p1', { quantity: 3 })], 30000))
    const { wrapper } = await mountApp('/products/p1')

    await wrapper.find('.increment').trigger('click')
    await wrapper.find('.increment').trigger('click')
    await wrapper.find('form.add-to-cart').trigger('submit')
    await flushPromises()

    expect(api.addCartItem).toHaveBeenCalledWith({ product_id: 'p1', quantity: 3 })
    expect(wrapper.find('.added').text()).toContain('Добавлено в корзину')
  })

  it('количество вводится руками и не меньше 1', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    vi.mocked(api.getProduct).mockResolvedValue(product('p1'))
    vi.mocked(api.addCartItem).mockResolvedValue(cart([], 0))
    const { wrapper } = await mountApp('/products/p1')

    await wrapper.find('input[name=quantity]').setValue('0')
    expect(wrapper.find('input[name=quantity]').element).toHaveProperty('value', '1')
    await wrapper.find('input[name=quantity]').setValue('12')
    await wrapper.find('form.add-to-cart').trigger('submit')
    await flushPromises()

    expect(api.addCartItem).toHaveBeenCalledWith({ product_id: 'p1', quantity: 12 })
  })

  it('без токена «В корзину» ведёт на вход', async () => {
    vi.mocked(api.getProduct).mockResolvedValue(product('p1'))
    const { wrapper, router } = await mountApp('/products/p1')

    await wrapper.find('form.add-to-cart').trigger('submit')
    await flushPromises()

    expect(api.addCartItem).not.toHaveBeenCalled()
    expect(router.currentRoute.value.fullPath).toBe('/sign-in?next=/products/p1')
  })

  it('превышение остатка показывает details бэкенда', async () => {
    signIn({ access_token: 't', expires_at: null, user })
    vi.mocked(api.getProduct).mockResolvedValue(product('p1', { stock: 1 }))
    vi.mocked(api.addCartItem).mockRejectedValue(
      parseApiError(400, {
        error: {
          code: 'FAILED_PRECONDITION',
          message: 'Not enough stock',
          details: [
            {
              '@type': 'type.googleapis.com/google.rpc.PreconditionFailure',
              violations: [
                { type: 'INSUFFICIENT_STOCK', subject: 'product:p1', description: 'only 1 left' },
              ],
            },
          ],
        },
      }),
    )
    const { wrapper } = await mountApp('/products/p1')

    await wrapper.find('.increment').trigger('click')
    await wrapper.find('form.add-to-cart').trigger('submit')
    await flushPromises()

    expect(api.addCartItem).toHaveBeenCalledWith({ product_id: 'p1', quantity: 2 })
    const box = wrapper.find('[role=alert]')
    expect(box.text()).toContain('Not enough stock')
    expect(box.text()).toContain('INSUFFICIENT_STOCK')
    expect(box.text()).toContain('only 1 left')
    expect(wrapper.find('.added').exists()).toBe(false)
  })

  it('несуществующий товар — ошибка', async () => {
    vi.mocked(api.getProduct).mockRejectedValue(
      parseApiError(404, { error: { code: 'NOT_FOUND', message: 'product "x" not found' } }),
    )
    const { wrapper } = await mountApp('/products/x')

    expect(wrapper.find('h1').text()).toBe('Товар')
    expect(wrapper.find('[role=alert]').text()).toContain('not found')
  })
})

describe('CartPage', () => {
  beforeEach(() => {
    signIn({ access_token: 't', expires_at: null, user })
  })

  it('позиции, цена за единицу, остаток, нехватка и итог', async () => {
    vi.mocked(api.getCart).mockResolvedValue(
      cart(
        [
          cartItem('p1', { quantity: 2, unit_price: rub(123450), available: 5 }),
          cartItem('p2', { quantity: 4, available: 1 }),
        ],
        286900,
      ),
    )
    const { wrapper } = await mountApp('/cart')

    const rows = wrapper.findAll('.cart-item')
    expect(rows).toHaveLength(2)
    expect(plain(rows[0]?.text())).toContain('1 234,50 ₽')
    expect(rows[0]?.classes()).not.toContain('shortage')
    expect(rows[1]?.classes()).toContain('shortage')
    expect(rows[1]?.find('.available').text()).toContain('не хватает 3')
    expect(plain(wrapper.find('.total').text())).toBe('Итого: 2 869,00 ₽')
  })

  it('удаление позиции обновляет корзину', async () => {
    vi.mocked(api.getCart).mockResolvedValue(
      cart([cartItem('p1'), cartItem('p2', { unit_price: rub(5000) })], 15000),
    )
    vi.mocked(api.removeCartItem).mockResolvedValue(
      cart([cartItem('p2', { unit_price: rub(5000) })], 5000),
    )
    const { wrapper } = await mountApp('/cart')

    await wrapper.findAll('.remove')[0]?.trigger('click')
    await flushPromises()

    expect(api.removeCartItem).toHaveBeenCalledWith('p1')
    expect(wrapper.findAll('.cart-item')).toHaveLength(1)
    expect(wrapper.find('.cart-item').text()).toContain('Товар p2')
    expect(plain(wrapper.find('.total').text())).toBe('Итого: 50,00 ₽')
  })

  it('удаление последней позиции — пустая корзина', async () => {
    vi.mocked(api.getCart).mockResolvedValue(cart([cartItem('p1')], 10000))
    vi.mocked(api.removeCartItem).mockResolvedValue(cart([], 0))
    const { wrapper } = await mountApp('/cart')

    await wrapper.find('.remove').trigger('click')
    await flushPromises()

    expect(wrapper.find('.empty').text()).toContain('Корзина пуста')
    expect(wrapper.find('.total').exists()).toBe(false)
  })

  it('ошибка удаления показывается, корзина остаётся', async () => {
    vi.mocked(api.getCart).mockResolvedValue(cart([cartItem('p1')], 10000))
    vi.mocked(api.removeCartItem).mockRejectedValue(
      parseApiError(504, { error: { code: 'DEADLINE_EXCEEDED', message: 'deadline' } }),
    )
    const { wrapper } = await mountApp('/cart')

    await wrapper.find('.remove').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role=alert]').text()).toContain('Сервис недоступен')
    expect(wrapper.findAll('.cart-item')).toHaveLength(1)
  })
})
