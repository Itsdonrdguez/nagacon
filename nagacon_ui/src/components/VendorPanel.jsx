import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import EmptyState from './EmptyState'
import Badge from './Badge'

export default function VendorPanel({ opportunityId }) {
  const { data: vendorMatches, isLoading, error } = useQuery({
    queryKey: ['workspace-vendors', opportunityId],
    queryFn: async () => {
      // This would use a dedicated endpoint or extracts from workspace/summary
      // For now, we'll use the data passed from parent or fetch separately
      return []
    },
    enabled: false, // Parent will pass data directly
  })

  return (
    <div className="vendor-panel">
      <h2>Matched Vendors</h2>
      <p className="panel-subtitle">Vendors related to this opportunity</p>

      {isLoading ? (
        <div className="stat-value">Loading vendors...</div>
      ) : error ? (
        <EmptyState
          title="Failed to Load Vendors"
          subtitle={error.message || 'Unable to fetch vendor matches'}
        />
      ) : !vendorMatches || vendorMatches.length === 0 ? (
        <EmptyState
          title="No Vendor Matches"
          subtitle="Run vendor sync to find related companies"
          action={<button className="action-btn">Sync Vendors</button>}
        />
      ) : (
        <div className="vendor-list">
          {vendorMatches.map(v => (
            <div key={v.id || v.vendor_id} className="vendor-item">
              <div className="vendor-name">{v.vendor_name || v.vendor_id}</div>
              <div className="vendor-meta">
                <Badge label={v.cage_code || 'N/A'} variant="info" />
                {v.match_reason ? <Badge label={v.match_reason} variant="success" /> : null}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
