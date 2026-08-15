import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken, setToken } from '@/shared/api/token'
import { routes } from './router'

function mockCurrentUser(role: 'admin' | 'member') {
  server.use(
    http.get('*/api/v1/auth/me', () =>
      HttpResponse.json({
        id: 'u1',
        email: `${role}@example.com`,
        role,
        is_active: true,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
  )
}

function renderAtPath(initialPath: string) {
  const queryClient = createTestQueryClient()
  const memoryRouter = createMemoryRouter(routes, {
    initialEntries: [initialPath],
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <RouterProvider router={memoryRouter} />
      </AuthProvider>
    </QueryClientProvider>,
  )
}

describe('router', () => {
  afterEach(() => {
    clearToken()
  })

  it('redirects an unauthenticated visit to / down to /login', async () => {
    renderAtPath('/')

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /log in/i }),
      ).toBeInTheDocument(),
    )
  })

  it('redirects an unauthenticated visit to a nested protected path down to /login', async () => {
    renderAtPath('/findings')

    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /log in/i }),
      ).toBeInTheDocument(),
    )
  })

  it('renders the login page directly at /login', async () => {
    renderAtPath('/login')

    expect(
      await screen.findByRole('button', { name: /log in/i }),
    ).toBeInTheDocument()
  })

  it.each(['/admin/users', '/admin/webhooks'])(
    'shows an access-denied panel (not a redirect) for a member visiting %s',
    async (path) => {
      setToken('a-valid-token')
      mockCurrentUser('member')

      renderAtPath(path)

      expect(await screen.findByRole('alert')).toHaveTextContent(
        /access denied/i,
      )
    },
  )

  it.each([
    ['/admin/users', /manage users/i],
    ['/admin/webhooks', /webhook deliveries audit/i],
  ] as const)('lets an admin reach %s', async (path, expectedText) => {
    setToken('a-valid-token')
    mockCurrentUser('admin')
    server.use(
      http.get('*/api/v1/webhooks/deliveries', () => HttpResponse.json([])),
    )

    renderAtPath(path)

    expect(await screen.findByText(expectedText)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('lets any authed role (member) reach /settings/api-keys', async () => {
    setToken('a-valid-token')
    mockCurrentUser('member')

    renderAtPath('/settings/api-keys')

    expect(await screen.findByText(/manage your api keys/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
