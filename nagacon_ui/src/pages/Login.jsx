import { useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Button, Card, Input, LoadingState } from '../components/ui'

export default function Login() {
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({
    full_name: '',
    identifier: '',
    password: '',
  })
  const navigate = useNavigate()
  const location = useLocation()
  const queryClient = useQueryClient()
  const authQuery = useQuery({
    queryKey: ['auth-me'],
    queryFn: async () => {
      const res = await api.get('/api/auth/me')
      return res.data
    },
    retry: 1,
  })

  const authMutation = useMutation({
    mutationFn: async (payload) => {
      const url = mode === 'signup' ? '/api/auth/signup' : '/api/auth/login'
      const res = await api.post(url, payload)
      return res.data
    },
    onSuccess: async (data) => {
      queryClient.setQueryData(['auth-me'], data)
      await queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      navigate(location.state?.from || '/', { replace: true })
    },
  })

  useEffect(() => {
    authMutation.reset()
  }, [mode])

  if (authQuery.isLoading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <LoadingState label="Loading sign in..." />
        </div>
      </div>
    )
  }

  if (authQuery.data?.authenticated) {
    return <Navigate to={location.state?.from || '/'} replace />
  }

  return (
    <div className="auth-shell">
      <Card className="auth-card">
        <div className="auth-brand">NagaCon</div>
        <div className="page-kicker">GovCon Intelligence</div>
        <h1 className="page-title auth-title">{mode === 'signup' ? 'Create your account' : 'Welcome back'}</h1>
        <div className="page-subtitle">
          {mode === 'signup'
            ? 'Start with a real account so the workspace is ready for online SaaS deployment.'
            : 'Sign in to your workspace and pick up where the operation left off.'}
        </div>

        <div className="quote-follow-up-summary">
          <button type="button" className={`quote-filter-chip ${mode === 'login' ? 'quote-filter-active' : ''}`} onClick={() => setMode('login')}>
            Log In
          </button>
          <button type="button" className={`quote-filter-chip ${mode === 'signup' ? 'quote-filter-active' : ''}`} onClick={() => setMode('signup')}>
            Sign Up
          </button>
        </div>

        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault()
            const payload = {
              email: form.identifier,
              identifier: form.identifier,
              password: form.password,
            }
            if (mode === 'signup') {
              payload.full_name = form.full_name
            }
            authMutation.mutate(payload)
          }}
        >
          {mode === 'signup' ? (
            <Input
              label="Full Name"
              value={form.full_name}
              onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
              placeholder="Your name"
            />
          ) : null}
          <Input
            label="Username or Email"
            value={form.identifier}
            onChange={(event) => setForm((current) => ({ ...current, identifier: event.target.value }))}
            placeholder="admin or you@company.com"
          />
          <Input
            label="Password"
            type="password"
            value={form.password}
            onChange={(event) => setForm((current) => ({ ...current, password: event.target.value }))}
            placeholder="At least 8 characters"
          />
          {authMutation.error ? (
            <div className="form-error">
              {authMutation.error?.response?.data?.detail || authMutation.error.message || 'Authentication failed.'}
            </div>
          ) : null}
          <Button type="submit" loading={authMutation.isPending}>
            {mode === 'signup' ? 'Create Account' : 'Log In'}
          </Button>
          {mode === 'login' ? (
            <div className="panel-subtitle">
              Temporary deployment-ready local admin login: <code>admin</code> / <code>admin</code>
            </div>
          ) : null}
        </form>
      </Card>
    </div>
  )
}
