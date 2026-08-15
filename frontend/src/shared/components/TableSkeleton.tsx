import { Skeleton } from '@/shared/ui/skeleton'
import { TableBody, TableCell, TableRow } from '@/shared/ui/table'

interface TableSkeletonProps {
  rows?: number
  columns: number
}

// Layout-matched loading placeholder for data tables (Req10). Renders
// `rows` x `columns` shimmering cells inside real <TableRow>/<TableCell>
// markup — composed from shared/ui's Skeleton primitive, never a
// reimplementation — so swapping it out for the loaded <TableBody> doesn't
// shift the table's shape.
export function TableSkeleton({ rows = 5, columns }: TableSkeletonProps) {
  return (
    <TableBody>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <TableRow key={rowIndex}>
          {Array.from({ length: columns }).map((_, columnIndex) => (
            <TableCell key={columnIndex}>
              <Skeleton className="h-4 w-full" />
            </TableCell>
          ))}
        </TableRow>
      ))}
    </TableBody>
  )
}
