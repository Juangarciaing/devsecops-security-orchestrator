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

export function ApiKeysPage() {
  const apiKeysQuery = useApiKeys()

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">API keys</h2>
        <IssueApiKeyDialog />
      </div>

      {apiKeysQuery.isPending ? (
        <p className="text-muted-foreground">Loading API keys…</p>
      ) : null}
      {apiKeysQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load your API keys.
        </p>
      ) : null}
      {apiKeysQuery.isSuccess && apiKeysQuery.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">
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
                <TableCell className="font-mono">{key.key_prefix}…</TableCell>
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
