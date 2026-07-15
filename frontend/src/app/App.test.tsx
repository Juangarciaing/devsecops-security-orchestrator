import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('renders the orchestrator placeholder heading without throwing', () => {
    render(<App />)

    expect(
      screen.getByRole('heading', {
        name: /devsecops security orchestrator/i,
      }),
    ).toBeInTheDocument()
  })
})
