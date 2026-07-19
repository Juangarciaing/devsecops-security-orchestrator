import { Link } from 'react-router'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import type { ScanRun } from '../types'
import { ScanStatusBadge } from './ScanStatusBadge'

export function ScanHistoryTable({ scans }: { scans: ScanRun[] }) {
  if (scans.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No scans have been run for this repository yet.
      </p>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Status</TableHead>
          <TableHead>Ref</TableHead>
          <TableHead>Triggered</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {scans.map((scan) => (
          <TableRow key={scan.id}>
            <TableCell>
              <ScanStatusBadge status={scan.status} />
            </TableCell>
            <TableCell>{scan.ref}</TableCell>
            <TableCell>{new Date(scan.created_at).toLocaleString()}</TableCell>
            <TableCell>
              <Link
                to={`/scans/${scan.id}`}
                className="text-sm font-medium text-primary underline-offset-4 hover:underline"
              >
                View
              </Link>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
