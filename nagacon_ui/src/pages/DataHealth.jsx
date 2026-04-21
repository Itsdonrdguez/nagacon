import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
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
  const queryClient = useQueryClient()
  const [publogJobId, setPublogJobId] = useState(null)
  const dataHealthQuery = useQuery({
    queryKey: ['data-health'],
    queryFn: async () => {
      const res = await api.get('/api/data-health')
      return res.data
    },
    retry: 1,
  })
  const publogStatusQuery = useQuery({
    queryKey: ['publog-status'],
    queryFn: async () => {
      const res = await api.get('/api/nsn/publog/status')
      return res.data
    },
    retry: 1,
  })
  const publogJobQuery = useQuery({
    queryKey: ['search-job', publogJobId],
    enabled: Boolean(publogJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${publogJobId}`)
      return res.data
    },
  })
  const publogSyncMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/nsn/publog/sync-job', { target_limit: 250 })
      return res.data
    },
    onSuccess: (job) => {
      setPublogJobId(job.id)
    },
  })

  useEffect(() => {
    if (publogJobQuery.data?.status !== 'success') return
    queryClient.invalidateQueries({ queryKey: ['data-health'] })
    queryClient.invalidateQueries({ queryKey: ['publog-status'] })
  }, [publogJobQuery.data?.status, publogJobQuery.data?.completed_at, queryClient])

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
  const publogStatus = publogStatusQuery.data || {}
  const publogJob = publogJobQuery.data
  const publogJobRunning = publogJob?.status === 'queued' || publogJob?.status === 'running'
  const latestPublogSource = latestPublog || publogStatus.latest_run

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

        <Card title="PUB LOG Package">
          <div className="data-health-stack">
            <div className="source-freshness-row">
              <div>
                <div className="row-title">{publogStatus.source_version || 'PUB LOG package'}</div>
                <div className="panel-subtitle">{publogStatus.zip_path || 'ZIP path unavailable'}</div>
                <div className="row-subtitle">
                  {publogStatus.zip?.size_bytes
                    ? `${formatNumber(publogStatus.zip.size_bytes)} bytes | ${publogStatus.zip.member_count || 0} files`
                    : 'Package metadata unavailable'}
                </div>
              </div>
              <Badge label={publogStatus.status || 'unknown'} variant={STATUS_VARIANT[publogStatus.status] || 'default'} />
            </div>
            <div className="data-health-action-row">
              <Button
                loading={publogSyncMutation.isPending || publogJobRunning}
                disabled={publogStatus.status !== 'ready'}
                onClick={() => publogSyncMutation.mutate()}
              >
                Sync PUB LOG Targets
              </Button>
              <Button variant="secondary" onClick={() => publogStatusQuery.refetch()}>
                Check Package
              </Button>
            </div>
            {publogJob ? (
              <div className="publog-job-box">
                <div className="source-freshness-row">
                  <div>
                    <div className="row-title">PUB LOG sync job</div>
                    <div className="panel-subtitle">
                      {(publogJob.progress?.current_label || 'Running package sync').trim()}
                    </div>
                    <div className="row-subtitle">
                      Status: {publogJob.status} | {publogJob.progress?.percent || 0}% complete
                    </div>
                  </div>
                  <Badge
                    label={publogJob.status}
                    variant={
                      publogJob.status === 'success'
                        ? 'success'
                        : publogJob.status === 'failed'
                          ? 'error'
                          : 'warning'
                    }
                  />
                </div>
                {publogJob.result?.target_count ? (
                  <div className="row-subtitle">
                    Targets: {publogJob.result.target_count} | Imported: {publogJob.result.imported || 0} | Failed: {publogJob.result.failed || 0}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </Card>
      </div>

      <Card title="Latest PUB LOG Import">
        {latestPublogSource ? (
          <div className="data-health-stack">
            <div className="data-health-stack">
              <div className="source-freshness-row">
                <div>
                  <div className="row-title">{latestPublogSource.source_name}</div>
                  <div className="panel-subtitle">{latestPublogSource.source_file || 'No source file recorded'}</div>
                  <div className="row-subtitle">Completed {formatDate(latestPublogSource.completed_at)}</div>
                </div>
                <Badge label={latestPublogSource.status} variant={latestPublogSource.status === 'completed' ? 'success' : 'warning'} />
              </div>
              <MetricList
                metrics={[
                  { label: 'Rows Seen', value: latestPublogSource.rows_seen },
                  { label: 'Rows Imported', value: latestPublogSource.rows_imported },
                ]}
              />
              {latestPublogSource.error ? <div className="error-text">{latestPublogSource.error}</div> : null}
            </div>
          </div>
        ) : (
          <EmptyState
            title="No PUB LOG import yet"
            subtitle="Import PublogDVD.zip to populate NSN master, reference, and interchangeability data."
          />
        )}
      </Card>

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
