import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OnboardingChecklist } from './OnboardingChecklist'

describe('OnboardingChecklist', () => {
  it('prompts to register a repository when none exist yet', () => {
    render(
      <OnboardingChecklist
        hasRepository={false}
        hasCompletedScan={false}
        hasFinding={false}
      />,
    )

    expect(
      screen.getByText(/register your first repository/i),
    ).toBeInTheDocument()
  })

  it('prompts to run a scan once a repository exists but none has completed', () => {
    render(
      <OnboardingChecklist
        hasRepository={true}
        hasCompletedScan={false}
        hasFinding={false}
      />,
    )

    expect(screen.getByText(/run your first scan/i)).toBeInTheDocument()
    expect(
      screen.queryByText(/register your first repository/i),
    ).not.toBeInTheDocument()
  })

  it('shows a distinct message once a scan has completed with zero findings', () => {
    render(
      <OnboardingChecklist
        hasRepository={true}
        hasCompletedScan={true}
        hasFinding={false}
      />,
    )

    expect(screen.getByText(/no findings yet/i)).toBeInTheDocument()
    expect(
      screen.queryByText(/run your first scan/i),
    ).not.toBeInTheDocument()
  })

  it('renders nothing once a repository, a completed scan, and a finding all exist', () => {
    const { container } = render(
      <OnboardingChecklist
        hasRepository={true}
        hasCompletedScan={true}
        hasFinding={true}
      />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})
