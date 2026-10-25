import { describe, expect, it } from 'vitest'

import {
  ApiError,
  describeDetails,
  describeValidation,
  NETWORK_MESSAGE,
  parseApiError,
  UNAVAILABLE_MESSAGE,
  type RichDetail,
} from './errors'

const standBody = (code: string, message: string, details: unknown[] = []) => ({
  error: { code, message, details },
})

describe('parseApiError', () => {
  it('ошибка стенда: код, сообщение, details', () => {
    const detail = {
      '@type': 'type.googleapis.com/google.rpc.ResourceInfo',
      resource_type: 'order',
      resource_name: '42',
    }
    const error = parseApiError(404, standBody('NOT_FOUND', 'order not found', [detail]))

    expect(error).toBeInstanceOf(ApiError)
    expect(error.kind).toBe('stand')
    expect(error.httpStatus).toBe(404)
    expect(error.code).toBe('NOT_FOUND')
    expect(error.message).toBe('order not found')
    expect(error.details).toEqual([detail])
  })

  it('details без @type отбрасываются', () => {
    const error = parseApiError(400, standBody('INVALID_ARGUMENT', 'bad', [{ foo: 1 }, 'x']))
    expect(error.details).toEqual([])
  })

  it('422 FastAPI — validation со списком полей', () => {
    const issue = { loc: ['query', 'page_size'], msg: 'Input should be >= 0', type: 'ge' }
    const error = parseApiError(422, { detail: [issue] })

    expect(error.kind).toBe('validation')
    expect(error.validation).toEqual([issue])
    expect(describeValidation(error.validation)).toEqual(['query.page_size: Input should be >= 0'])
  })

  it('401 стенда — unauthorized с кодом', () => {
    const error = parseApiError(401, standBody('UNAUTHENTICATED', 'invalid credentials'))
    expect(error.kind).toBe('unauthorized')
    expect(error.code).toBe('UNAUTHENTICATED')
    expect(error.message).toBe('invalid credentials')
  })

  it('401 без тела — unauthorized', () => {
    expect(parseApiError(401, undefined).kind).toBe('unauthorized')
  })

  it.each([503, 504])('%d стенда — unavailable, исходное сообщение сохранено', (status) => {
    const detail = {
      '@type': 'type.googleapis.com/google.rpc.ErrorInfo',
      reason: 'DEPENDENCY_UNAVAILABLE',
      domain: 'stand',
      metadata: { dependency: 'catalog' },
    }
    const error = parseApiError(status, standBody('UNAVAILABLE', 'catalog is unavailable', [detail]))

    expect(error.kind).toBe('unavailable')
    expect(error.message).toBe(UNAVAILABLE_MESSAGE)
    expect(error.details).toEqual([detail])
  })

  it('502 от nginx без JSON — unavailable', () => {
    expect(parseApiError(502, undefined).kind).toBe('unavailable')
  })

  it('прочее — unknown', () => {
    const error = parseApiError(500, undefined)
    expect(error.kind).toBe('unknown')
    expect(error.message).toContain('500')
  })

  it('сетевой сбой — network', () => {
    const error = ApiError.network()
    expect(error.kind).toBe('network')
    expect(error.httpStatus).toBe(0)
    expect(error.message).toBe(NETWORK_MESSAGE)
  })
})

describe('describeDetails', () => {
  const rpc = (name: string, fields: Record<string, unknown>): RichDetail => ({
    '@type': `type.googleapis.com/google.rpc.${name}`,
    ...fields,
  })

  it('BadRequest — по строке на нарушение поля', () => {
    const detail = rpc('BadRequest', {
      field_violations: [
        { field: 'email', description: 'must be a valid email' },
        { field: 'password', description: 'too short' },
      ],
    })
    expect(describeDetails([detail])).toEqual([
      'Поле «email»: must be a valid email',
      'Поле «password»: too short',
    ])
  })

  it('PreconditionFailure — тип, субъект, описание', () => {
    const detail = rpc('PreconditionFailure', {
      violations: [{ type: 'STOCK', subject: 'product/p1', description: 'only 2 left' }],
    })
    expect(describeDetails([detail])).toEqual(['Условие STOCK (product/p1): only 2 left'])
  })

  it('ErrorInfo — причина, домен, metadata', () => {
    const detail = rpc('ErrorInfo', {
      reason: 'DEPENDENCY_UNAVAILABLE',
      domain: 'stand',
      metadata: { dependency: 'catalog' },
    })
    expect(describeDetails([detail])).toEqual([
      'Причина DEPENDENCY_UNAVAILABLE (stand); dependency=catalog',
    ])
  })

  it('ErrorInfo без metadata', () => {
    expect(describeDetails([rpc('ErrorInfo', { reason: 'X', domain: 'stand' })])).toEqual([
      'Причина X (stand)',
    ])
  })

  it('QuotaFailure — субъект и описание', () => {
    const detail = rpc('QuotaFailure', {
      violations: [{ subject: 'user/u1', description: 'rate limit exceeded' }],
    })
    expect(describeDetails([detail])).toEqual(['Квота user/u1: rate limit exceeded'])
  })

  it('ResourceInfo — тип и имя ресурса', () => {
    const detail = rpc('ResourceInfo', { resource_type: 'order', resource_name: '42' })
    expect(describeDetails([detail])).toEqual(['Ресурс order «42»'])
  })

  it('неизвестный @type — как есть', () => {
    const detail = { '@type': 'type.googleapis.com/acme.Custom', answer: 42 }
    expect(describeDetails([detail])).toEqual([JSON.stringify(detail)])
  })

  it('несколько details — подряд', () => {
    const details = [
      rpc('ErrorInfo', { reason: 'A', domain: 'd' }),
      rpc('QuotaFailure', { violations: [{ subject: 's', description: 'q' }] }),
    ]
    expect(describeDetails(details)).toEqual(['Причина A (d)', 'Квота s: q'])
  })
})
