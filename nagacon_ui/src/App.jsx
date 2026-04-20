import { Link, Outlet } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from './api/client'
import Sidebar from './components/layout/Sidebar/Sidebar'
import RouteErrorBoundary from './components/RouteErrorBoundary'

export default function App() {
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
    queryFn: async () => {
      const res = await api.get('/api/notifications')
      return res.data
    },
    retry: 1,
  })

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
        </div>
        <RouteErrorBoundary>
          <Outlet />
        </RouteErrorBoundary>
      </main>
    </div>
  )
}
