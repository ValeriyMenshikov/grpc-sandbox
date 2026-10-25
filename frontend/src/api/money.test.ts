import { describe, expect, it } from 'vitest'

import { formatMoney, MoneyInputError, moneyToKopecks, rublesToKopecks } from './money'

const rub = (units: number, nanos = 0) => ({ currency_code: 'RUB', units, nanos })
// Неразрывные пробелы → обычные, чтобы ожидания читались
const plain = (value: string) => value.replace(/ /g, ' ')

describe('formatMoney', () => {
  it.each([
    [rub(1234, 500_000_000), '1 234,50 ₽'],
    [rub(0), '0,00 ₽'],
    [rub(5, 10_000_000), '5,01 ₽'],
    [rub(1_000_000), '1 000 000,00 ₽'],
    [rub(999), '999,00 ₽'],
    [rub(-12, -340_000_000), '-12,34 ₽'],
  ])('%j → %s', (money, expected) => {
    expect(plain(formatMoney(money))).toBe(expected)
  })

  it('разряды и знак валюты разделены неразрывным пробелом', () => {
    expect(formatMoney(rub(1234, 500_000_000))).toBe('1 234,50 ₽')
  })

  it('не-рубли — с кодом валюты', () => {
    expect(plain(formatMoney({ currency_code: 'USD', units: 3, nanos: 0 }))).toBe('3,00 USD')
  })

  it('moneyToKopecks', () => {
    expect(moneyToKopecks(rub(12, 340_000_000))).toBe(1234)
  })
})

describe('rublesToKopecks', () => {
  it.each([
    ['1234', 123_400],
    ['1234,5', 123_450],
    ['1234.50', 123_450],
    ['0,01', 1],
    [' 1 234 ', 123_400],
    ['0', 0],
  ])('%s → %d', (input, expected) => {
    expect(rublesToKopecks(input)).toBe(expected)
  })

  it.each(['', '   '])('пустой ввод «%s» — фильтра нет', (input) => {
    expect(rublesToKopecks(input)).toBeUndefined()
  })

  it.each(['-5', '1,234', 'abc', '1e3', '12,', ',5', '99999999999999999999'])(
    'некорректный ввод «%s»',
    (input) => {
      expect(() => rublesToKopecks(input)).toThrow(MoneyInputError)
    },
  )
})
