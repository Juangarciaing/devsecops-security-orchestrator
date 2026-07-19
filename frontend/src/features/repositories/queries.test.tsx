import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import {
  useDeleteRepository,
  useRegisterRepository,
  useRepositories,
  useRepository,
} from './queries'

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = createTestQueryClient()
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
}

const repo = {
  id: 'r1',
  provider: 'github',
  owner: 'acme',
  name: 'widgets',
  clone_url: 'https://github.com/acme/widgets.git',
  default_branch: 'main',
  credential_ref: null,
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

describe('useRepositories', () => {
  it('fetches the repository list', async () => {
    server.use(
      http.get('*/api/v1/repositories', () => HttpResponse.json([repo])),
    )
    const { result } = renderHook(() => useRepositories(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([repo])
  })

  it('surfaces an error when the request fails', async () => {
    server.use(
      http.get(
        '*/api/v1/repositories',
        () => new HttpResponse(null, { status: 500 }),
      ),
    )
    const { result } = renderHook(() => useRepositories(), { wrapper })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useRepository', () => {
  it('fetches a single repository by id', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1', () => HttpResponse.json(repo)),
    )
    const { result } = renderHook(() => useRepository('r1'), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(repo)
  })
})

describe('useRegisterRepository', () => {
  it('posts the new repository and invalidates the list on success', async () => {
    server.use(
      http.post('*/api/v1/repositories', () =>
        HttpResponse.json(repo, { status: 201 }),
      ),
    )
    const { result } = renderHook(() => useRegisterRepository(), { wrapper })

    result.current.mutate({
      provider: 'github',
      owner: 'acme',
      name: 'widgets',
      clone_url: 'https://github.com/acme/widgets.git',
      default_branch: 'main',
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual(repo)
  })

  it('surfaces a 409 conflict error', async () => {
    server.use(
      http.post(
        '*/api/v1/repositories',
        () =>
          new HttpResponse(
            JSON.stringify({
              title: 'Conflict',
              detail:
                'A repository with this provider/owner/name already exists',
            }),
            {
              status: 409,
              headers: { 'Content-Type': 'application/problem+json' },
            },
          ),
      ),
    )
    const { result } = renderHook(() => useRegisterRepository(), { wrapper })

    result.current.mutate({
      provider: 'github',
      owner: 'acme',
      name: 'widgets',
      clone_url: 'https://github.com/acme/widgets.git',
      default_branch: 'main',
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
  })
})

describe('useDeleteRepository', () => {
  it('deletes the repository', async () => {
    server.use(
      http.delete(
        '*/api/v1/repositories/r1',
        () => new HttpResponse(null, { status: 204 }),
      ),
    )
    const { result } = renderHook(() => useDeleteRepository(), { wrapper })

    result.current.mutate('r1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
  })
})
