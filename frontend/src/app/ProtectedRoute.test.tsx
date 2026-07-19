import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import { ProtectedRoute } from './ProtectedRoute'

function renderProtected() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={['/']}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<div>Login page</div>} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  <div>Secret dashboard</div>
                </ProtectedRoute>
              }
            />
          </Routes>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('ProtectedRoute', () => {
  afterEach(() => {
    clearToken()
  })

  it('redirects an unauthenticated user to /login', async () => {
    renderProtected()

    await waitFor(() =>
      expect(screen.getByText('Login page')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Secret dashboard')).not.toBeInTheDocument()
  })

  it('renders the protected content for an authenticated user', async () => {
    setToken('a-valid-token')
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

    renderProtected()

    await waitFor(() =>
      expect(screen.getByText('Secret dashboard')).toBeInTheDocument(),
    )
    expect(screen.queryByText('Login page')).not.toBeInTheDocument()
  })
})
