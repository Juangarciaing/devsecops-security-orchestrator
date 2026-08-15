import { ErrorState } from '@/shared/components/ErrorState'
import { TableSkeleton } from '@/shared/components/TableSkeleton'
import { Badge } from '@/shared/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import { IssueApiKeyDialog } from '../components/IssueApiKeyDialog'
import { RevokeApiKeyButton } from '../components/RevokeApiKeyButton'
import { useApiKeys } from '../queries'

// Matches this table's own header (Key, Status, Created, Last used, action
// column) so the skeleton's shape doesn't shift on load.
const TABLE_COLUMN_COUNT = 5

export function ApiKeysPage() {
  const apiKeysQuery = useApiKeys()

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-heading">API keys</h2>
        <IssueApiKeyDialog />
      </div>

      {apiKeysQuery.isPending ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableSkeleton columns={TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}

      {apiKeysQuery.isError ? (
        <ErrorState
          description="Could not load your API keys."
          onRetry={() => apiKeysQuery.refetch()}
        />
      ) : null}

      {apiKeysQuery.isSuccess && apiKeysQuery.data.length === 0 ? (
        <p className="text-body text-muted-foreground">
          No API keys yet. Issue one to authenticate scripts and CI jobs.
        </p>
      ) : null}

      {apiKeysQuery.isSuccess && apiKeysQuery.data.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Key</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Created</TableHead>
              <TableHead>Last used</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {apiKeysQuery.data.map((key) => (
              <TableRow key={key.id}>
                <TableCell className="font-mono text-code">
                  {key.key_prefix}…
                </TableCell>
                <TableCell>
                  <Badge variant={key.is_active ? 'outline' : 'secondary'}>
                    {key.is_active ? 'Active' : 'Revoked'}
                  </Badge>
                </TableCell>
                <TableCell>{new Date(key.created_at).toLocaleDateString()}</TableCell>
                <TableCell>
                  {key.last_used_at
                    ? new Date(key.last_used_at).toLocaleDateString()
                    : 'Never'}
                </TableCell>
                <TableCell>
                  {key.is_active ? <RevokeApiKeyButton keyId={key.id} /> : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </div>
  )
}
