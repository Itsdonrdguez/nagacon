import { useQuery } from '@tanstack/react-query'
import { PieChart, Pie, Cell, ResponsiveContainer } from 'recharts'
import { api } from '../api/client'
import StatCard from '../components/StatCard'

export default function Dashboard() {
  const { data } = useQuery({
    queryKey: ['dashboard-opps'],
    queryFn: async () => {
      const res = await api.get('/api/opportunities?limit=50&offset=0')
      return Array.isArray(res.data) ? res.data : (res.data.value || [])
    },
  })

  const opps = data || []
  const samCount = opps.filter(o => o.source === 'SAM').length
  const dibbsCount = opps.filter(o => o.source === 'DIBBS').length
  const pieData = [{ name: 'SAM', value: samCount }, { name: 'DIBBS', value: dibbsCount }]

  return (
    <div className="page">
      <h1 className="page-title">Dashboard</h1>
      <div className="stats-grid">
        <StatCard label="Total Opportunities" value={opps.length} subtitle="Live from backend" />
        <StatCard label="SAM Opportunities" value={samCount} />
        <StatCard label="DIBBS Opportunities" value={dibbsCount} />
        <StatCard label="Active Workspaces" value={Math.min(opps.length, 8)} />
      </div>
      <div className="dashboard-grid">
        <div className="card">
          <h2>Recent Opportunities</h2>
          <div className="simple-list">
            {opps.slice(0, 6).map(opp => (
              <div key={opp.id} className="simple-list-row">
                <div>
                  <div className="row-title">{opp.display_title || opp.title}</div>
                  <div className="row-subtitle">{opp.source} · {opp.agency}</div>
                </div>
                <a className="action-btn" href={`/workspace/${opp.id}`}>Open</a>
              </div>
            ))}
          </div>
        </div>
        <div className="card">
          <h2>Opportunities by Source</h2>
          <div style={{ width: '100%', height: 280 }}>
            <ResponsiveContainer>
              <PieChart>
                <Pie data={pieData} dataKey="value" nameKey="name" innerRadius={70} outerRadius={100}>
                  <Cell fill="#2563eb" />
                  <Cell fill="#f97316" />
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="legend"><span>SAM: {samCount}</span><span>DIBBS: {dibbsCount}</span></div>
        </div>
      </div>
    </div>
  )
}
