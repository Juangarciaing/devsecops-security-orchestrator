import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { useCreateUser, useUsers } from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const user = {
  id: 'u1',
  email: 'admin@example.com',
  role: 'admin',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('useUsers', () => {
  it('fetches the user list', async () => {
    server.use(http.get('*/api/v1/users', () => HttpResponse.json([user])))
    const { result } = renderHook(() => useUsers(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([user])
  })
})

describe('useCreateUser', () => {
  it('posts the new user and invalidates the list on success', async () => {
    server.use(
      http.post('*/api/v1/users', () =>
        HttpResponse.json(user, { status: 201 }),
      ),
    )
    const { result } = renderHook(() => useCreateUser(), { wrapper })

    result.current.mutate({
      email: 'admin@example.com',
      password: 'correct-horse',
      role: 'admin',
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(user)
  })

  it('surfaces a 409 conflict error for a duplicate email', async () => {
    server.use(
      http.post(
        '*/api/v1/users',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail: 'A user with this email already exists',
            }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const { result } = renderHook(() => useCreateUser(), { wrapper })

    result.current.mutate({
      email: 'admin@example.com',
      password: 'correct-horse',
      role: 'admin',
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})
