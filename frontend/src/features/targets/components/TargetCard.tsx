import { Badge } from '@/shared/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import type { ScanTarget } from '../types'
import { DeactivateTargetButton } from './DeactivateTargetButton'
import { TriggerTargetScanButton } from './TriggerTargetScanButton'

export function TargetCard({ target }: { target: ScanTarget }) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{target.name}</CardTitle>
        <Badge variant="outline">{target.is_active ? 'active' : 'inactive'}</Badge>
      </CardHeader>
      <CardContent className="flex items-center justify-between gap-4">
        <span className="text-sm text-muted-foreground">
          {target.target_url}
        </span>
        <div className="flex items-center gap-2">
          <TriggerTargetScanButton targetId={target.id} />
          <DeactivateTargetButton targetId={target.id} />
        </div>
      </CardContent>
    </Card>
  )
}
