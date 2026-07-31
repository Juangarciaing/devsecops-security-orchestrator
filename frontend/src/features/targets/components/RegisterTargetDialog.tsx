import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/shared/ui/dialog'
import { Button } from '@/shared/ui/button'
import { Input } from '@/shared/ui/input'
import { Label } from '@/shared/ui/label'
import { parseProblemMessage } from '@/shared/lib/problem'
import { useRegisterScanTarget } from '../queries'

const registerScanTargetSchema = z.object({
  name: z.string().min(1, 'Name is required'),
  target_url: z.string().min(1, 'Target URL is required'),
})

type RegisterScanTargetFormValues = z.infer<typeof registerScanTargetSchema>

export function RegisterTargetDialog() {
  const [open, setOpen] = useState(false)
  const registerScanTarget = useRegisterScanTarget()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<RegisterScanTargetFormValues>({
    resolver: zodResolver(registerScanTargetSchema),
  })

  const onSubmit = handleSubmit((values) => {
    registerScanTarget.mutate(values, {
      onSuccess: () => {
        toast.success('Scan target registered.')
        reset()
        setOpen(false)
      },
    })
  })

  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) {
          reset()
        }
      }}
    >
      <DialogTrigger asChild>
        <Button type="button">Register target</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register scan target</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="name">Name</Label>
            <Input id="name" {...register('name')} />
            {errors.name ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.name.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="target_url">Target URL</Label>
            <Input id="target_url" {...register('target_url')} />
            {errors.target_url ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.target_url.message}
              </p>
            ) : null}
          </div>
          {registerScanTarget.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {parseProblemMessage(registerScanTarget.error)}
            </p>
          ) : null}
          <Button type="submit" disabled={registerScanTarget.isPending}>
            {registerScanTarget.isPending ? 'Registering…' : 'Register'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
