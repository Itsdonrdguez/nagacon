import { useState } from 'react'

export default function Tabs({ tabs = [] }) {
  const [activeTab, setActiveTab] = useState(0)

  if (tabs.length === 0) return null

  const active = tabs[activeTab] || tabs[0]

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
