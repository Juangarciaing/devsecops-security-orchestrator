import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import type {
  FindingFilters as FindingFiltersValue,
  FindingSeverity,
  FindingStatus,
} from '../types'
import type { ScannerType } from '@/features/scans/types'

const SEVERITIES: FindingSeverity[] = [
  'critical',
  'high',
  'medium',
  'low',
  'info',
]
const STATUSES: FindingStatus[] = [
  'open',
  'resolved',
  'suppressed',
  'false_positive',
]
const SCANNER_TYPES: ScannerType[] = ['sast', 'dast', 'sca', 'secrets', 'iac']

const selectClassName =
  'h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm'

export function FindingFilters({
  filters,
  onChange,
}: {
  filters: FindingFiltersValue
  onChange: (filters: FindingFiltersValue) => void
}) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <div className="flex flex-col gap-2">
        <Label htmlFor="filter-severity">Severity</Label>
        <select
          id="filter-severity"
          className={selectClassName}
          value={filters.severity ?? ''}
          onChange={(event) =>
            onChange({
              ...filters,
              severity: (event.target.value || undefined) as
                FindingSeverity | undefined,
            })
          }
        >
          <option value="">All</option>
          {SEVERITIES.map((severity) => (
            <option key={severity} value={severity}>
              {severity}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-2">
        <Label htmlFor="filter-status">Status</Label>
        <select
          id="filter-status"
          className={selectClassName}
          value={filters.status ?? ''}
          onChange={(event) =>
            onChange({
              ...filters,
              status: (event.target.value || undefined) as
                FindingStatus | undefined,
            })
          }
        >
          <option value="">All</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {status}
            </option>
          ))}
        </select>
      </div>

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
  )
}
