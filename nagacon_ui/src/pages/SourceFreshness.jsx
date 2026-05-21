import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, Button, Card, EmptyState, LoadingState } from '../components/ui'

const STATUS_VARIANT = {
  fresh: 'success',
  stale: 'warning',
  missing: 'error',
}

const formatDate = (value) => {
  if (!value) return 'Never'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function SourceFreshness() {
  const freshnessQuery = useQuery({
    queryKey: ['source-freshness'],
    queryFn: async () => {
      const res = await api.get('/api/source-freshness')
      return res.data
    },
    retry: 1,
  })

  if (freshnessQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading source freshness..." />
        </Card>
      </div>
    )
  }

  if (freshnessQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Source freshness unavailable"
          subtitle={freshnessQuery.error.message || 'Could not load source freshness.'}
          action={<Button onClick={() => freshnessQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  const data = freshnessQuery.data || {}
  const sources = data.sources || []
  const summary = data.summary || {}

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Data Operations</div>
          <h1 className="page-title">Source Freshness</h1>
          <div className="page-subtitle">Track whether the government data layers powering NagaCon are fresh, stale, or missing.</div>
        </div>
        <Button variant="secondary" onClick={() => freshnessQuery.refetch()}>
          Refresh
        </Button>
      </div>

      <div className="stats-grid">
        <Card className="work-queue-stat">
          <div className="stat-label">Fresh</div>
          <div className="stat-value">{summary.fresh || 0}</div>
          <div className="stat-subtitle">Ready for analysis</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Stale</div>
          <div className="stat-value">{summary.stale || 0}</div>
          <div className="stat-subtitle">Refresh recommended</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Missing</div>
          <div className="stat-value">{summary.missing || 0}</div>
          <div className="stat-subtitle">Needs first import</div>
        </Card>
      </div>

      <Card title="Source Status">
        <div className="work-queue-list">
          {sources.map((source) => (
            <div key={source.key} className="source-freshness-row">
              <div>
                <div className="row-title">{source.label}</div>
                <div className="panel-subtitle">{source.detail}</div>
                <div className="row-subtitle">Latest: {formatDate(source.latest_at)}</div>
              </div>
              <Badge label={source.status} variant={STATUS_VARIANT[source.status] || 'default'} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  )
}
