import { useState } from 'react'
import { Menu } from 'lucide-react'
import { NavLink } from 'react-router'
import type { UserRole } from '@/features/auth/types'
import { cn } from '@/shared/lib/utils'
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

// Motion/elevation (PR3, Req4/Req5): duration-fast + ease-standard tokens on
// hover; the global reduced-motion gate in index.css already neutralizes
// this for prefers-reduced-motion: reduce, no per-component override needed.
// `end` avoids react-router's partial-match gotcha where `to="/"` would
// otherwise report active on every nested route.
function NavLinks({ items, onNavigate }: NavLinksProps) {
  return (
    <nav className="flex flex-col gap-1 text-body">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'rounded-md px-3 py-2 transition-colors duration-[var(--duration-fast)] ease-standard hover:bg-sidebar-accent hover:text-sidebar-accent-foreground',
              isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
            )
          }
        >
          {item.label}
        </NavLink>
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
        <span className="px-3 text-label tracking-wide text-muted-foreground uppercase">
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
