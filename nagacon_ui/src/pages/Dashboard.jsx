import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts'
import { api } from '../api/client'
import { StatCard, EmptyState, Badge, Card, Button, LoadingState, StatusPill } from '../components/ui'
import { sourceIcon } from '../utils/badges'

const formatDueDate = (dueAt) => {
  if (!dueAt) return '-'

  const due = new Date(dueAt)
  const now = new Date()
  const daysLeft = Math.ceil((due - now) / (1000 * 60 * 60 * 24))
  const formatted = due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  if (daysLeft < 0) return `Closed ${formatted}`
  if (daysLeft === 0) return 'Today'
  if (daysLeft === 1) return 'Tomorrow'
  return `${formatted} (${daysLeft}d)`
}

const getDueSoonClass = (daysLeft) => {
  if (daysLeft < 0) return 'due-closed'
  if (daysLeft <= 3) return 'due-urgent'
  if (daysLeft <= 7) return 'due-soon'
  return 'due-normal'
}

const formatCurrency = (value) => {
  if (typeof value !== 'number' || Number.isNaN(value)) return 'Not set'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(value)
}

export default function Dashboard() {
  const opportunitiesQuery = useQuery({
    queryKey: ['dashboard-opps'],
    queryFn: async () => {
      const res = await api.get('/api/opportunities?limit=50&offset=0')
      return Array.isArray(res.data) ? res.data : (res.data.value || [])
    },
    retry: 1,
  })

  const recentOpenQuery = useQuery({
    queryKey: ['dashboard-recent-open-opps'],
    queryFn: async () => {
      const res = await api.get('/api/opportunities?limit=8&offset=0&due_window=open')
      return Array.isArray(res.data) ? res.data : (res.data.value || [])
    },
    retry: 1,
  })

  const companyQuery = useQuery({
    queryKey: ['company-profile'],
    queryFn: async () => {
      const res = await api.get('/api/company/profile')
      return res.data
    },
    retry: 1,
  })

  const opps = opportunitiesQuery.data || []
  const recentOpenOpps = recentOpenQuery.data || []
  const company = companyQuery.data || null

  const samCount = opps.filter((opp) => opp.source === 'SAM').length
  const dibbsCount = opps.filter((opp) => opp.source === 'DIBBS').length

  const dueSoon = opps
    .filter((opp) => {
      if (!opp.due_at) return false
      const daysLeft = Math.ceil((new Date(opp.due_at) - new Date()) / (1000 * 60 * 60 * 24))
      return daysLeft > 0 && daysLeft <= 7
    })
    .sort((a, b) => new Date(a.due_at) - new Date(b.due_at))

  const bySetAside = {}
  opps.forEach((opp) => {
    const type = opp.set_aside_type || 'Open'
    bySetAside[type] = (bySetAside[type] || 0) + 1
  })

  const setAsideData = Object.entries(bySetAside)
    .map(([name, value]) => ({ name: name.substring(0, 18), value }))
    .sort((a, b) => b.value - a.value)

  const sourceData = [
    { name: 'SAM', value: samCount },
    { name: 'DIBBS', value: dibbsCount },
  ]

  const dueDateData = [
    {
      name: 'Due Soon',
      value: dueSoon.length,
    },
    {
      name: 'Due Later',
      value: opps.filter((opp) => {
        if (!opp.due_at) return false
        const daysLeft = Math.ceil((new Date(opp.due_at) - new Date()) / (1000 * 60 * 60 * 24))
        return daysLeft > 7
      }).length,
    },
    {
      name: 'Closed',
      value: opps.filter((opp) => {
        if (!opp.due_at) return false
        const daysLeft = Math.ceil((new Date(opp.due_at) - new Date()) / (1000 * 60 * 60 * 24))
        return daysLeft < 0
      }).length,
    },
  ]

  if (opportunitiesQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading dashboard..." />
        </Card>
      </div>
    )
  }

  if (opportunitiesQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Dashboard unavailable"
          subtitle={opportunitiesQuery.error.message || 'Failed to load opportunities.'}
          action={<Button onClick={() => opportunitiesQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Command Center</div>
          <h1 className="page-title">Dashboard</h1>
          <div className="page-subtitle">Track opportunity flow, due-date pressure, and company readiness from one clean overview.</div>
        </div>
      </div>

      <div className="stats-grid">
        <StatCard label="Total Opportunities" value={opps.length} subtitle={`${samCount} SAM | ${dibbsCount} DIBBS`} />
        <StatCard label="Due Soon (7d)" value={dueSoon.length} subtitle={dueSoon.length > 0 ? 'Attention required' : 'No urgent deadlines'} />
        <StatCard label="Active Workspaces" value={opps.length} subtitle="Workspace-ready opportunities" />
        <StatCard label="Set-Asides Available" value={Object.keys(bySetAside).length} subtitle="Opportunity coverage" />
      </div>

      <Card title="Company Profile">
        {companyQuery.isLoading ? (
          <LoadingState label="Loading company profile..." />
        ) : company ? (
          <div className="company-profile-grid">
            <div className="company-info">
              <div className="company-name">{company.legal_name}</div>
              <div className="company-contact">
                <strong>UEI:</strong> {company.uei || 'Not set'}
              </div>
              <div className="company-contact">
                <strong>CAGE:</strong> {company.cage || 'Not set'}
              </div>
              <div className="company-contact">
                <strong>Annual Revenue:</strong> {formatCurrency(company.annual_revenue)}
              </div>
              {company.capability_statement_url ? (
                <div className="company-contact">
                  <a href={company.capability_statement_url} target="_blank" rel="noreferrer">
                    View capability statement
                  </a>
                </div>
              ) : null}
            </div>

            <div className="company-identifiers">
              <div className="identifier-row">
                <span className="identifier-label">Certifications</span>
                <div className="badge-stack">
                  {(company.certifications || []).length > 0 ? (
                    company.certifications.map((item) => (
                      <Badge key={item} label={item} variant="info" />
                    ))
                  ) : (
                    <StatusPill status="Not Requested" />
                  )}
                </div>
              </div>
              <div className="identifier-row">
                <span className="identifier-label">NAICS</span>
                <div className="badge-stack">
                  {(company.naics_codes || []).length > 0 ? (
                    company.naics_codes.map((code) => (
                      <Badge key={code} label={code} variant="success" />
                    ))
                  ) : (
                    <StatusPill status="Not Requested" />
                  )}
                </div>
              </div>
              {company.core_competencies ? (
                <div className="company-copy-block">
                  <strong>Core Competencies</strong>
                  <p>{company.core_competencies}</p>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <EmptyState
            title="No company profile yet"
            subtitle="Create a company profile to power dashboard intelligence and future bid analysis."
          />
        )}
      </Card>

      {dueSoon.length > 0 ? (
        <Card title="Due Soon">
          <div className="due-soon-list">
            {dueSoon.slice(0, 5).map((opp) => {
              const daysLeft = Math.ceil((new Date(opp.due_at) - new Date()) / (1000 * 60 * 60 * 24))
              return (
                <div key={opp.id} className={`due-item ${getDueSoonClass(daysLeft)}`}>
                  <div className="due-item-header">
                    <div className="due-item-title">{opp.display_title || opp.title}</div>
                    <StatusPill status={daysLeft <= 3 ? 'Due' : 'Pending'} />
                  </div>
                  <div className="due-item-meta">
                    <span className="badge-inline">{opp.source}</span>
                    <span className="badge-inline">{formatDueDate(opp.due_at)}</span>
                    <Link className="action-btn-inline" to={`/workspace/${opp.id}`}>Open workspace</Link>
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      ) : null}

      <div className="dashboard-charts-grid">
        <Card title="Opportunities by Source">
          <div className="chart-frame">
            <ResponsiveContainer>
              <PieChart>
                <Pie data={sourceData} dataKey="value" nameKey="name" innerRadius={60} outerRadius={90}>
                  <Cell fill="#2563eb" />
                  <Cell fill="#f97316" />
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="legend">
            <span>SAM {samCount}</span>
            <span>DIBBS {dibbsCount}</span>
          </div>
        </Card>

        <Card title="Due Date Distribution">
          <div className="chart-frame">
            <ResponsiveContainer>
              <BarChart data={dueDateData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip contentStyle={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '8px' }} />
                <Bar dataKey="value" fill="#2563eb" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Set-Aside Distribution">
        {setAsideData.length > 0 ? (
          <div className="set-aside-grid">
            {setAsideData.map((item) => (
              <div key={item.name} className="set-aside-item">
                <div className="set-aside-label">{item.name}</div>
                <div className="set-aside-count">{item.value}</div>
                <div className="set-aside-bar">
                  <div
                    className="set-aside-bar-fill"
                    style={{ width: `${(item.value / Math.max(...setAsideData.map((entry) => entry.value), 1)) * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No set-aside data yet" subtitle="Opportunity ingestion will populate this breakdown." />
        )}
      </Card>

      <Card title="Recent Open Opportunities">
        {recentOpenQuery.isLoading ? (
          <LoadingState label="Loading recent opportunities..." />
        ) : recentOpenOpps.length > 0 ? (
          <div className="simple-list">
            {recentOpenOpps.slice(0, 6).map((opp) => (
              <div key={opp.id} className="simple-list-row">
                <div className="list-item-content">
                  <div className="row-title">{opp.display_title || opp.title}</div>
                  <div className="row-meta">
                    <Badge label={opp.source} variant={opp.source === 'SAM' ? 'success' : 'info'} />
                    <span className="agency-inline">{opp.solicitation_number || 'Solicitation unavailable'}</span>
                    <span className="agency-inline">{opp.agency || 'Agency unavailable'}</span>
                    <span className="agency-inline">{formatDueDate(opp.due_at)}</span>
                    {(opp.fsc || opp.naics) ? (
                      <span className="agency-inline">{opp.fsc ? `FSC ${opp.fsc}` : `NAICS ${opp.naics}`}</span>
                    ) : null}
                  </div>
                </div>
                <Link className="action-btn-small" to={`/workspace/${opp.id}`}>Open</Link>
              </div>
            ))}
          </div>
        ) : (
          <EmptyState title="No open opportunities yet" subtitle="Import SAM or DIBBS opportunities, or adjust the opportunities filters to review closed records." />
        )}
      </Card>
    </div>
  )
}
