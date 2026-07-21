import { QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { server } from '@/test/msw/server'
import { createTestQueryClient } from '@/test/testQueryClient'
import type { RepositoryPolicy } from '../types'
import { PolicyGateBadge } from './PolicyGateBadge'

function renderBadge() {
  const queryClient = createTestQueryClient()
  return render(
    <QueryClientProvider client={queryClient}>
      <PolicyGateBadge repositoryId="r1" />
    </QueryClientProvider>,
  )
}

describe('PolicyGateBadge', () => {
  it('shows a failing badge when the verdict is fail', async () => {
    const policy: RepositoryPolicy = {
      repository_id: 'r1',
      verdict: 'fail',
      blocking_severities: ['critical', 'high'],
      violating_counts: { critical: 2 },
    }
    server.use(
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json(policy),
      ),
    )
    renderBadge()

    const badge = await screen.findByText(/fail/i)
    expect(badge).toBeInTheDocument()
  })

  it('shows a passing badge for a repository with no scans (zero violating counts)', async () => {
    const policy: RepositoryPolicy = {
      repository_id: 'r1',
      verdict: 'pass',
      blocking_severities: ['critical', 'high'],
      violating_counts: {},
    }
    server.use(
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json(policy),
      ),
    )
    renderBadge()

    const badge = await screen.findByText(/pass/i)
    expect(badge).toBeInTheDocument()
  })

  it('shows an inline error message when the policy check fails to load', async () => {
    server.use(
      http.get('*/api/v1/repositories/r1/policy-check', () =>
        HttpResponse.json({ title: 'Not Found' }, { status: 404 }),
      ),
    )
    renderBadge()

    expect(
      await screen.findByText(/could not load policy check/i),
    ).toBeInTheDocument()
  })
})
