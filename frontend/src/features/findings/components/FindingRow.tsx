import { useState } from 'react'
import { Button } from '@/shared/ui/button'
import { TableCell, TableRow } from '@/shared/ui/table'
import type { Finding } from '../types'
import { FindingStatusBadge } from './FindingStatusBadge'
import { SeverityBadge } from './SeverityBadge'
import { SuppressButton } from './SuppressButton'

const DETAIL_COLUMN_COUNT = 6

export function FindingRow({ finding }: { finding: Finding }) {
  const [expanded, setExpanded] = useState(false)

  // Redaction-safe (Req: Redaction-Safe Rendering): raw_evidence/snippet/
  // file_path/line_number are nulled server-side for the `member` role —
  // never assume presence, render blank/omit rather than throwing.
  const hasDetails = finding.snippet != null || finding.raw_evidence != null

  return (
    <>
      <TableRow>
        <TableCell>
          <SeverityBadge severity={finding.severity} />
        </TableCell>
        <TableCell>{finding.rule_id}</TableCell>
        <TableCell>{finding.title}</TableCell>
        <TableCell>
          <FindingStatusBadge status={finding.status} />
        </TableCell>
        <TableCell>
          {finding.file_path
            ? `${finding.file_path}${
                finding.line_number != null ? `:${finding.line_number}` : ''
              }`
            : '—'}
        </TableCell>
        <TableCell>
          <div className="flex flex-col gap-1">
            <SuppressButton findingId={finding.id} status={finding.status} />
            {hasDetails ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                aria-expanded={expanded}
                onClick={() => setExpanded((prev) => !prev)}
              >
                {expanded ? 'Hide details' : 'Details'}
              </Button>
            ) : null}
          </div>
        </TableCell>
      </TableRow>
      {expanded && hasDetails ? (
        <TableRow>
          <TableCell
            colSpan={DETAIL_COLUMN_COUNT}
            className="whitespace-normal"
          >
            <div className="flex flex-col gap-2">
              {finding.snippet != null ? (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">
                    Snippet
                  </p>
                  <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
                    <code>{finding.snippet}</code>
                  </pre>
                </div>
              ) : null}
              {finding.raw_evidence != null ? (
                <div>
                  <p className="text-xs font-medium text-muted-foreground">
                    Raw evidence
                  </p>
                  <pre className="overflow-x-auto rounded-md bg-muted p-2 text-xs">
                    {JSON.stringify(finding.raw_evidence, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          </TableCell>
        </TableRow>
      ) : null}
    </>
  )
}
