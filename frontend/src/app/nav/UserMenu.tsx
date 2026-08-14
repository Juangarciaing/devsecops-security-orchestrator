import type { CurrentUser } from '@/features/auth/types'
import { Button } from '@/shared/ui/button'

type UserMenuProps = { user: CurrentUser; onLogout: () => void }

export function UserMenu({ user, onLogout }: UserMenuProps) {
  return (
    <div className="flex items-center gap-3 text-sm text-muted-foreground">
      <span>{user.email}</span>
      <Button type="button" variant="outline" size="sm" onClick={onLogout}>
        Log out
      </Button>
    </div>
  )
}
