import type { UserRole } from '@/features/auth/types'

export interface NavItem {
  label: string
  to: string
  requiredRole?: UserRole
}

// Nav as data (design D5), filtered by role. Admin-only entries mirror the
// backend's require_role(ADMIN) boundary (design D3); /settings/api-keys is
// any authed user, matching the backend's get_current_user-only guard.
export const navItems: NavItem[] = [
  { label: 'Repositories', to: '/' },
  { label: 'Scan targets', to: '/targets' },
  { label: 'Findings', to: '/findings' },
  { label: 'Admin: Users', to: '/admin/users', requiredRole: 'admin' },
  {
    label: 'Admin: Webhook deliveries',
    to: '/admin/webhooks',
    requiredRole: 'admin',
  },
  { label: 'API keys', to: '/settings/api-keys' },
]

export function filterNavItemsByRole(
  items: NavItem[],
  role: UserRole | null,
): NavItem[] {
  return items.filter(
    (item) => !item.requiredRole || item.requiredRole === role,
  )
}
