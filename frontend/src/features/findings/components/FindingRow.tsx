import { TableCell, TableRow } from '@/shared/ui/table'
import type { Finding } from '../types'
import { FindingStatusBadge } from './FindingStatusBadge'
import { SeverityBadge } from './SeverityBadge'
import { SuppressButton } from './SuppressButton'

export function FindingRow({ finding }: { finding: Finding }) {
  return (
    <TableRow>
      <TableCell>
        <SeverityBadge severity={finding.severity} />
      </TableCell>
      <TableCell>{finding.title}</TableCell>
      <TableCell>
        <FindingStatusBadge status={finding.status} />
      </TableCell>
      <TableCell>
        {/* Redaction-safe (Req: Redaction-Safe Rendering): file_path/snippet
            are nulled server-side for the `member` role — never assume
            presence, render blank rather than throwing. */}
        {finding.file_path
          ? `${finding.file_path}${
              finding.line_number != null ? `:${finding.line_number}` : ''
            }`
          : '—'}
      </TableCell>
      <TableCell>
        <SuppressButton findingId={finding.id} status={finding.status} />
      </TableCell>
    </TableRow>
  )
}
