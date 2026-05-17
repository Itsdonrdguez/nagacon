import { NavLink } from 'react-router-dom'

const items = [
  ['/', 'Dashboard'],
  ['/work-queue', 'Today'],
  ['/company', 'Company Profile'],
  ['/ingestion', 'Search'],
  ['/opportunities', 'Opportunities'],
  ['/pipeline', 'Pipeline'],
  ['/vendors', 'Vendor Intelligence'],
  ['/providers', 'Providers'],
  ['/nsn-intelligence', 'NSN Intelligence'],
  ['/publog-reference', 'PUB LOG Reference'],
  ['/data-health', 'Data Health'],
  ['/source-freshness', 'Source Freshness'],
  ['/settings', 'Settings'],
]

export default function Sidebar({
  mobileNavOpen = false,
  onNavigate = null,
  onLogout = null,
  logoutLoading = false,
  showLogout = true,
}) {
  return (
    <aside className={`sidebar ${mobileNavOpen ? 'open' : ''}`}>
      <div className="brand">
        <div className="brand-title">NagaCon</div>
        <div className="brand-subtitle">GovCon Intelligence Platform</div>
      </div>
      <nav className="nav">
        {items.map(([to, label]) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
            onClick={() => onNavigate?.()}
          >
            {label}
          </NavLink>
        ))}
      </nav>
      {showLogout ? (
        <div className="sidebar-footer">
          <button
            type="button"
            className="nav-link nav-link-action"
            onClick={() => {
              onNavigate?.()
              onLogout?.()
            }}
            disabled={logoutLoading}
          >
            {logoutLoading ? 'Logging out...' : 'Log Out'}
          </button>
        </div>
      ) : null}
    </aside>
  )
}
