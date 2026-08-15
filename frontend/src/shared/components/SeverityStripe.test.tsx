import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CriticalCue, SeverityStripe } from './SeverityStripe'

describe('SeverityStripe', () => {
  it('applies the stripe class and data-critical when active', () => {
    render(
      <SeverityStripe active>
        <div data-testid="target">content</div>
      </SeverityStripe>,
    )

    const target = screen.getByTestId('target')
    expect(target).toHaveAttribute('data-critical', 'true')
    expect(target.className).toContain('border-l-severity-critical')
  })

  it('omits the stripe class and data-critical when inactive', () => {
    render(
      <SeverityStripe active={false}>
        <div data-testid="target">content</div>
      </SeverityStripe>,
    )

    const target = screen.getByTestId('target')
    expect(target).not.toHaveAttribute('data-critical')
    expect(target.className).not.toContain('border-l-severity-critical')
  })

  it('merges the stripe onto a real TableCell child (first-cell border-left)', () => {
    render(
      <table>
        <tbody>
          <tr>
            <SeverityStripe active>
              <td data-testid="cell" data-slot="table-cell">
                value
              </td>
            </SeverityStripe>
          </tr>
        </tbody>
      </table>,
    )

    const cell = screen.getByTestId('cell')
    expect(cell).toHaveAttribute('data-critical', 'true')
    expect(cell.className).toContain('border-l-severity-critical')
  })
})

describe('CriticalCue', () => {
  it('renders an aria-hidden icon plus an sr-only label when active', () => {
    render(<CriticalCue active />)

    const label = screen.getByText('Open critical finding')
    expect(label).toHaveClass('sr-only')
  })

  it('renders nothing when inactive', () => {
    const { container } = render(<CriticalCue active={false} />)

    expect(container).toBeEmptyDOMElement()
  })
})
