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
import { StatTile } from '@/features/repositories/components/StatTile'
import { CreateUserDialog } from '../components/CreateUserDialog'
import { useUsers } from '../queries'

// Matches this table's own header (Email, Role, Status) so the skeleton's
// shape doesn't shift on load.
const TABLE_COLUMN_COUNT = 3

export function AdminUsersPage() {
  const usersQuery = useUsers()

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-heading">Users</h2>
        <CreateUserDialog />
      </div>

      {usersQuery.isPending ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableSkeleton columns={TABLE_COLUMN_COUNT} />
        </Table>
      ) : null}
      {usersQuery.isError ? (
        <ErrorState
          description="Could not load users."
          onRetry={() => usersQuery.refetch()}
        />
      ) : null}
      {usersQuery.isSuccess && usersQuery.data.length === 0 ? (
        <p className="text-body text-muted-foreground">No users yet.</p>
      ) : null}

      {usersQuery.isSuccess && usersQuery.data.length > 0 ? (
        <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
          <StatTile label="Total users" value={usersQuery.data.length} />
          <StatTile
            label="Admins"
            value={usersQuery.data.filter((user) => user.role === 'admin').length}
          />
          <StatTile
            label="Active users"
            value={usersQuery.data.filter((user) => user.is_active).length}
          />
        </div>
      ) : null}

      {usersQuery.isSuccess && usersQuery.data.length > 0 ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Email</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {usersQuery.data.map((user) => (
              <TableRow key={user.id}>
                <TableCell>{user.email}</TableCell>
                <TableCell>
                  <Badge variant="outline">{user.role}</Badge>
                </TableCell>
                <TableCell>{user.is_active ? 'Active' : 'Inactive'}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </div>
  )
}
