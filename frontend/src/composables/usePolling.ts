// Поллинг ресурса: запрос, пауза, следующий запрос (без наложения запросов друг на друга).
// Останавливается, когда `isDone(data)`, на невременной ошибке и при размонтировании;
// временную ошибку (502/503/504, сеть) показывает и продолжает опрос.
import { getCurrentInstance, onUnmounted, ref, shallowRef, type Ref } from 'vue'

import { ApiError, toApiError } from '../api/errors'

export const POLL_INTERVAL_MS = 1500

export interface Polling<T> {
  data: Ref<T | null>
  error: Ref<ApiError | null>
  // Опрос идёт (следующий запрос запланирован или в полёте)
  active: Ref<boolean>
  start: () => void
  stop: () => void
}

function isTransient(error: ApiError): boolean {
  return error.kind === 'unavailable' || error.kind === 'network'
}

export function usePolling<T>(
  fetch: () => Promise<T>,
  isDone: (data: T) => boolean,
): Polling<T> {
  const data = shallowRef<T | null>(null)
  const error = ref<ApiError | null>(null)
  const active = ref(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  // Номер запуска: ответ запроса из прошлого запуска (stop/start посреди запроса) отбрасывается
  let generation = 0

  async function tick(current: number): Promise<void> {
    timer = undefined
    let keepGoing = true
    try {
      const value = await fetch()
      if (current !== generation) return
      data.value = value
      error.value = null
      keepGoing = !isDone(value)
    } catch (e) {
      if (current !== generation) return
      error.value = toApiError(e)
      keepGoing = isTransient(error.value)
    }
    if (keepGoing) {
      timer = setTimeout(() => void tick(current), POLL_INTERVAL_MS)
    } else {
      active.value = false
    }
  }

  function stop(): void {
    generation++
    if (timer !== undefined) clearTimeout(timer)
    timer = undefined
    active.value = false
  }

  function start(): void {
    stop()
    data.value = null
    error.value = null
    active.value = true
    void tick(generation)
  }

  if (getCurrentInstance() !== null) onUnmounted(stop)

  return { data, error, active, start, stop }
}
