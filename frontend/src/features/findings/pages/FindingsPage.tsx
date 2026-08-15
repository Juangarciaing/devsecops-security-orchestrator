import { useState } from 'react'
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

  const handleFiltersChange = (nextFilters: FindingFiltersValue) => {
    setFilters(nextFilters)
    // Real server-side pagination (unlike PR2's repositories/scans
    // client-side workarounds) — any filter change starts a fresh query at
    // offset 0.
    setOffset(0)
  }

  const findings = findingsQuery.data ?? []
  const hasNextPage = findings.length === PAGE_SIZE

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-heading">Findings</h2>

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
