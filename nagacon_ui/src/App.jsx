import { useEffect, useState } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, persistSessionToken } from './api/client'
import Sidebar from './components/layout/Sidebar/Sidebar'
import RouteErrorBoundary from './components/RouteErrorBoundary'
import { Button, LoadingState } from './components/ui'

const LOCAL_MODE = String(import.meta.env.VITE_LOCAL_MODE ?? 'true').toLowerCase() !== 'false'
const LOCAL_SESSION = {
  authenticated: true,
  user: {
    full_name: 'Local Operator',
    email: 'owner@nagacon.local',
    role: 'OWNER',
  },
  organization: {
    name: 'NagaCon Local',
  },
}

export default function App() {
  const location = useLocation()
  const queryClient = useQueryClient()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const authQuery = useQuery({
    queryKey: ['auth-me'],
    enabled: !LOCAL_MODE,
    queryFn: async () => {
      const res = await api.get('/api/auth/me')
      return res.data
    },
    retry: 1,
  })
  const authData = LOCAL_MODE ? LOCAL_SESSION : authQuery.data
  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    enabled: Boolean(authData?.authenticated),
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
      persistSessionToken(null)
      await queryClient.invalidateQueries({ queryKey: ['auth-me'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
    },
  })

  useEffect(() => {
    setMobileNavOpen(false)
  }, [location.pathname])

  if (!LOCAL_MODE && authQuery.isLoading) {
    return (
      <div className="auth-shell">
        <div className="auth-card">
          <LoadingState label="Loading workspace..." />
        </div>
      </div>
    )
  }

  if (!LOCAL_MODE && !authQuery.data?.authenticated) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return (
    <div className={`app-shell ${mobileNavOpen ? 'nav-open' : ''}`}>
      <button
        type="button"
        className={`mobile-nav-backdrop ${mobileNavOpen ? 'visible' : ''}`}
        aria-label="Close navigation"
        onClick={() => setMobileNavOpen(false)}
      />
      <Sidebar
        mobileNavOpen={mobileNavOpen}
        onNavigate={() => setMobileNavOpen(false)}
        onLogout={() => logoutMutation.mutate()}
        logoutLoading={logoutMutation.isPending}
        showLogout={!LOCAL_MODE}
      />
      <main className="main-content">
        <div className="app-topbar">
          <div className="topbar-leading">
            <button
              type="button"
              className={`mobile-nav-toggle ${mobileNavOpen ? 'active' : ''}`}
              aria-label={mobileNavOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={mobileNavOpen}
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              <span />
              <span />
              <span />
            </button>
            <div>
              <div className="row-title">
                {authData?.organization?.name || 'Workspace'}
              </div>
              <div className="row-subtitle">
                {authData?.user?.full_name || authData?.user?.email || 'Current user'}
                {authData?.user?.role ? ` | ${authData.user.role}` : ''}
                {LOCAL_MODE ? ' | local mode' : ''}
              </div>
            </div>
          </div>
          <div className="topbar-actions">
            <Link className="topbar-notification-link" to="/work-queue">
              {notificationsQuery.data?.unread_count || 0} alerts
            </Link>
            {!LOCAL_MODE ? (
              <Button className="topbar-logout-button" variant="secondary" size="sm" loading={logoutMutation.isPending} onClick={() => logoutMutation.mutate()}>
                Log Out
              </Button>
            ) : null}
          </div>
        </div>
        <RouteErrorBoundary>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  )
}
