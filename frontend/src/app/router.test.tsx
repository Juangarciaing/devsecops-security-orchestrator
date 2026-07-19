import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { afterEach, describe, expect, it } from 'vitest'
import { AuthProvider } from '@/app/auth/AuthProvider'
import { createTestQueryClient } from '@/test/testQueryClient'
import { clearToken } from '@/shared/api/token'
import { routes } from './router'

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
})
