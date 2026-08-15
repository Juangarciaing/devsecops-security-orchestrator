import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/shared/ui/alert-dialog'
import { Button } from '@/shared/ui/button'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useRevokeApiKey } from '../queries'

// Unlike DeleteRepositoryButton/DeactivateTargetButton, revoke is caller-
// scoped (`get_current_user`, not `require_role(ADMIN)`) — see auth.py:79-96
// — so this button has no admin-role gate, matching the backend authority.
export function RevokeApiKeyButton({ keyId }: { keyId: string }) {
  const revokeApiKey = useRevokeApiKey()

  const handleConfirm = () => {
    revokeApiKey.mutate(keyId, {
      onError: (error) => {
        toast.error(parseProblemMessage(error))
      },
    })
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button type="button" variant="destructive" size="sm">
          Revoke
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Revoke this API key?</AlertDialogTitle>
          <AlertDialogDescription>
            Any script or CI job using this key will immediately lose access.
            This cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction onClick={handleConfirm}>Confirm</AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
