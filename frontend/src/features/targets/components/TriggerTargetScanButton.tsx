import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/shared/ui/button'
import { Label } from '@/shared/ui/label'
import { parseProblemMessage } from '@/shared/lib/problem'
import type { ScannerType } from '@/features/scans/types'
import { useTriggerTargetScan } from '../queries'

// Backward compatible: an unselected picker forwards no `scanner_type` at
// all, matching the pre-existing (no-picker) request shape exactly.
const SCANNER_TYPES: ScannerType[] = [
  'sast',
  'dast',
  'sca',
  'secrets',
  'iac',
  'semgrep',
]

export function TriggerTargetScanButton({ targetId }: { targetId: string }) {
  const navigate = useNavigate()
  const triggerTargetScan = useTriggerTargetScan()
  const [scannerType, setScannerType] = useState<ScannerType | ''>('')
  const selectId = `scanner-type-${targetId}`

  const handleClick = () => {
    triggerTargetScan.mutate(
      { targetId, scanner_type: scannerType || undefined },
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
      <div className="flex items-center gap-2">
        <Label htmlFor={selectId}>Scanner type</Label>
        <select
          id={selectId}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
          value={scannerType}
          onChange={(event) =>
            setScannerType(event.target.value as ScannerType | '')
          }
        >
          <option value="">Default (DAST)</option>
          {SCANNER_TYPES.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
      </div>
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
