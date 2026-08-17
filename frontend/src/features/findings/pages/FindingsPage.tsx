import { useMemo, useState } from 'react'
import { StatTile } from '@/features/repositories/components/StatTile'
import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { Button } from '@/shared/ui/button'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { useFindings } from '../queries'
import type { FindingFilters as FindingFiltersValue } from '../types'
import { FindingFilters } from '../components/FindingFilters'
import { FindingsTable } from '../components/FindingsTable'

const PAGE_SIZE = 20
// Matches FindingsTable's own header (Severity, Rule ID, Title, Status,
// Location, action column) so the skeleton's shape doesn't shift on load.
const TABLE_COLUMN_COUNT = 6

export function FindingsPage() {
  const [filters, setFilters] = useState<FindingFiltersValue>({})
  const [offset, setOffset] = useState(0)

  const findingsQuery = useFindings({
    ...filters,
    limit: PAGE_SIZE,
    offset,
  })
  // Unfiltered, unpaginated — drives the stat strip only, mirroring
  // RepositoriesPage's `useFindings({})` aggregation pattern.
  const allFindingsQuery = useFindings({})

  const handleFiltersChange = (nextFilters: FindingFiltersValue) => {
    setFilters(nextFilters)
    // Real server-side pagination (unlike PR2's repositories/scans
    // client-side workarounds) — any filter change starts a fresh query at
    // offset 0.
    setOffset(0)
  }

  const findings = findingsQuery.data ?? []
  const hasNextPage = findings.length === PAGE_SIZE

  const allFindings = useMemo(
    () => allFindingsQuery.data ?? [],
    [allFindingsQuery.data],
  )
  const criticalOpenCount = allFindings.filter(
    (finding) => finding.severity === 'critical' && finding.status === 'open',
  ).length
  const highOpenCount = allFindings.filter(
    (finding) => finding.severity === 'high' && finding.status === 'open',
  ).length
  const suppressedCount = allFindings.filter(
    (finding) => finding.status === 'suppressed',
  ).length

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 className="text-heading">Findings</h2>
        {allFindingsQuery.isSuccess ? (
          <span className="text-meta text-muted-foreground">
            {allFindings.length}{' '}
            {allFindings.length === 1 ? 'finding' : 'findings'}
          </span>
        ) : null}
      </div>

      {allFindingsQuery.isSuccess && allFindings.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <StatTile label="Total findings" value={allFindings.length} />
          <StatTile
            label="Critical, open"
            value={criticalOpenCount}
            tone={criticalOpenCount > 0 ? 'warning' : 'default'}
          />
          <StatTile
            label="High, open"
            value={highOpenCount}
            tone={highOpenCount > 0 ? 'warning' : 'default'}
          />
          <StatTile label="Suppressed findings" value={suppressedCount} />
        </div>
      ) : null}

      <FindingFilters filters={filters} onChange={handleFiltersChange} />

      {findingsQuery.isPending ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Rule ID</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Location</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableSkeleton columns={TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}

      {findingsQuery.isError ? (
        <ErrorState
          description="Could not load findings."
          onRetry={() => findingsQuery.refetch()}
        />
      ) : null}

      {findingsQuery.isSuccess ? (
        <>
          <FindingsTable findings={findings} />
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={offset === 0}
              onClick={() =>
                setOffset((current) => Math.max(0, current - PAGE_SIZE))
              }
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              disabled={!hasNextPage}
              onClick={() => setOffset((current) => current + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </>
      ) : null}
    </div>
  )
}
