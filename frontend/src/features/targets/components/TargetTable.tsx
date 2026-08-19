import { Badge } from '@/shared/ui/badge'
import { EmptyState } from '@/shared/components/EmptyState'
import { ScanStatusBadge } from '@/features/scans/components/ScanStatusBadge'
import type { ScanRun } from '@/features/scans/types'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import { DeactivateTargetButton } from './DeactivateTargetButton'
import { TriggerTargetScanButton } from './TriggerTargetScanButton'
import { latestScanForTarget } from '../lastScan'
import type { ScanTarget } from '../types'

// Column count for TableSkeleton's layout-matched loading placeholder
// (Target, URL, Status, Last scan, Actions).
export const TARGET_TABLE_COLUMN_COUNT = 5

// Scan targets list table (Req: dense dev-tool table language, mirroring
// RepositoryTable) — replaces the former card list. Unlike repositories,
// targets have no per-row detail page, so trigger-scan/deactivate stay
// inline in an Actions cell rather than moving behind a chevron.
export function TargetTable({
  targets,
  scans,
}: {
  targets: ScanTarget[]
  scans: ScanRun[]
}) {
  if (targets.length === 0) {
    return (
      <EmptyState
        title="No scan targets registered yet"
        description="Register one to get started."
      />
    )
  }

  return (
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
      <TableBody>
        {targets.map((target) => {
          const lastScan = latestScanForTarget(scans, target.id)

          return (
            <TableRow key={target.id}>
              <TableCell className="font-medium">{target.name}</TableCell>
              <TableCell className="text-meta text-muted-foreground">
                {target.target_url}
              </TableCell>
              <TableCell>
                <Badge variant="outline">
                  {target.is_active ? 'active' : 'inactive'}
                </Badge>
              </TableCell>
              <TableCell>
                {lastScan ? (
                  <div className="flex flex-col gap-1">
                    <ScanStatusBadge status={lastScan.status} />
                    <span className="text-meta text-muted-foreground tabular-nums">
                      {new Date(lastScan.created_at).toLocaleString()}
                    </span>
                  </div>
                ) : (
                  <span className="text-meta text-muted-foreground">
                    Not scanned yet
                  </span>
                )}
              </TableCell>
              <TableCell>
                <div className="flex items-center gap-2">
                  <TriggerTargetScanButton targetId={target.id} />
                  <DeactivateTargetButton targetId={target.id} />
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
