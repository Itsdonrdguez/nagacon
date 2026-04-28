import { useState } from 'react'

export default function Tabs({ tabs = [], activeTab: controlledActiveTab = null, onChange = null }) {
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
    <div className="tabs-container">
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
