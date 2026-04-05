import { NavLink } from 'react-router-dom'

const items = [
  ['/', 'Dashboard'],
  ['/opportunities', 'Opportunities'],
  ['/vendors', 'Vendors'],
  ['/workspace/25', 'Workspace'],
]

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-title">NagaCon</div>
        <div className="brand-subtitle">Gov Opportunity Tracker</div>
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
