import { EmptyState } from '@/shared/components/EmptyState'
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import type { Finding } from '../types'
import { FindingRow } from './FindingRow'

export function FindingsTable({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return (
      <EmptyState
        title="No findings to show"
        description="Findings will appear here once a scan completes."
      />
    )
  }

  return (
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
      <TableBody>
        {findings.map((finding) => (
          <FindingRow key={finding.id} finding={finding} />
        ))}
      </TableBody>
    </Table>
  )
}
