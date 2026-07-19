import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { getToken } from '@/shared/api/token'
import { useLogin, useMe } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

describe('useLogin', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('stores the returned access token on successful login', async () => {
    server.use(
      http.post('*/api/v1/auth/login', () =>
        HttpResponse.json({
          access_token: 'fresh-token',
          token_type: 'bearer',
        }),
      ),
    )
    const { result } = renderHook(() => useLogin(), { wrapper })

    result.current.mutate({ email: 'a@b.com', password: 'secret' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(getToken()).toBe('fresh-token')
  })

  it('surfaces an error and does not store a token on invalid credentials', async () => {
    server.use(
      http.post(
        '*/api/v1/auth/login',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Unauthorized',
              detail: 'Incorrect email or password.',
            }),
            {
              status: 401,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const { result } = renderHook(() => useLogin(), { wrapper })

    result.current.mutate({ email: 'a@b.com', password: 'wrong' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(getToken()).toBeNull()
  })
})

describe('useMe', () => {
  it('fetches the current user including role when enabled', async () => {
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u1',
          email: 'a@b.com',
          role: 'admin',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    )
    const { result } = renderHook(() => useMe(true), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.role).toBe('admin')
  })

  it('does not fetch when disabled', async () => {
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u1',
          email: 'a@b.com',
          role: 'member',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    )
    const { result } = renderHook(() => useMe(false), { wrapper })

    expect(result.current.fetchStatus).toBe('idle')
    expect(result.current.data).toBeUndefined()
  })
})
