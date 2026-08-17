import { useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import { useScans } from '@/features/scans/queries'
import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { StatTile } from '@/features/repositories/components/StatTile'
import { RegisterTargetDialog } from '../components/RegisterTargetDialog'
import {
  TARGET_TABLE_COLUMN_COUNT,
  TargetTable,
} from '../components/TargetTable'
import { latestScanForTarget } from '../lastScan'
import { useScanTargets } from '../queries'
import type { ScanTarget } from '../types'

const PAGE_SIZE = 10

type StatusFilter = 'all' | 'active' | 'inactive'

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'active', label: 'Active' },
  { value: 'inactive', label: 'Inactive' },
]

function matchesSearch(target: ScanTarget, search: string): boolean {
  const query = search.trim().toLowerCase()
  if (!query) return true
  return (
    target.name.toLowerCase().includes(query) ||
    target.target_url.toLowerCase().includes(query)
  )
}

function matchesStatus(target: ScanTarget, status: StatusFilter): boolean {
  if (status === 'all') return true
  return status === 'active' ? target.is_active : !target.is_active
}

export function TargetsPage() {
  const targetsQuery = useScanTargets()
  const scansQuery = useScans()
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [page, setPage] = useState(0)

  const scans = useMemo(() => scansQuery.data ?? [], [scansQuery.data])

  const filtered = useMemo(() => {
    const targets = targetsQuery.data ?? []
    return targets.filter(
      (target) =>
        matchesSearch(target, search) && matchesStatus(target, statusFilter),
    )
  }, [targetsQuery.data, search, statusFilter])

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const clampedPage = Math.min(page, pageCount - 1)
  const paginated = filtered.slice(
    clampedPage * PAGE_SIZE,
    clampedPage * PAGE_SIZE + PAGE_SIZE,
  )

  const targets = targetsQuery.data ?? []
  const activeCount = targets.filter((target) => target.is_active).length
  const runningCount = targets.filter(
    (target) => latestScanForTarget(scans, target.id)?.status === 'running',
  ).length
  const neverScannedCount = targets.filter(
    (target) => !latestScanForTarget(scans, target.id),
  ).length

  function updateSearch(value: string) {
    setSearch(value)
    setPage(0)
  }

  function updateStatusFilter(value: StatusFilter) {
    setStatusFilter(value)
    setPage(0)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-heading">Scan targets</h2>
          {targetsQuery.isSuccess ? (
            <span className="text-meta text-muted-foreground">
              {targets.length} {targets.length === 1 ? 'target' : 'targets'}
            </span>
          ) : null}
        </div>
        <RegisterTargetDialog />
      </div>

      {targetsQuery.isPending ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Target</TableHead>
              <TableHead>URL</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Last scan</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableSkeleton columns={TARGET_TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}

      {targetsQuery.isError ? (
        <ErrorState
          description="Could not load scan targets."
          onRetry={() => targetsQuery.refetch()}
        />
      ) : null}

      {targetsQuery.isSuccess ? (
        <>
          {targets.length > 0 ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatTile label="Total targets" value={targets.length} />
              <StatTile
                label="Active targets"
                value={activeCount}
                tone="active"
              />
              <StatTile
                label="Scans running"
                value={runningCount}
                tone={runningCount > 0 ? 'active' : 'default'}
              />
              <StatTile label="Never scanned" value={neverScannedCount} />
            </div>
          ) : null}

          {targets.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative w-full max-w-xs">
                <Search
                  aria-hidden="true"
                  className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  aria-label="Search targets"
                  placeholder="Search targets..."
                  className="pl-8"
                  value={search}
                  onChange={(event) => updateSearch(event.target.value)}
                />
              </div>
              <div className="flex items-center gap-1.5">
                {STATUS_FILTERS.map((filter) => (
                  <Button
                    key={filter.value}
                    type="button"
                    size="sm"
                    variant={statusFilter === filter.value ? 'default' : 'outline'}
                    aria-pressed={statusFilter === filter.value}
                    onClick={() => updateStatusFilter(filter.value)}
                  >
                    {filter.label}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}

          <TargetTable targets={paginated} scans={scans} />

          {filtered.length > PAGE_SIZE ? (
            <div className="flex items-center justify-between">
              <span className="text-meta text-muted-foreground">
                Showing {paginated.length} of {filtered.length}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={clampedPage === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={clampedPage >= pageCount - 1}
                  onClick={() =>
                    setPage((current) => Math.min(pageCount - 1, current + 1))
                  }
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
