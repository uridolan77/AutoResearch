import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders deciding status with normalized class name', () => {
    render(<StatusBadge value="deciding" />)

    const badge = screen.getByText('deciding')
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveClass('status-pill')
    expect(badge).toHaveClass('status-deciding')
  })
})
