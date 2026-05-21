import { useState } from 'react'

export default function Tabs({
  tabs = [],
  activeTab: controlledActiveTab = null,
  onChange = null,
  className = '',
  mobileSelect = false,
  mobileLabel = 'Section',
}) {
  const [internalActiveTab, setInternalActiveTab] = useState(0)
  const activeTab = Number.isInteger(controlledActiveTab) ? controlledActiveTab : internalActiveTab

  if (tabs.length === 0) return null

  const active = tabs[activeTab] || tabs[0]
  const setActiveTab = (idx) => {
    if (!Number.isInteger(controlledActiveTab)) {
      setInternalActiveTab(idx)
    }
    onChange?.(idx)
  }

  return (
    <div className={`tabs-container ${className}`.trim()}>
      {mobileSelect ? (
        <label className="tabs-mobile-select">
          <span className="tabs-mobile-select-label">{mobileLabel}</span>
          <select
            value={activeTab}
            onChange={(event) => setActiveTab(Number(event.target.value))}
          >
            {tabs.map((tab, idx) => (
              <option key={idx} value={idx}>
                {tab.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="tabs-nav">
        {tabs.map((tab, idx) => (
          <button
            key={idx}
            className={`tab-button ${activeTab === idx ? 'active' : ''}`}
            onClick={() => setActiveTab(idx)}
          >
            {tab.icon ? <span className="tab-icon">{tab.icon}</span> : null}
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tabs-content">
        {active.content}
      </div>
    </div>
  )
}
