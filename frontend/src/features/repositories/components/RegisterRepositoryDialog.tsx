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
import { useRegisterRepository } from '../queries'
import type { RepositoryProvider } from '../types'

const PROVIDERS: RepositoryProvider[] = ['github', 'gitlab', 'bitbucket']

const registerRepositorySchema = z.object({
  provider: z.enum(['github', 'gitlab', 'bitbucket']),
  owner: z.string().min(1, 'Owner is required'),
  name: z.string().min(1, 'Name is required'),
  clone_url: z.string().min(1, 'Clone URL is required'),
  default_branch: z.string().min(1, 'Default branch is required'),
  credential_ref: z.string().optional(),
})

type RegisterRepositoryFormValues = z.infer<typeof registerRepositorySchema>

export function RegisterRepositoryDialog() {
  const [open, setOpen] = useState(false)
  const registerRepository = useRegisterRepository()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<RegisterRepositoryFormValues>({
    resolver: zodResolver(registerRepositorySchema),
    defaultValues: { provider: 'github' },
  })

  const onSubmit = handleSubmit((values) => {
    registerRepository.mutate(
      { ...values, credential_ref: values.credential_ref || undefined },
      {
        onSuccess: () => {
          toast.success('Repository registered.')
          reset()
          setOpen(false)
        },
      },
    )
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
        <Button type="button">Register repository</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Register repository</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="provider">Provider</Label>
            <select
              id="provider"
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              {...register('provider')}
            >
              {PROVIDERS.map((provider) => (
                <option key={provider} value={provider}>
                  {provider}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="owner">Owner</Label>
            <Input id="owner" {...register('owner')} />
            {errors.owner ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.owner.message}
              </p>
            ) : null}
          </div>
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
            <Label htmlFor="clone_url">Clone URL</Label>
            <Input id="clone_url" {...register('clone_url')} />
            {errors.clone_url ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.clone_url.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="default_branch">Default branch</Label>
            <Input id="default_branch" {...register('default_branch')} />
            {errors.default_branch ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.default_branch.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="credential_ref">
              Credential reference (optional)
            </Label>
            <Input id="credential_ref" {...register('credential_ref')} />
          </div>
          {registerRepository.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {parseProblemMessage(registerRepository.error)}
            </p>
          ) : null}
          <Button type="submit" disabled={registerRepository.isPending}>
            {registerRepository.isPending ? 'Registering…' : 'Register'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
