import { Badge } from '@/shared/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/shared/ui/table'
import { CreateUserDialog } from '../components/CreateUserDialog'
import { useUsers } from '../queries'

export function AdminUsersPage() {
  const usersQuery = useUsers()

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Users</h2>
        <CreateUserDialog />
      </div>

      {usersQuery.isPending ? (
        <p className="text-muted-foreground">Loading users…</p>
      ) : null}

      {usersQuery.isError ? (
        <p role="alert" className="text-sm text-destructive">
          Could not load users.
        </p>
      ) : null}

      {usersQuery.isSuccess ? (
        usersQuery.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No users yet.</p>
        ) : (
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
        )
      ) : null}
    </div>
  )
}
