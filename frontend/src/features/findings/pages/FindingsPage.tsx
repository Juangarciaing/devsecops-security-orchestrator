import { useState } from 'react'
import { Button } from '@/shared/ui/button'
import { useFindings } from '../queries'
import type { FindingFilters as FindingFiltersValue } from '../types'
import { FindingFilters } from '../components/FindingFilters'
import { FindingsTable } from '../components/FindingsTable'

const PAGE_SIZE = 20

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
      <h2 className="text-xl font-semibold">Findings</h2>

      <FindingFilters filters={filters} onChange={handleFiltersChange} />

      {findingsQuery.isPending ? (
        <p className="text-muted-foreground">Loading findings…</p>
      ) : null}

      {findingsQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load findings.
        </p>
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
