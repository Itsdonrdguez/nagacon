import { NavLink } from 'react-router-dom'

import { useState } from 'react'

const sections = [
  {
    label: 'Operate',
    items: [
      ['/', 'Mission Control'],
      ['/work-queue', 'Today'],
      ['/opportunities', 'Opportunities'],
      ['/pipeline', 'Pipeline Lanes'],
      ['/vendors', 'Vendor Workflow'],
    ],
  },
  {
    label: 'Research',
    items: [
      ['/company', 'Company Criteria'],
      ['/ingestion', 'Daily Intake'],
      ['/providers', 'Providers'],
      ['/nsn-intelligence', 'NSN Intelligence'],
    ],
  },
  {
    label: 'Advanced / Labs',
    items: [
      ['/publog-reference', 'PUB LOG Reference'],
      ['/data-health', 'Data Health'],
      ['/source-freshness', 'Source Freshness'],
      ['/settings', 'Settings'],
    ],
  },
]

export default function Sidebar({
  mobileNavOpen = false,
  onNavigate = null,
  onLogout = null,
  logoutLoading = false,
  showLogout = true,
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  return (
    <aside className={`sidebar ${mobileNavOpen ? 'open' : ''}`}>
      <div className="brand">
        <div className="brand-title">NagaCon</div>
        <div className="brand-subtitle">GovCon Operator Cockpit</div>
      </div>
      <nav className="nav">
        {sections.map((section) => (
          <div key={section.label} className="nav-section">
            {section.label === 'Advanced / Labs' ? (
              <button
                type="button"
                className="nav-section-toggle"
                onClick={() => setAdvancedOpen((current) => !current)}
              >
                <span className="nav-section-label">{section.label}</span>
                <span className="nav-section-toggle-state">{advancedOpen ? 'Hide' : 'Show'}</span>
              </button>
            ) : (
              <div className="nav-section-label">{section.label}</div>
            )}
            {(section.label !== 'Advanced / Labs' || advancedOpen) ? section.items.map(([to, label]) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                onClick={() => onNavigate?.()}
              >
                {label}
              </NavLink>
            )) : null}
          </div>
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
