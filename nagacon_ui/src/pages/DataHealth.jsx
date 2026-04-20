import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, Button, Card, EmptyState, LoadingState } from '../components/ui'

const STATUS_VARIANT = {
  ready: 'success',
  thin: 'warning',
  missing: 'error',
  fresh: 'success',
  stale: 'warning',
}

const formatNumber = (value) => Number(value || 0).toLocaleString()

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

const percent = (value) => `${Math.round(Number(value || 0) * 100)}%`

function MetricList({ metrics = [] }) {
  return (
    <div className="data-health-metrics">
      {metrics.map((metric) => (
        <div key={metric.label} className="data-health-metric">
          <span>{metric.label}</span>
          <strong>{formatNumber(metric.value)}</strong>
        </div>
      ))}
    </div>
  )
}

export default function DataHealth() {
  const dataHealthQuery = useQuery({
    queryKey: ['data-health'],
    queryFn: async () => {
      const res = await api.get('/api/data-health')
      return res.data
    },
    retry: 1,
  })

  if (dataHealthQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading data health..." />
        </Card>
      </div>
    )
  }

  if (dataHealthQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Data health unavailable"
          subtitle={dataHealthQuery.error.message || 'Could not load data health.'}
          action={<Button onClick={() => dataHealthQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  const data = dataHealthQuery.data || {}
  const summary = data.summary || {}
  const coverage = data.coverage || {}
  const categories = data.categories || []
  const readinessChecks = data.readiness_checks || []
  const freshnessSources = data.source_freshness?.sources || []
  const saasSummary = data.saas_readiness?.summary || {}
  const latestPublog = data.latest_publog_import

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Operations</div>
          <h1 className="page-title">Data Health</h1>
          <div className="page-subtitle">Check whether the NSN catalog, vendor database, award evidence, workflows, and SaaS guardrails are ready to power NagaCon.</div>
        </div>
        <Button variant="secondary" onClick={() => dataHealthQuery.refetch()}>
          Refresh
        </Button>
      </div>

      <div className="stats-grid">
        <Card className="work-queue-stat">
          <div className="stat-label">Ready</div>
          <div className="stat-value">{summary.ready || 0}</div>
          <div className="stat-subtitle">Healthy checks</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Thin</div>
          <div className="stat-value">{summary.thin || 0}</div>
          <div className="stat-subtitle">Needs more data</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Missing</div>
          <div className="stat-value">{summary.missing || 0}</div>
          <div className="stat-subtitle">Needs first import</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">SaaS Scope</div>
          <div className="stat-value">{saasSummary.ready_for_saas ? 'Ready' : 'Review'}</div>
          <div className="stat-subtitle">{saasSummary.warnings || 0} warnings</div>
        </Card>
      </div>

      <div className="data-health-grid">
        {categories.map((category) => (
          <Card key={category.key} className="data-health-card">
            <div className="data-health-card-header">
              <div>
                <div className="row-title">{category.label}</div>
                <div className="panel-subtitle">{category.summary}</div>
              </div>
              <Badge label={category.status} variant={STATUS_VARIANT[category.status] || 'default'} />
            </div>
            <MetricList metrics={category.metrics} />
          </Card>
        ))}
      </div>

      <Card title="NSN-NOW Replacement Backbone">
        <div className="data-health-readiness">
          {readinessChecks.map((check) => (
            <div key={check.key} className="source-freshness-row">
              <div>
                <div className="row-title">{check.label}</div>
                <div className="panel-subtitle">{check.detail}</div>
              </div>
              <Badge label={check.status} variant={STATUS_VARIANT[check.status] || 'default'} />
            </div>
          ))}
        </div>
      </Card>

      <div className="data-health-grid">
        <Card title="Coverage">
          <div className="data-health-metrics">
            <div className="data-health-metric">
              <span>References per NSN</span>
              <strong>{coverage.references_per_nsn || 0}</strong>
            </div>
            <div className="data-health-metric">
              <span>Interchangeability per NSN</span>
              <strong>{coverage.interchangeability_per_nsn || 0}</strong>
            </div>
            <div className="data-health-metric">
              <span>Award evidence per NSN</span>
              <strong>{coverage.award_evidence_per_nsn || 0}</strong>
            </div>
            <div className="data-health-metric">
              <span>Provider item coverage</span>
              <strong>{percent(coverage.provider_item_coverage)}</strong>
            </div>
            <div className="data-health-metric">
              <span>Vendor leads per opportunity</span>
              <strong>{coverage.vendor_leads_per_opportunity || 0}</strong>
            </div>
            <div className="data-health-metric">
              <span>Part Finder artifacts</span>
              <strong>{formatNumber(coverage.part_finder_artifacts)}</strong>
            </div>
          </div>
        </Card>

        <Card title="Latest PUB LOG Import">
          {latestPublog ? (
            <div className="data-health-stack">
              <div className="source-freshness-row">
                <div>
                  <div className="row-title">{latestPublog.source_name}</div>
                  <div className="panel-subtitle">{latestPublog.source_file || 'No source file recorded'}</div>
                  <div className="row-subtitle">Completed {formatDate(latestPublog.completed_at)}</div>
                </div>
                <Badge label={latestPublog.status} variant={latestPublog.status === 'completed' ? 'success' : 'warning'} />
              </div>
              <MetricList
                metrics={[
                  { label: 'Rows Seen', value: latestPublog.rows_seen },
                  { label: 'Rows Imported', value: latestPublog.rows_imported },
                ]}
              />
              {latestPublog.error ? <div className="error-text">{latestPublog.error}</div> : null}
            </div>
          ) : (
            <EmptyState
              title="No PUB LOG import yet"
              subtitle="Import PublogDVD.zip to populate NSN master, reference, and interchangeability data."
            />
          )}
        </Card>
      </div>

      <Card title="Source Freshness">
        <div className="work-queue-list">
          {freshnessSources.map((source) => (
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
