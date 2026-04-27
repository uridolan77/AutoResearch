import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it } from 'vitest'
import { AppShell } from './AppShell'

describe('AppShell', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it('renders navigation and projected content', () => {
    render(
      <MemoryRouter>
        <AppShell>
          <div>Test Child Content</div>
        </AppShell>
      </MemoryRouter>,
    )

    expect(screen.getByText('Operator Console')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sessions' })).toBeInTheDocument()
    expect(screen.getByText('Test Child Content')).toBeInTheDocument()
  })
})
