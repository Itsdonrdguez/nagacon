import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api/client'
import Sidebar from './components/layout/Sidebar/Sidebar'
import RouteErrorBoundary from './components/RouteErrorBoundary'
import { Button, LoadingState } from './components/ui'

export default function App() {
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
  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    enabled: Boolean(authQuery.data?.authenticated),
    queryFn: async () => {
      const res = await api.get('/api/notifications')
      return res.data
    },
    retry: 1,
  })
  const logoutMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/auth/logout')
      return res.data
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  if (authQuery.isLoading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <LoadingState label="Loading workspace..." />
        </div>
      </div>
    )
  }

  if (!authQuery.data?.authenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content">
        <div className="app-topbar">
          <div>
            <div className="row-title">
              {authQuery.data?.organization?.name || 'Workspace'}
            </div>
            <div className="row-subtitle">
              {authQuery.data?.user?.full_name || authQuery.data?.user?.email || 'Current user'}
              {authQuery.data?.user?.role ? ` | ${authQuery.data.user.role}` : ''}
            </div>
          </div>
          <Link className="topbar-notification-link" to="/work-queue">
            {notificationsQuery.data?.unread_count || 0} alerts
          </Link>
          <Button variant="secondary" size="sm" loading={logoutMutation.isPending} onClick={() => logoutMutation.mutate()}>
            Log Out
          </Button>
        </div>
        <RouteErrorBoundary>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  )
}
