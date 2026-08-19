import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { Button } from '@/shared/ui/button'
import type {
  FindingFilters as FindingFiltersValue,
  FindingSeverity,
  FindingStatus,
} from '../types'
import type { ScannerType } from '@/features/scans/types'

const SEVERITY_FILTERS: { value: FindingSeverity | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
  { value: 'info', label: 'Info' },
]

const STATUS_FILTERS: { value: FindingStatus | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'resolved', label: 'Resolved' },
  { value: 'suppressed', label: 'Suppressed' },
  { value: 'false_positive', label: 'False positive' },
]

const SCANNER_TYPES: ScannerType[] = [
  'sast',
  'dast',
  'sca',
  'secrets',
  'iac',
  'semgrep',
]

const selectClassName =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm'

// Findings toolbar (Req: dense dev-tool table language, mirroring the
// Repositories provider-chip toolbar) — severity/status are the primary
// signals on this screen, so they render as single-select chip groups.
// Scanner type and repository id stay as a secondary select/input row: a
// 6-way chip group and a free-text id don't fit the chip idiom as cleanly.
export function FindingFilters({
  filters,
  onChange,
}: {
  filters: FindingFiltersValue
  onChange: (filters: FindingFiltersValue) => void
}) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-4">
        <div
          role="group"
          aria-label="Filter by severity"
          className="flex items-center gap-1.5"
        >
          {SEVERITY_FILTERS.map((filter) => {
            const active = (filters.severity ?? 'all') === filter.value
            return (
              <Button
                key={filter.value}
                type="button"
                size="sm"
                variant={active ? 'default' : 'outline'}
                aria-pressed={active}
                onClick={() =>
                  onChange({
                    ...filters,
                    severity:
                      filter.value === 'all' ? undefined : filter.value,
                  })
                }
              >
                {filter.label}
              </Button>
            )
          })}
        </div>

        <div
          role="group"
          aria-label="Filter by status"
          className="flex items-center gap-1.5"
        >
          {STATUS_FILTERS.map((filter) => {
            const active = (filters.status ?? 'all') === filter.value
            return (
              <Button
                key={filter.value}
                type="button"
                size="sm"
                variant={active ? 'default' : 'outline'}
                aria-pressed={active}
                onClick={() =>
                  onChange({
                    ...filters,
                    status: filter.value === 'all' ? undefined : filter.value,
                  })
                }
              >
                {filter.label}
              </Button>
            )
          })}
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="filter-scanner">Scanner</Label>
          <select
            id="filter-scanner"
            className={selectClassName}
            value={filters.scanner_type ?? ''}
            onChange={(event) =>
              onChange({
                ...filters,
                scanner_type: (event.target.value || undefined) as
                  ScannerType | undefined,
              })
            }
          >
            <option value="">All</option>
            {SCANNER_TYPES.map((scannerType) => (
              <option key={scannerType} value={scannerType}>
                {scannerType}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-2">
          <Label htmlFor="filter-repository">Repository ID</Label>
          <Input
            id="filter-repository"
            value={filters.repository_id ?? ''}
            onChange={(event) =>
              onChange({
                ...filters,
                repository_id: event.target.value || undefined,
              })
            }
          />
        </div>
      </div>
    </div>
  )
}
