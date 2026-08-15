import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SEVERITY_TOKEN_CLASSNAME, SeverityBadge } from './SeverityBadge'

const SEVERITY_CASES = [
  ['critical', 'Critical'],
  ['high', 'High'],
  ['medium', 'Medium'],
  ['low', 'Low'],
  ['info', 'Info'],
] as const

describe('SeverityBadge', () => {
  it.each(SEVERITY_CASES)('renders the %s label', (severity, label) => {
    render(<SeverityBadge severity={severity} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it.each(SEVERITY_CASES)(
    'pins the data-severity attribute to %s so existing consumers keep working unchanged',
    (severity, label) => {
      render(<SeverityBadge severity={severity} />)
      expect(screen.getByText(label)).toHaveAttribute(
        'data-severity',
        severity,
      )
    },
  )

  it('renders critical severity on the neutral outline base variant now that color comes from the token class map', () => {
    render(<SeverityBadge severity="critical" />)
    expect(screen.getByText('Critical')).toHaveAttribute(
      'data-variant',
      'outline',
    )
  })

  it('renders info severity on the neutral outline base variant now that color comes from the token class map', () => {
    render(<SeverityBadge severity="info" />)
    expect(screen.getByText('Info')).toHaveAttribute('data-variant', 'outline')
  })

  it('maps every severity to a distinct design-system color token class', () => {
    const classNames = Object.values(SEVERITY_TOKEN_CLASSNAME)
    expect(classNames).toHaveLength(5)
    expect(new Set(classNames).size).toBe(5)
  })
})
