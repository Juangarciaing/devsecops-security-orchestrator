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
import { useCreateUser } from '../queries'
import type { UserRole } from '@/features/auth/types'

const ROLES: UserRole[] = ['member', 'admin']

const createUserSchema = z.object({
  email: z
    .string()
    .min(1, 'Email is required')
    .email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  role: z.enum(['admin', 'member']),
})

type CreateUserFormValues = z.infer<typeof createUserSchema>

export function CreateUserDialog() {
  const [open, setOpen] = useState(false)
  const createUser = useCreateUser()
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<CreateUserFormValues>({
    resolver: zodResolver(createUserSchema),
    defaultValues: { role: 'member' },
  })

  const onSubmit = handleSubmit((values) => {
    createUser.mutate(values, {
      onSuccess: () => {
        toast.success('User created.')
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
        <Button type="button">Create user</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create user</DialogTitle>
        </DialogHeader>
        <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="off"
              {...register('email')}
            />
            {errors.email ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.email.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              autoComplete="new-password"
              {...register('password')}
            />
            {errors.password ? (
              <p role="alert" className="text-sm text-destructive">
                {errors.password.message}
              </p>
            ) : null}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="role">Role</Label>
            <select
              id="role"
              className="h-9 w-full rounded-md border border-input bg-transparent px-3 text-sm"
              {...register('role')}
            >
              {ROLES.map((role) => (
                <option key={role} value={role}>
                  {role}
                </option>
              ))}
            </select>
          </div>
          {createUser.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {parseProblemMessage(createUser.error)}
            </p>
          ) : null}
          <Button type="submit" disabled={createUser.isPending}>
            {createUser.isPending ? 'Creating…' : 'Create'}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
