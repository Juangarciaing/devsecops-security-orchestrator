import { useState } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Button } from '@/shared/ui/button'
import { Label } from '@/shared/ui/label'
import { parseProblemMessage } from '@/shared/lib/problem'
import type { ScannerType } from '../types'
import { useTriggerScan } from '../queries'

// Backward compatible: an unselected picker forwards no `scanner_type` at
// all, so `TriggerScanInput`'s server-side default (secrets) still applies.
const SCANNER_TYPES: ScannerType[] = [
  'sast',
  'dast',
  'sca',
  'secrets',
  'iac',
  'semgrep',
]

export function TriggerScanButton({ repositoryId }: { repositoryId: string }) {
  const navigate = useNavigate()
  const triggerScan = useTriggerScan()
  const [scannerType, setScannerType] = useState<ScannerType | ''>('')
  const selectId = `scanner-type-${repositoryId}`

  const handleClick = () => {
    triggerScan.mutate(
      { repositoryId, scanner_type: scannerType || undefined },
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
          <option value="">Default (secrets)</option>
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
