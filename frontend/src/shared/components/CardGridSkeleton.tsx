import { Card, CardHeader } from '@/shared/ui/card'
import { Skeleton } from '@/shared/ui/skeleton'

interface CardGridSkeletonProps {
  count?: number
}

// Layout-matched loading placeholder for card-grid list pages (Req10).
// Renders `count` shimmering <Card> placeholders — composed from
// shared/ui's Skeleton primitive, never a reimplementation — in the same
// grid the loaded content uses, so nothing shifts on swap.
export function CardGridSkeleton({ count = 3 }: CardGridSkeletonProps) {
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }).map((_, index) => (
        <Card key={index}>
          <CardHeader>
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
          </CardHeader>
        </Card>
      ))}
    </div>
  )
}
