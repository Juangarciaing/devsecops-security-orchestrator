import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { WebhookDelivery } from '../types'
import { WebhookDeliveriesTable } from './WebhookDeliveriesTable'

function makeDelivery(
  id: string,
  overrides: Partial<WebhookDelivery> = {},
): WebhookDelivery {
  return {
    id,
    signature_valid: true,
    outcome: 'accepted',
    received_at: '2026-01-01T00:00:00Z',
    delivery_id: `gh-${id}`,
    event_type: 'push',
    source_ip: '203.0.113.7',
    repository_full_name: 'acme/widgets',
    ref: 'refs/heads/main',
    commit_sha: 'abc123',
    ...overrides,
  }
}

describe('WebhookDeliveriesTable', () => {
  it('renders one row per delivery with outcome, repository, and source IP', () => {
    render(
      <WebhookDeliveriesTable
        deliveries={[makeDelivery('d1', { outcome: 'accepted' })]}
      />,
    )

    expect(screen.getByText('acme/widgets')).toBeInTheDocument()
    expect(screen.getByText('accepted')).toBeInTheDocument()
    expect(screen.getByText('203.0.113.7')).toBeInTheDocument()
  })

  it('renders a rejected-signature row distinctly and falls back for a null repository', () => {
    render(
      <WebhookDeliveriesTable
        deliveries={[
          makeDelivery('d2', {
            outcome: 'rejected_signature',
            signature_valid: false,
            repository_full_name: null,
            source_ip: null,
          }),
        ]}
      />,
    )

    expect(screen.getByText('rejected_signature')).toBeInTheDocument()
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(2)
  })
})
