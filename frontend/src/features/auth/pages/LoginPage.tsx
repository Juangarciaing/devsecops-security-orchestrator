import { Navigate } from 'react-router'
import { useAuth } from '@/app/auth/useAuth'
import { Card, CardContent, CardHeader, CardTitle } from '@/shared/ui/card'
import { LoginForm } from '../components/LoginForm'

export function LoginPage() {
  const auth = useAuth()

  if (auth.status === 'authed') {
    return <Navigate to="/" replace />
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Log in</CardTitle>
        </CardHeader>
        <CardContent>
          <LoginForm />
        </CardContent>
      </Card>
    </main>
  )
}
