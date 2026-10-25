import { enableAutoUnmount, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import { parseApiError } from '../api/errors'
import { POLL_INTERVAL_MS, usePolling, type Polling } from './usePolling'

enableAutoUnmount(afterEach)

interface Status {
  status: string
}

const unavailable = () => parseApiError(503, { error: { code: 'UNAVAILABLE', message: 'x' } })

// Компонент-обёртка: `usePolling` внутри setup, чтобы сработал `onUnmounted`
function mountPolling(fetch: () => Promise<Status>) {
  let polling: Polling<Status> | undefined
  const wrapper = mount(
    defineComponent({
      setup() {
        polling = usePolling(fetch, (value) => value.status === 'DONE')
        polling.start()
        return () => h('div')
      },
    }),
  )
  if (polling === undefined) throw new Error('setup не выполнился')
  return { wrapper, polling }
}

beforeEach(() => {
  // flushPromises из test-utils ходит через setImmediate — его не подменяем
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('usePolling', () => {
  it('опрашивает с интервалом и останавливается на финальном значении', async () => {
    const fetch = vi
      .fn<() => Promise<Status>>()
      .mockResolvedValueOnce({ status: 'A' })
      .mockResolvedValueOnce({ status: 'B' })
      .mockResolvedValue({ status: 'DONE' })
    const { polling } = mountPolling(fetch)

    await vi.advanceTimersByTimeAsync(0)
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(polling.data.value).toEqual({ status: 'A' })

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS - 1)
    expect(fetch).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetch).toHaveBeenCalledTimes(2)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(polling.data.value).toEqual({ status: 'DONE' })
    expect(polling.active.value).toBe(false)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('временная ошибка показывается, опрос продолжается и ошибка уходит', async () => {
    const fetch = vi
      .fn<() => Promise<Status>>()
      .mockResolvedValueOnce({ status: 'A' })
      .mockRejectedValueOnce(unavailable())
      .mockResolvedValue({ status: 'B' })
    const { polling } = mountPolling(fetch)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(polling.error.value?.kind).toBe('unavailable')
    // последнее известное значение не теряется
    expect(polling.data.value).toEqual({ status: 'A' })
    expect(polling.active.value).toBe(true)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetch).toHaveBeenCalledTimes(3)
    expect(polling.error.value).toBeNull()
    expect(polling.data.value).toEqual({ status: 'B' })
  })

  it('невременная ошибка останавливает опрос', async () => {
    const fetch = vi
      .fn<() => Promise<Status>>()
      .mockRejectedValue(parseApiError(404, { error: { code: 'NOT_FOUND', message: 'nope' } }))
    const { polling } = mountPolling(fetch)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(polling.error.value?.code).toBe('NOT_FOUND')
    expect(polling.active.value).toBe(false)
  })

  it('размонтирование останавливает опрос', async () => {
    const fetch = vi.fn<() => Promise<Status>>().mockResolvedValue({ status: 'A' })
    const { wrapper } = mountPolling(fetch)

    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS)
    expect(fetch).toHaveBeenCalledTimes(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 5)

    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('ответ, пришедший после stop, отбрасывается', async () => {
    let resolve: (value: Status) => void = () => {}
    const fetch = vi.fn<() => Promise<Status>>().mockReturnValue(
      new Promise((r) => {
        resolve = r
      }),
    )
    const { polling } = mountPolling(fetch)

    polling.stop()
    resolve({ status: 'A' })
    await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 3)

    expect(polling.data.value).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
