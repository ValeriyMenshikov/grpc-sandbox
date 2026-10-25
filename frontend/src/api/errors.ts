// Единый разбор ошибок gateway: тело стенда `{"error":{code,message,details}}`, 422 FastAPI
// `{"detail":[...]}`, 401, недоступность (502 от nginx, 503/504 от gateway) и сетевые сбои.

export type ApiErrorKind = 'stand' | 'validation' | 'unauthorized' | 'unavailable' | 'network' | 'unknown'

// google.rpc rich detail в JSON (`MessageToDict`): `@type` + поля сообщения
export interface RichDetail {
  '@type': string
  [field: string]: unknown
}

// Элемент 422 FastAPI
export interface ValidationIssue {
  loc: (string | number)[]
  msg: string
  type: string
}

export const UNAVAILABLE_MESSAGE = 'Сервис недоступен, попробуйте снова'
export const NETWORK_MESSAGE = 'Нет связи с сервером, попробуйте снова'
export const VALIDATION_MESSAGE = 'Запрос не прошёл проверку'
export const UNAUTHORIZED_MESSAGE = 'Требуется вход'

// 502 — nginx не достучался до gateway; 503 — сосед gateway недоступен; 504 — deadline
const UNAVAILABLE_STATUSES = new Set([502, 503, 504])

interface ApiErrorInit {
  kind: ApiErrorKind
  httpStatus: number
  message: string
  code?: string
  details?: RichDetail[]
  validation?: ValidationIssue[]
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  // 0 — ответа не было (сетевой сбой)
  readonly httpStatus: number
  // Имя gRPC-статуса из тела стенда (`NOT_FOUND`, `FAILED_PRECONDITION`, ...), иначе пусто
  readonly code: string
  readonly details: RichDetail[]
  readonly validation: ValidationIssue[]

  constructor(init: ApiErrorInit) {
    super(init.message)
    this.name = 'ApiError'
    this.kind = init.kind
    this.httpStatus = init.httpStatus
    this.code = init.code ?? ''
    this.details = init.details ?? []
    this.validation = init.validation ?? []
  }

  static network(): ApiError {
    return new ApiError({ kind: 'network', httpStatus: 0, message: NETWORK_MESSAGE })
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isRichDetail(value: unknown): value is RichDetail {
  return isRecord(value) && typeof value['@type'] === 'string'
}

function isValidationIssue(value: unknown): value is ValidationIssue {
  return isRecord(value) && Array.isArray(value.loc) && typeof value.msg === 'string'
}

// Ошибка из статуса и уже разобранного JSON-тела (`undefined` — тело не JSON или пустое)
export function parseApiError(httpStatus: number, body: unknown): ApiError {
  const unavailable = UNAVAILABLE_STATUSES.has(httpStatus)
  if (isRecord(body) && isRecord(body.error)) {
    const { code, message, details } = body.error
    const serverMessage = typeof message === 'string' ? message : ''
    const kind: ApiErrorKind =
      httpStatus === 401 ? 'unauthorized' : unavailable ? 'unavailable' : 'stand'
    return new ApiError({
      kind,
      httpStatus,
      code: typeof code === 'string' ? code : '',
      message: unavailable ? UNAVAILABLE_MESSAGE : serverMessage || `HTTP ${httpStatus}`,
      details: Array.isArray(details) ? details.filter(isRichDetail) : [],
    })
  }
  if (httpStatus === 422 && isRecord(body) && Array.isArray(body.detail)) {
    return new ApiError({
      kind: 'validation',
      httpStatus,
      message: VALIDATION_MESSAGE,
      validation: body.detail.filter(isValidationIssue),
    })
  }
  if (httpStatus === 401) {
    return new ApiError({ kind: 'unauthorized', httpStatus, message: UNAUTHORIZED_MESSAGE })
  }
  if (unavailable) {
    return new ApiError({ kind: 'unavailable', httpStatus, message: UNAVAILABLE_MESSAGE })
  }
  return new ApiError({ kind: 'unknown', httpStatus, message: `Ошибка сервера: HTTP ${httpStatus}` })
}

function records(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.filter(isRecord) : []
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value)
}

// Короткое имя типа: `type.googleapis.com/google.rpc.BadRequest` → `google.rpc.BadRequest`
function typeName(detail: RichDetail): string {
  return detail['@type'].split('/').pop() ?? detail['@type']
}

function describeDetail(detail: RichDetail): string[] {
  switch (typeName(detail)) {
    case 'google.rpc.BadRequest':
      return records(detail.field_violations).map(
        (v) => `Поле «${text(v.field)}»: ${text(v.description)}`,
      )
    case 'google.rpc.PreconditionFailure':
      return records(detail.violations).map(
        (v) => `Условие ${text(v.type)} (${text(v.subject)}): ${text(v.description)}`,
      )
    case 'google.rpc.QuotaFailure':
      return records(detail.violations).map(
        (v) => `Квота ${text(v.subject)}: ${text(v.description)}`,
      )
    case 'google.rpc.ErrorInfo': {
      const metadata = isRecord(detail.metadata)
        ? Object.entries(detail.metadata).map(([key, value]) => `${key}=${text(value)}`)
        : []
      const suffix = metadata.length > 0 ? `; ${metadata.join(', ')}` : ''
      return [`Причина ${text(detail.reason)} (${text(detail.domain)})${suffix}`]
    }
    case 'google.rpc.ResourceInfo': {
      const description = text(detail.description)
      const suffix = description ? `: ${description}` : ''
      return [`Ресурс ${text(detail.resource_type)} «${text(detail.resource_name)}»${suffix}`]
    }
    default:
      // Неизвестный тип — как есть, чтобы ничего не потерять
      return [JSON.stringify(detail)]
  }
}

// Rich details построчно — для показа пользователю поштучно
export function describeDetails(details: RichDetail[]): string[] {
  return details.flatMap(describeDetail)
}

// Ошибки 422 FastAPI построчно: `query.min_price_kopecks: Input should be ...`
export function describeValidation(issues: ValidationIssue[]): string[] {
  return issues.map((issue) => `${issue.loc.join('.')}: ${issue.msg}`)
}

// Любое пойманное исключение — в `ApiError` для показа (`catch (e)` в страницах)
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error
  }
  const message = error instanceof Error ? error.message : String(error)
  return new ApiError({ kind: 'unknown', httpStatus: 0, message })
}
