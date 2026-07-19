import { QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, getToken, setToken } from '@/shared/api/token'
import { AuthProvider } from './AuthProvider'
import { useAuth } from './useAuth'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  )
}

const currentUserResponse = {
  id: 'u1',
  email: 'a@b.com',
  role: 'admin' as const,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('AuthProvider / useAuth', () => {
  afterEach(() => {
    clearToken()
  })

  it('is anon immediately when no token is stored, without calling /auth/me', async () => {
    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('anon'))
    expect(result.current.user).toBeNull()
    expect(result.current.role).toBeNull()
  })

  it('hydrates to authed with the user role when a token is already stored', async () => {
    setToken('existing-token')
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json(currentUserResponse),
      ),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('authed'))
    expect(result.current.role).toBe('admin')
    expect(result.current.user?.email).toBe('a@b.com')
  })

  it('becomes anon when the boot /auth/me call fails', async () => {
    setToken('a-token-the-backend-rejects')
    server.use(
      http.get(
        '*/api/v1/auth/me',
        () => new HttpResponse(null, { status: 401 }),
      ),
    )

    const { result } = renderHook(() => useAuth(), { wrapper })

    await waitFor(() => expect(result.current.status).toBe('anon'))
  })

  it('login() stores the token and transitions to authed', async () => {
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json(currentUserResponse),
      ),
    )
    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('anon'))

    act(() => {
      result.current.login('brand-new-token')
    })

    expect(getToken()).toBe('brand-new-token')
    await waitFor(() => expect(result.current.status).toBe('authed'))
  })

  it('logout() clears the token and transitions back to anon', async () => {
    setToken('existing-token')
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json(currentUserResponse),
      ),
    )
    const { result } = renderHook(() => useAuth(), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('authed'))

    act(() => {
      result.current.logout()
    })

    expect(getToken()).toBeNull()
    await waitFor(() => expect(result.current.status).toBe('anon'))
    expect(result.current.user).toBeNull()
  })
})
