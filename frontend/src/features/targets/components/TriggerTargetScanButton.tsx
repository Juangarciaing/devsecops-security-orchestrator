import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/shared/ui/button'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useTriggerTargetScan } from '../queries'

export function TriggerTargetScanButton({ targetId }: { targetId: string }) {
  const navigate = useNavigate()
  const triggerTargetScan = useTriggerTargetScan()

  const handleClick = () => {
    triggerTargetScan.mutate(
      { targetId },
      {
        onSuccess: ({ run, status }) => {
          if (status === 200) {
            toast.info('A scan is already in progress for this target.')
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
        disabled={triggerTargetScan.isPending}
      >
        {triggerTargetScan.isPending ? 'Triggering…' : 'Trigger scan'}
      </Button>
      {triggerTargetScan.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {parseProblemMessage(triggerTargetScan.error)}
        </p>
      ) : null}
    </div>
  )
}
