import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router'
import { ScanStatusBadge } from '@/features/scans/components/ScanStatusBadge'
import type { Finding } from '@/features/findings/types'
import type { ScanRun } from '@/features/scans/types'
import { EmptyState } from '@/shared/components/EmptyState'
import { CriticalCue, SeverityStripe } from '@/shared/components/SeverityStripe'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import { CredentialBadge } from './CredentialBadge'
import { SeverityCountDots } from './SeverityCountDots'
import { latestScanForRepository } from '../lastScan'
import { openSeverityCounts, repositoryHasOpenCritical } from '../severity'
import type { CodeRepository } from '../types'

const PROVIDER_LABEL: Record<CodeRepository['provider'], string> = {
  github: 'GitHub',
  gitlab: 'GitLab',
  bitbucket: 'Bitbucket',
}

// Column count for TableSkeleton's layout-matched loading placeholder
// (Repository, Provider, Open findings, Last scan, Credential, chevron).
export const REPOSITORY_TABLE_COLUMN_COUNT = 6

// Repositories list table (Req: repositories list mockup) — replaces the
// former card grid. `findings`/`scans` are the page's already-fetched,
// unscoped lists; every per-row derivation (stripe, severity dots, last
// scan) is a pure filter over them, no per-row queries.
export function RepositoryTable({
  repositories,
  findings,
  scans,
}: {
  repositories: CodeRepository[]
  findings: Finding[]
  scans: ScanRun[]
}) {
  if (repositories.length === 0) {
    return (
      <EmptyState
        title="No repositories registered yet"
        description="Register one to get started."
      />
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Repository</TableHead>
          <TableHead>Provider</TableHead>
          <TableHead>Open findings</TableHead>
          <TableHead>Last scan</TableHead>
          <TableHead>Credential</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {repositories.map((repository) => {
          const critical = repositoryHasOpenCritical(findings, repository.id)
          const counts = openSeverityCounts(findings, repository.id)
          const lastScan = latestScanForRepository(scans, repository.id)

          return (
            <TableRow key={repository.id}>
              <SeverityStripe active={critical}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    <div className="flex flex-col">
                      <Link
                        to={`/repositories/${repository.id}`}
                        className="font-medium hover:underline"
                      >
                        {repository.owner}/{repository.name}
                      </Link>
                      <span className="text-meta text-muted-foreground">
                        {repository.default_branch}
                      </span>
                    </div>
                    <CriticalCue active={critical} />
                  </div>
                </TableCell>
              </SeverityStripe>
              <TableCell>{PROVIDER_LABEL[repository.provider]}</TableCell>
              <TableCell>
                <SeverityCountDots counts={counts} />
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
                <CredentialBadge
                  hasCredential={repository.has_credential}
                  credentialKind={repository.credential_kind}
                />
              </TableCell>
              <TableCell>
                <Link
                  to={`/repositories/${repository.id}`}
                  aria-label={`View ${repository.owner}/${repository.name}`}
                >
                  <ChevronRight className="size-4 text-muted-foreground" />
                </Link>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}
