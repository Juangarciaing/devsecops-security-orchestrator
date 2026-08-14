import { describe, expect, it } from 'vitest'
import { filterNavItemsByRole, navItems } from './navItems'

describe('filterNavItemsByRole', () => {
  it('hides admin-only items for a member role', () => {
    const visible = filterNavItemsByRole(navItems, 'member')

    expect(visible.some((item) => item.to.startsWith('/admin'))).toBe(false)
    // Non-admin items must still be present.
    expect(visible.some((item) => item.to === '/')).toBe(true)
    expect(visible.some((item) => item.to === '/settings/api-keys')).toBe(true)
  })

  it('shows admin-only items for an admin role', () => {
    const visible = filterNavItemsByRole(navItems, 'admin')

    expect(visible.some((item) => item.to === '/admin/users')).toBe(true)
    expect(visible.some((item) => item.to === '/admin/webhooks')).toBe(true)
  })

  it('hides every requiredRole item when role is null (e.g. loading state)', () => {
    const visible = filterNavItemsByRole(navItems, null)

    expect(visible.every((item) => item.requiredRole === undefined)).toBe(true)
    // But non-role items are still visible.
    expect(visible.length).toBeGreaterThan(0)
  })
})
