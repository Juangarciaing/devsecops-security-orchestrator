import { describe, expect, it } from 'vitest'
import { isTerminalScanStatus } from './types'

describe('isTerminalScanStatus', () => {
  it.each([
    ['pending', false],
    ['running', false],
    ['completed', true],
    ['failed', true],
    ['cancelled', true],
  ] as const)('returns %s -> %s', (status, expected) => {
    expect(isTerminalScanStatus(status)).toBe(expected)
  })
})
