import { beforeEach, describe, expect, it } from 'vitest'
import { clearToken, getToken, setToken } from './token'

describe('token storage', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns null when no token has been stored', () => {
    expect(getToken()).toBeNull()
  })

  it('returns the exact token that was stored', () => {
    setToken('abc.def.ghi')

    expect(getToken()).toBe('abc.def.ghi')
  })

  it('overwrites a previously stored token with a new one', () => {
    setToken('first-token')
    setToken('second-token')

    expect(getToken()).toBe('second-token')
  })

  it('removes the token so getToken returns null again', () => {
    setToken('to-be-cleared')
    clearToken()

    expect(getToken()).toBeNull()
  })
})
