import { useMemo, useState } from 'react'
import { AlertTriangle, KeyRound, Search } from 'lucide-react'
import { useFindings } from '@/features/findings/queries'
import { useScans } from '@/features/scans/queries'
import { ErrorState } from '@/shared/components/ErrorState'
import { OnboardingChecklist } from '@/shared/components/OnboardingChecklist'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { Table, TableHead, TableHeader, TableRow } from '@/shared/ui/table'
import { RegisterRepositoryDialog } from '../components/RegisterRepositoryDialog'
import {
  REPOSITORY_TABLE_COLUMN_COUNT,
  RepositoryTable,
} from '../components/RepositoryTable'
import { StatTile } from '../components/StatTile'
import { latestScanForRepository } from '../lastScan'
import { repositoryHasOpenCritical } from '../severity'
import { useRepositories } from '../queries'
import type { CodeRepository, RepositoryProvider } from '../types'

const PAGE_SIZE = 10

const PROVIDER_FILTERS: { value: RepositoryProvider | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'github', label: 'GitHub' },
  { value: 'gitlab', label: 'GitLab' },
  { value: 'bitbucket', label: 'Bitbucket' },
]

function matchesSearch(repository: CodeRepository, search: string): boolean {
  const query = search.trim().toLowerCase()
  if (!query) return true
  return `${repository.owner}/${repository.name}`.toLowerCase().includes(query)
}

export function RepositoriesPage() {
  const repositoriesQuery = useRepositories()
  const scansQuery = useScans()
  const findingsQuery = useFindings({})
  const [search, setSearch] = useState('')
  const [providerFilter, setProviderFilter] = useState<RepositoryProvider | 'all'>(
    'all',
  )
  const [page, setPage] = useState(0)

  // Secondary data — degrade gracefully to an empty list rather than
  // blocking the page if scans/findings fail while repositories succeed
  // (mirrors this page's pre-existing tolerance of scansQuery/findingsQuery
  // errors for the onboarding checklist). Memoized so a stable empty-array
  // fallback doesn't retrigger the sort useMemo below on every render.
  const findings = useMemo(() => findingsQuery.data ?? [], [findingsQuery.data])
  const scans = useMemo(() => scansQuery.data ?? [], [scansQuery.data])

  const filteredAndSorted = useMemo(() => {
    const repositories = repositoriesQuery.data ?? []
    return repositories
      .filter(
        (repository) =>
          matchesSearch(repository, search) &&
          (providerFilter === 'all' || repository.provider === providerFilter),
      )
      .sort((a, b) => {
        const aScan = latestScanForRepository(scans, a.id)
        const bScan = latestScanForRepository(scans, b.id)
        if (!aScan && !bScan) return 0
        if (!aScan) return 1
        if (!bScan) return -1
        return (
          new Date(bScan.created_at).getTime() -
          new Date(aScan.created_at).getTime()
        )
      })
  }, [repositoriesQuery.data, search, providerFilter, scans])

  const pageCount = Math.max(1, Math.ceil(filteredAndSorted.length / PAGE_SIZE))
  const clampedPage = Math.min(page, pageCount - 1)
  const paginated = filteredAndSorted.slice(
    clampedPage * PAGE_SIZE,
    clampedPage * PAGE_SIZE + PAGE_SIZE,
  )

  const repositories = repositoriesQuery.data ?? []
  const criticalRepoCount = repositories.filter((repository) =>
    repositoryHasOpenCritical(findings, repository.id),
  ).length
  const runningCount = repositories.filter(
    (repository) => latestScanForRepository(scans, repository.id)?.status === 'running',
  ).length
  const missingCredentialCount = repositories.filter(
    (repository) => !repository.has_credential,
  ).length

  function updateSearch(value: string) {
    setSearch(value)
    setPage(0)
  }

  function updateProviderFilter(value: RepositoryProvider | 'all') {
    setProviderFilter(value)
    setPage(0)
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h2 className="text-heading">Repositories</h2>
          {repositoriesQuery.isSuccess ? (
            <div className="text-meta text-muted-foreground flex items-center gap-2">
              <span>
                {repositories.length}{' '}
                {repositories.length === 1 ? 'repository' : 'repositories'}
              </span>
              {criticalRepoCount > 0 ? (
                <>
                  <span aria-hidden="true">·</span>
                  <AlertTriangle
                    aria-hidden="true"
                    className="size-3.5 text-severity-medium"
                  />
                  <span>{criticalRepoCount} need attention</span>
                </>
              ) : null}
            </div>
          ) : null}
        </div>
        <RegisterRepositoryDialog />
      </div>

      {repositoriesQuery.isPending ? (
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
          <TableSkeleton columns={REPOSITORY_TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}

      {repositoriesQuery.isError ? (
        <ErrorState
          description="Could not load repositories."
          onRetry={() => repositoriesQuery.refetch()}
        />
      ) : null}

      {repositoriesQuery.isSuccess ? (
        <>
          <OnboardingChecklist
            hasRepository={repositories.length > 0}
            hasCompletedScan={scans.some((scan) => scan.status === 'completed')}
            hasFinding={findings.length > 0}
          />

          {repositories.length > 0 ? (
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatTile label="Total repos" value={repositories.length} />
              <StatTile
                label="Critical, open"
                value={criticalRepoCount}
                icon={
                  <AlertTriangle
                    aria-hidden="true"
                    className="size-3.5 text-severity-critical"
                  />
                }
                tone={criticalRepoCount > 0 ? 'warning' : 'default'}
              />
              <StatTile
                label="Scans running"
                value={runningCount}
                tone={runningCount > 0 ? 'active' : 'default'}
              />
              <StatTile
                label="Missing credential"
                value={missingCredentialCount}
                icon={
                  <KeyRound
                    aria-hidden="true"
                    className="size-3.5 text-muted-foreground"
                  />
                }
              />
            </div>
          ) : null}

          {repositories.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative w-full max-w-xs">
                <Search
                  aria-hidden="true"
                  className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
                />
                <Input
                  aria-label="Search repositories"
                  placeholder="Search repositories..."
                  className="pl-8"
                  value={search}
                  onChange={(event) => updateSearch(event.target.value)}
                />
              </div>
              <div className="flex items-center gap-1.5">
                {PROVIDER_FILTERS.map((filter) => (
                  <Button
                    key={filter.value}
                    type="button"
                    size="sm"
                    variant={providerFilter === filter.value ? 'default' : 'outline'}
                    aria-pressed={providerFilter === filter.value}
                    onClick={() => updateProviderFilter(filter.value)}
                  >
                    {filter.label}
                  </Button>
                ))}
              </div>
            </div>
          ) : null}

          <RepositoryTable
            repositories={paginated}
            findings={findings}
            scans={scans}
          />

          {filteredAndSorted.length > PAGE_SIZE ? (
            <div className="flex items-center justify-between">
              <span className="text-meta text-muted-foreground">
                Showing {paginated.length} of {filteredAndSorted.length}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={clampedPage === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                >
                  Previous
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={clampedPage >= pageCount - 1}
                  onClick={() =>
                    setPage((current) => Math.min(pageCount - 1, current + 1))
                  }
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
