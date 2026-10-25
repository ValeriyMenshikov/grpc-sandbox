import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, parseApiError, UNAVAILABLE_MESSAGE } from '../api/errors'
import ErrorBox from './ErrorBox.vue'

function items(wrapper: ReturnType<typeof mount>): string[] {
  return wrapper.findAll('.error-details li').map((li) => li.text())
}

describe('ErrorBox', () => {
  it('ошибка стенда: сообщение, код и details поштучно', () => {
    const error = parseApiError(400, {
      error: {
        code: 'INVALID_ARGUMENT',
        message: 'Quantity exceeds stock',
        details: [
          {
            '@type': 'type.googleapis.com/google.rpc.BadRequest',
            field_violations: [
              { field: 'quantity', description: 'must be <= 5' },
              { field: 'product_id', description: 'required' },
            ],
          },
        ],
      },
    })

    const wrapper = mount(ErrorBox, { props: { error } })

    expect(wrapper.find('.error-message').text()).toContain('Quantity exceeds stock')
    expect(wrapper.find('.error-code').text()).toBe('INVALID_ARGUMENT')
    expect(items(wrapper)).toEqual([
      'Поле «quantity»: must be <= 5',
      'Поле «product_id»: required',
    ])
    expect(wrapper.find('.error-retry').exists()).toBe(false)
  })

  it('422: список полей FastAPI', () => {
    const error = parseApiError(422, {
      detail: [{ loc: ['query', 'min_price_kopecks'], msg: 'Input should be a valid integer', type: 'int' }],
    })

    const wrapper = mount(ErrorBox, { props: { error } })

    expect(wrapper.find('.error-message').text()).toBe('Запрос не прошёл проверку')
    expect(items(wrapper)).toEqual(['query.min_price_kopecks: Input should be a valid integer'])
  })

  it('недоступность с колбэком: сообщение и кнопка повтора', async () => {
    const retry = vi.fn()
    const error = parseApiError(503, undefined)

    const wrapper = mount(ErrorBox, { props: { error, retry } })
    await wrapper.find('.error-retry').trigger('click')

    expect(wrapper.find('.error-message').text()).toBe(UNAVAILABLE_MESSAGE)
    expect(retry).toHaveBeenCalledOnce()
  })

  it('недоступность без колбэка: кнопки нет', () => {
    const wrapper = mount(ErrorBox, { props: { error: parseApiError(504, undefined) } })

    expect(wrapper.find('.error-message').text()).toBe(UNAVAILABLE_MESSAGE)
    expect(wrapper.find('.error-retry').exists()).toBe(false)
  })

  it('сетевой сбой тоже можно повторить', () => {
    const error = ApiError.network()

    const wrapper = mount(ErrorBox, { props: { error, retry: vi.fn() } })

    expect(wrapper.find('.error-message').text()).toBe(error.message)
    expect(wrapper.find('.error-retry').exists()).toBe(true)
  })

  it('401 и неизвестная ошибка: только сообщение, без повтора', () => {
    for (const status of [401, 418]) {
      const error = parseApiError(status, undefined)

      const wrapper = mount(ErrorBox, { props: { error, retry: vi.fn() } })

      expect(wrapper.find('.error-message').text()).toBe(error.message)
      expect(wrapper.find('.error-details').exists()).toBe(false)
      expect(wrapper.find('.error-retry').exists()).toBe(false)
    }
  })
})
