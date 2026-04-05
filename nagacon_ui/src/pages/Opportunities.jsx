import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export default function Opportunities() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['opportunities'],
    queryFn: async () => {
      const res = await api.get('/api/opportunities?limit=50&offset=0')
      return Array.isArray(res.data) ? res.data : (res.data.value || [])
    },
  })

  if (isLoading) return <div className="page">Loading opportunities...</div>
  if (error) return <div className="page">Failed to load opportunities.</div>

  return (
    <div className="page">
      <h1 className="page-title">Opportunities</h1>
      <div className="card">
        <table className="data-table">
          <thead><tr><th>Title</th><th>Source</th><th>Agency</th><th>NAICS/FSC</th><th>Action</th></tr></thead>
          <tbody>
            {data.map(opp => (
              <tr key={opp.id}>
                <td><div className="row-title">{opp.display_title || opp.title}</div><div className="row-subtitle">{opp.solicitation_number}</div></td>
                <td>{opp.source}</td>
                <td>{opp.agency}</td>
                <td>{opp.naics_code || opp.fsc_code || '-'}</td>
                <td><Link className="action-btn" to={`/workspace/${opp.id}`}>Workspace</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
