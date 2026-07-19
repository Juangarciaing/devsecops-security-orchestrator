import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '@/test/msw/server'
import { apiClient } from './client'
import { getToken, setToken } from './token'

describe('apiClient request interceptor', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('attaches an Authorization Bearer header when a token is stored', async () => {
    setToken('a-valid-token')
    let receivedAuthHeader: string | null = null

    server.use(
      http.get('*/probe', ({ request }) => {
        receivedAuthHeader = request.headers.get('Authorization')
        return HttpResponse.json({ ok: true })
      }),
    )

    await apiClient.get('/probe')

    expect(receivedAuthHeader).toBe('Bearer a-valid-token')
  })

  it('sends no Authorization header when no token is stored', async () => {
    let receivedAuthHeader: string | null = 'unset'

    server.use(
      http.get('*/probe', ({ request }) => {
        receivedAuthHeader = request.headers.get('Authorization')
        return HttpResponse.json({ ok: true })
      }),
    )

    await apiClient.get('/probe')

    expect(receivedAuthHeader).toBeNull()
  })
})

describe('apiClient response interceptor — global 401 handling', () => {
  const originalLocation = window.location

  beforeEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...originalLocation, assign: vi.fn() },
    })
  })

  afterEach(() => {
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: originalLocation,
    })
    localStorage.clear()
  })

  it('clears the stored token and redirects to /login on a 401 response', async () => {
    setToken('an-expired-token')
    server.use(
      http.get('*/protected', () => new HttpResponse(null, { status: 401 })),
    )

    await expect(apiClient.get('/protected')).rejects.toBeTruthy()

    expect(getToken()).toBeNull()
    expect(window.location.assign).toHaveBeenCalledWith('/login')
  })

  it('does not clear the token or redirect on a non-401 error response', async () => {
    setToken('a-still-valid-token')
    server.use(
      http.get('*/broken', () => new HttpResponse(null, { status: 500 })),
    )

    await expect(apiClient.get('/broken')).rejects.toBeTruthy()

    expect(getToken()).toBe('a-still-valid-token')
    expect(window.location.assign).not.toHaveBeenCalled()
  })

  it('does not redirect on a 401 from the login endpoint itself (invalid credentials, not session expiry)', async () => {
    server.use(
      http.post(
        '*/api/v1/auth/login',
        () => new HttpResponse(null, { status: 401 }),
      ),
    )

    await expect(
      apiClient.post('/api/v1/auth/login', {
        email: 'a@b.com',
        password: 'wrong',
      }),
    ).rejects.toBeTruthy()

    expect(window.location.assign).not.toHaveBeenCalled()
  })
})
