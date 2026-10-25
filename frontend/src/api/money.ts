import type { Money } from './types'

const NANOS_PER_KOPECK = 10_000_000
const KOPECKS_PER_UNIT = 100
// Неразрывный пробел: разряды и знак валюты не переносятся на новую строку
const NBSP = ' '
const RUBLES_INPUT = /^(\d+)(?:[.,](\d{1,2}))?$/

export function moneyToKopecks(money: Money): number {
  return money.units * KOPECKS_PER_UNIT + Math.trunc(money.nanos / NANOS_PER_KOPECK)
}

// «1 234,50 ₽»; не-рубли — с кодом валюты вместо знака
export function formatMoney(money: Money): string {
  const kopecks = moneyToKopecks(money)
  const sign = kopecks < 0 ? '-' : ''
  const absolute = Math.abs(kopecks)
  const units = Math.trunc(absolute / KOPECKS_PER_UNIT)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, NBSP)
  const fraction = (absolute % KOPECKS_PER_UNIT).toString().padStart(2, '0')
  const currency = money.currency_code === 'RUB' ? '₽' : money.currency_code
  return `${sign}${units},${fraction}${NBSP}${currency}`
}

export class MoneyInputError extends Error {
  constructor(input: string) {
    super(`Некорректная сумма «${input}»: ожидаются рубли, например 1234 или 1234,50`)
    this.name = 'MoneyInputError'
  }
}

// Рубли из поля фильтра → копейки для `*_kopecks`. Пустой ввод — `undefined` (фильтра нет);
// отрицательные, больше двух знаков после запятой и мусор — `MoneyInputError`.
export function rublesToKopecks(input: string): number | undefined {
  const normalized = input.replace(/\s/g, '')
  if (normalized === '') {
    return undefined
  }
  const match = RUBLES_INPUT.exec(normalized)
  if (match === null) {
    throw new MoneyInputError(input)
  }
  const kopecks = Number(match[1]) * KOPECKS_PER_UNIT + Number((match[2] ?? '').padEnd(2, '0'))
  if (!Number.isSafeInteger(kopecks)) {
    throw new MoneyInputError(input)
  }
  return kopecks
}
