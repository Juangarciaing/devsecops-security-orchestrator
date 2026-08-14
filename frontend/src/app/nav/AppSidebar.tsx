import { useState } from 'react'
import { Menu } from 'lucide-react'
import { Link } from 'react-router'
import type { UserRole } from '@/features/auth/types'
import { Button } from '@/shared/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/shared/ui/sheet'
import { filterNavItemsByRole, navItems, type NavItem } from './navItems'

type NavLinksProps = { items: NavItem[]; onNavigate?: () => void }

function NavLinks({ items, onNavigate }: NavLinksProps) {
  return (
    <nav className="flex flex-col gap-1 text-sm">
      {items.map((item) => (
        <Link
          key={item.to}
          to={item.to}
          onClick={onNavigate}
          className="rounded-md px-3 py-2 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground"
        >
          {item.label}
        </Link>
      ))}
    </nav>
  )
}

// Hand-rolled sidebar (design D4). Mobile's nav only mounts inside a closed
// Sheet's content, which Radix unmounts — no duplicate nav copy (task 2.6).
export function AppSidebar({ role }: { role: UserRole | null }) {
  const [mobileOpen, setMobileOpen] = useState(false)
  const visibleItems = filterNavItemsByRole(navItems, role)

  return (
    <>
      <aside className="hidden w-56 shrink-0 flex-col gap-4 border-r bg-sidebar px-4 py-6 text-sidebar-foreground md:flex">
        <span className="px-3 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
          Navigation
        </span>
        <NavLinks items={visibleItems} />
      </aside>

      <div className="border-b px-3 py-2 md:hidden">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Open navigation menu"
            >
              <Menu className="size-5" />
            </Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>Navigation</SheetTitle>
            </SheetHeader>
            <div className="px-4">
              <NavLinks
                items={visibleItems}
                onNavigate={() => setMobileOpen(false)}
              />
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </>
  )
}
