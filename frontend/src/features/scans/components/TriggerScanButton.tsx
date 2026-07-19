import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/shared/ui/button'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useTriggerScan } from '../queries'

export function TriggerScanButton({ repositoryId }: { repositoryId: string }) {
  const navigate = useNavigate()
  const triggerScan = useTriggerScan()

  const handleClick = () => {
    triggerScan.mutate(
      { repositoryId },
      {
        onSuccess: ({ run, status }) => {
          if (status === 200) {
            toast.info('A scan is already in progress for this repository.')
          }
          navigate(`/scans/${run.id}`)
        },
      },
    )
  }

  return (
    <div className="flex flex-col gap-2">
      <Button
        type="button"
        onClick={handleClick}
        disabled={triggerScan.isPending}
      >
        {triggerScan.isPending ? 'Triggering…' : 'Trigger scan'}
      </Button>
      {triggerScan.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {parseProblemMessage(triggerScan.error)}
        </p>
      ) : null}
    </div>
  )
}
