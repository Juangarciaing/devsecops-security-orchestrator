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
import { useDeleteRepository } from '../queries'

export function DeleteRepositoryButton({
  repositoryId,
}: {
  repositoryId: string
}) {
  const auth = useAuth()
  const deleteRepository = useDeleteRepository()

  // Admin-only UI hint (design D4) — the backend's `require_role(ADMIN)`
  // remains the sole authority; hiding the button just avoids a
  // guaranteed-403 for members.
  if (auth.role !== 'admin') {
    return null
  }

  const handleConfirm = () => {
    deleteRepository.mutate(repositoryId, {
      onError: (error) => {
        toast.error(parseProblemMessage(error))
      },
    })
  }

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>
        <Button type="button" variant="destructive" size="sm">
          Delete repository
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this repository?</AlertDialogTitle>
          <AlertDialogDescription>
            This deactivates the repository. It stops being available for new
            scans; existing scan history is preserved.
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
