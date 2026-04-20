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
  ['/data-health', 'Data Health'],
  ['/source-freshness', 'Source Freshness'],
  ['/settings', 'Settings'],
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-title">NagaCon</div>
        <div className="brand-subtitle">GovCon Intelligence Platform</div>
      </div>
      <nav className="nav">
        {items.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}>
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
