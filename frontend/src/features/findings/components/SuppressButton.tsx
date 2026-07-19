import { Button } from '@/shared/ui/button'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useSuppressFinding, useUnsuppressFinding } from '../queries'
import { isSuppressed } from '../types'
import type { FindingStatus } from '../types'

export function SuppressButton({
  findingId,
  status,
}: {
  findingId: string
  status: FindingStatus
}) {
  const suppress = useSuppressFinding()
  const unsuppress = useUnsuppressFinding()
  const suppressed = isSuppressed(status)
  const mutation = suppressed ? unsuppress : suppress

  const handleClick = () => {
    mutation.mutate(findingId)
  }

  return (
    <div className="flex flex-col gap-1">
      <Button
        type="button"
        size="sm"
        variant="outline"
        onClick={handleClick}
        disabled={mutation.isPending}
      >
        {suppressed ? 'Unsuppress' : 'Suppress'}
      </Button>
      {mutation.isError ? (
        <p role="alert" className="text-xs text-destructive">
          {parseProblemMessage(mutation.error)}
        </p>
      ) : null}
    </div>
  )
}
