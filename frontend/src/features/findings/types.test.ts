import { describe, expect, it } from 'vitest'
import { isSuppressed } from './types'

describe('isSuppressed', () => {
  it.each([
    ['open', false],
    ['resolved', false],
    ['suppressed', true],
    ['false_positive', false],
  ] as const)('%s -> %s', (status, expected) => {
    expect(isSuppressed(status)).toBe(expected)
  })
})
