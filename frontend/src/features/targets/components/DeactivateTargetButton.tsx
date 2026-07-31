import { toast } from 'sonner'
import { useAuth } from '@/app/auth/useAuth'
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
import { useDeactivateScanTarget } from '../queries'

export function DeactivateTargetButton({ targetId }: { targetId: string }) {
  const auth = useAuth()
  const deactivateScanTarget = useDeactivateScanTarget()

  // Admin-only UI hint, mirroring `DeleteRepositoryButton` (design D4
  // precedent) — the backend's `require_role(ADMIN)` on
  // `DELETE /api/v1/targets/{id}` remains the sole authority.
  if (auth.role !== 'admin') {
    return null
  }

  const handleConfirm = () => {
    deactivateScanTarget.mutate(targetId, {
      onError: (error) => {
        toast.error(parseProblemMessage(error))
      },
    })
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button type="button" variant="destructive" size="sm">
          Deactivate
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Deactivate this scan target?</AlertDialogTitle>
          <AlertDialogDescription>
            This deactivates the target. It stops being available for new
            DAST scans; existing scan history is preserved.
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
