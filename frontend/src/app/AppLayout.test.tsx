import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import { AppLayout } from './AppLayout'

function renderAppLayout() {
  const queryClient = createTestQueryClient()
  return render(
    <MemoryRouter initialEntries={['/']}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <Routes>
            <Route element={<AppLayout />}>
              <Route path="/" element={<div>Nested page content</div>} />
            </Route>
          </Routes>
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('AppLayout', () => {
  afterEach(() => {
    clearToken()
  })

  it('renders the app title and the nested route content via Outlet', () => {
    renderAppLayout()

    expect(
      screen.getByRole('heading', { name: /devsecops security orchestrator/i }),
    ).toBeInTheDocument()
    expect(screen.getByText('Nested page content')).toBeInTheDocument()
  })

  it('shows the current user email and a log out action once authenticated', async () => {
    setToken('a-valid-token')
    server.use(
      http.get('*/api/v1/auth/me', () =>
        HttpResponse.json({
          id: 'u1',
          email: 'signed-in@example.com',
          role: 'member',
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    )

    renderAppLayout()

    await waitFor(() =>
      expect(screen.getByText('signed-in@example.com')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument()
  })

  it('renders navigation links to Repositories and Findings', () => {
    renderAppLayout()

    expect(screen.getByRole('link', { name: /repositories/i })).toHaveAttribute(
      'href',
      '/',
    )
    expect(screen.getByRole('link', { name: /findings/i })).toHaveAttribute(
      'href',
      '/findings',
    )
  })
})
