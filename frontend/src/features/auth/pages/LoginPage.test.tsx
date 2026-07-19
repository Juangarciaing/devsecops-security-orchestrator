import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it, afterEach } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import { LoginPage } from './LoginPage'

function renderLoginPage() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div>Dashboard home</div>} />
          </Routes>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  afterEach(() => {
    clearToken()
  })

  it('renders the login form when the user is not authenticated', async () => {
    renderLoginPage()

    expect(
      await screen.findByRole('button', { name: /log in/i }),
    ).toBeInTheDocument()
  })

  it('redirects an already-authenticated user to /', async () => {
    setToken('already-valid-token')
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

    renderLoginPage()

    await waitFor(() =>
      expect(screen.getByText('Dashboard home')).toBeInTheDocument(),
    )
    expect(
      screen.queryByRole('button', { name: /log in/i }),
    ).not.toBeInTheDocument()
  })
})
