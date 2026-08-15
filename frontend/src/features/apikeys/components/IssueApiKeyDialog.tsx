import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/shared/ui/dialog'
import { Button } from '@/shared/ui/button'
import { Label } from '@/shared/ui/label'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useIssueApiKey } from '../queries'

// Reveals `raw_key` exactly once. Design D7: the key lives ONLY in this
// component's `useState`, cleared with `mutation.reset()` on close — never
// in the query cache/sessionStorage/URL. Only "Done" may close while shown.
export function IssueApiKeyDialog() {
  const [open, setOpen] = useState(false)
  const [revealedKey, setRevealedKey] = useState<string | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const issueApiKey = useIssueApiKey()

  function resetAll() {
    setRevealedKey(null)
    setAcknowledged(false)
    issueApiKey.reset()
  }

  function handleIssue() {
    issueApiKey.mutate(undefined, {
      onSuccess: (data) => setRevealedKey(data.raw_key),
    })
  }

  function closeAndReset() {
    setOpen(false)
    resetAll()
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) resetAll()
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">Issue new key</Button>
      </DialogTrigger>
      <DialogContent
        showCloseButton={revealedKey === null}
        onInteractOutside={(e) => revealedKey !== null && e.preventDefault()}
        onEscapeKeyDown={(e) => revealedKey !== null && e.preventDefault()}
      >
        <DialogHeader>
          <DialogTitle>Issue new API key</DialogTitle>
        </DialogHeader>

        {revealedKey === null ? (
          <>
            <p className="text-sm text-muted-foreground">
              A new key will be generated. You will only be able to see it
              once.
            </p>
            {issueApiKey.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {parseProblemMessage(issueApiKey.error)}
              </p>
            ) : null}
            <Button type="button" disabled={issueApiKey.isPending} onClick={handleIssue}>
              {issueApiKey.isPending ? 'Issuing…' : 'Issue key'}
            </Button>
          </>
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Copy this key now — it will not be shown again.
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 truncate rounded-md border bg-muted px-3 py-2 text-sm">
                {revealedKey}
              </code>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigator.clipboard.writeText(revealedKey)}
              >
                Copy
              </Button>
            </div>
            <div className="flex items-center gap-2">
              <input
                id="ack-copied-key"
                type="checkbox"
                checked={acknowledged}
                onChange={(e) => setAcknowledged(e.target.checked)}
                className="size-4"
              />
              <Label htmlFor="ack-copied-key" className="font-normal">
                I have copied this key
              </Label>
            </div>
            <DialogFooter>
              <Button type="button" disabled={!acknowledged} onClick={closeAndReset}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
