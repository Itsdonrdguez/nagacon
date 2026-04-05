import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'

export default function Workspace() {
  const { id } = useParams()
  const { data, isLoading } = useQuery({
    queryKey: ['workspace', id],
    queryFn: async () => {
      const res = await api.get(`/api/workspace/summary?opp_id=${id}`)
      return res.data
    },
  })

  if (isLoading) return <div className="page">Loading workspace...</div>

  const opp = data?.opportunity || {}
  const vendors = data?.vendor_matches || []

  return (
    <div className="page">
      <h1 className="page-title">Opportunity Workspace</h1>
      <div className="workspace-grid">
        <div className="card">
          <h2>{opp.display_title || opp.title || 'Opportunity'}</h2>
          <p className="row-subtitle">{opp.agency}</p>
          <div className="meta-grid">
            <div><strong>Source:</strong> {opp.source || '-'}</div>
            <div><strong>Due:</strong> {opp.due_at || '-'}</div>
            <div><strong>NAICS:</strong> {opp.naics || opp.naics_code || '-'}</div>
            <div><strong>FSC:</strong> {opp.fsc || opp.fsc_code || '-'}</div>
          </div>
        </div>
        <div className="card">
          <h2>Vendor Intelligence</h2>
          {vendors.length === 0 ? <p>No vendor matches yet.</p> : vendors.map(v => <div key={v.id || v.vendor_id} className="simple-list-row">{v.match_reason || v.vendor_id}</div>)}
        </div>
      </div>
    </div>
  )
}
