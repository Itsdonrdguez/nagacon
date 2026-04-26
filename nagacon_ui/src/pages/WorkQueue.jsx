import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, Button, Card, EmptyState, LoadingState } from '../components/ui'

const PRIORITY_VARIANT = {
  HIGH: 'error',
  MEDIUM: 'warning',
  LOW: 'info',
}

const TYPE_LABELS = {
  QUOTE_FOLLOW_UP_DUE: 'Quote Follow-up',
  QUOTE_REQUESTED_NO_RESPONSE: 'Awaiting Quote',
  RFQ_CLOSING_SOON: 'Closing Soon',
  MISSING_VENDOR_LEADS: 'Vendor Leads',
  MISSING_PART_FINDER: 'Part Finder',
  MISSING_SUBMISSION_PACKAGE: 'Submission Package',
  AWARDEE_ENRICHMENT_READY: 'Awardee Enrichment',
  NSN_INTELLIGENCE_REFRESH: 'NSN Intelligence',
}

const FILTERS = [
  ['all', 'All'],
  ['HIGH', 'High'],
  ['QUOTE_FOLLOW_UP_DUE', 'Follow-ups'],
  ['RFQ_CLOSING_SOON', 'Closing Soon'],
  ['MISSING_VENDOR_LEADS', 'Vendor Leads'],
  ['MISSING_PART_FINDER', 'Part Finder'],
]

const formatDate = (value) => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

const compactMeta = (parts) => parts.filter(Boolean).join(' | ')

const queueStatusLabel = (value) => String(value || '').toUpperCase() || 'QUEUED'

export default function WorkQueue() {
  const [filter, setFilter] = useState('all')
  const [backgroundJobId, setBackgroundJobId] = useState(null)
  const [queueTodayResult, setQueueTodayResult] = useState(null)
  const queryClient = useQueryClient()
  const workQueueQuery = useQuery({
    queryKey: ['work-queue-today'],
    queryFn: async () => {
      const res = await api.get('/api/work-queue/today')
      return res.data
    },
    retry: 1,
  })

  const data = workQueueQuery.data || {}
  const items = data.items || []
  const inProgressItems = data.in_progress_items || []
  const recentCompletedItems = data.recent_completed_items || []
  const recentFailedItems = data.recent_failed_items || []
  const summary = data.summary || {}
  const inProgressSummary = data.in_progress_summary || {}
  const backgroundJobQuery = useQuery({
    queryKey: ['work-queue-background-job', backgroundJobId],
    enabled: Boolean(backgroundJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${backgroundJobId}`)
      return res.data
    },
  })
  const refreshQueue = () => {
    queryClient.invalidateQueries({ queryKey: ['work-queue-today'] })
  }
  const runPartFinderMutation = useMutation({
    mutationFn: async (opportunityId) => {
      const res = await api.post(`/api/parts/opportunity/${opportunityId}/refresh`)
      return res.data
    },
    onSuccess: refreshQueue,
  })
  const syncVendorLeadsMutation = useMutation({
    mutationFn: async (opportunityId) => {
      const res = await api.post('/api/vendors/leads/sync', { opportunity_id: Number(opportunityId) })
      return res.data
    },
    onSuccess: refreshQueue,
  })
  const logFollowUpMutation = useMutation({
    mutationFn: async ({ opportunityId, quoteId, companyName }) => {
      const res = await api.post(`/api/vendors/quotes/${quoteId}/follow-up`, {
        opportunity_id: Number(opportunityId),
        notes: `Follow-up logged from Daily Work Queue${companyName ? ` for ${companyName}` : ''}.`,
      })
      return res.data
    },
    onSuccess: refreshQueue,
  })
  const queueBackgroundMutation = useMutation({
    mutationFn: async (item) => {
      const opportunityId = item.opportunity?.id
      if (item.type === 'AWARDEE_ENRICHMENT_READY') {
        const res = await api.post(`/api/opportunities/${opportunityId}/awardee-enrichment-job`, null, {
          params: { force: true },
        })
        return res.data
      }
      if (item.type === 'NSN_INTELLIGENCE_REFRESH' && item.meta?.nsn) {
        const cleanNsn = String(item.meta.nsn || '').replace(/\D+/g, '')
        const res = await api.post(`/api/nsn/${cleanNsn}/build-job`, null, {
          params: {
            run_usaspending: true,
            seed_providers: true,
            limit: 50,
          },
        })
        return res.data
      }
      throw new Error('No background job available for this work item.')
    },
    onSuccess: (job) => {
      setBackgroundJobId(job.id)
    },
  })
  const queueTodayMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/work-queue/queue-today', null, {
        params: { limit: 200 },
      })
      return res.data
    },
    onSuccess: (result) => {
      setQueueTodayResult(result)
      refreshQueue()
      const firstJobId = result?.queued_jobs?.[0]?.job_id
      if (firstJobId) {
        setBackgroundJobId(firstJobId)
      }
    },
  })
  const visibleItems = items.filter((item) => {
    if (filter === 'all') return true
    return item.priority === filter || item.type === filter
  })
  useEffect(() => {
    if (backgroundJobQuery.data?.status === 'success') {
      refreshQueue()
    }
  }, [backgroundJobQuery.data?.status])
  const actionLoading = (item) => {
    if (item.type === 'MISSING_PART_FINDER') return runPartFinderMutation.isPending
    if (item.type === 'MISSING_VENDOR_LEADS') return syncVendorLeadsMutation.isPending
    if (item.type === 'QUOTE_FOLLOW_UP_DUE') return logFollowUpMutation.isPending
    if (item.type === 'AWARDEE_ENRICHMENT_READY' || item.type === 'NSN_INTELLIGENCE_REFRESH') return queueBackgroundMutation.isPending
    return false
  }
  const runItemAction = (item) => {
    const opportunityId = item.opportunity?.id
    if (!opportunityId) return
    if (item.type === 'MISSING_PART_FINDER') {
      runPartFinderMutation.mutate(opportunityId)
    } else if (item.type === 'MISSING_VENDOR_LEADS') {
      syncVendorLeadsMutation.mutate(opportunityId)
    } else if (item.type === 'QUOTE_FOLLOW_UP_DUE' && item.meta?.quote_id) {
      logFollowUpMutation.mutate({
        opportunityId,
        quoteId: item.meta.quote_id,
        companyName: item.meta.company_name || item.meta.cage,
      })
    } else if (item.type === 'AWARDEE_ENRICHMENT_READY' || item.type === 'NSN_INTELLIGENCE_REFRESH') {
      queueBackgroundMutation.mutate(item)
    }
  }
  const directActionLabel = (item) => {
    if (item.type === 'MISSING_PART_FINDER') return 'Run Part Finder'
    if (item.type === 'MISSING_VENDOR_LEADS') return 'Sync Leads'
    if (item.type === 'QUOTE_FOLLOW_UP_DUE') return 'Log Follow-up'
    if (item.type === 'AWARDEE_ENRICHMENT_READY') return 'Queue Award Check'
    if (item.type === 'NSN_INTELLIGENCE_REFRESH') return 'Queue NSN Build'
    return ''
  }

  if (workQueueQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading work queue..." />
        </Card>
      </div>
    )
  }

  if (workQueueQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Work queue unavailable"
          subtitle={workQueueQuery.error.message || 'Failed to load daily work queue.'}
          action={<Button onClick={() => workQueueQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Daily Work Queue</div>
          <h1 className="page-title">Today</h1>
          <div className="page-subtitle">The highest-value actions across quotes, RFQs, vendor research, Part Finder, submissions, and closed solicitations.</div>
        </div>
        <Button onClick={() => queueTodayMutation.mutate()} loading={queueTodayMutation.isPending}>
          Queue Today's Work
        </Button>
        <Button variant="secondary" onClick={() => workQueueQuery.refetch()}>
          Refresh
        </Button>
        <a className="btn btn-secondary btn-sm" href={`${api.defaults.baseURL}/api/export/work_queue.csv`}>
          Export CSV
        </a>
      </div>

      <Card title="Action Filters">
        <div className="quote-follow-up-summary">
          {FILTERS.map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`quote-filter-chip ${filter === value ? 'quote-filter-active' : ''}`}
              onClick={() => setFilter(value)}
            >
              {label} {value === 'all' ? data.total || 0 : summary[value] || 0}
            </button>
          ))}
        </div>
      </Card>

      <Card title="Work Items">
        {queueTodayResult ? (
          <div className="settings-summary-box">
            <div className="row-title">Today's collection work queued</div>
            <div className="row-subtitle">
              Queued {queueTodayResult.queued_count || 0} job{(queueTodayResult.queued_count || 0) === 1 ? '' : 's'}
              {` | `}
              Skipped {queueTodayResult.skipped_duplicate_count || 0} duplicate{(queueTodayResult.skipped_duplicate_count || 0) === 1 ? '' : 's'}
              {` | `}
              From {queueTodayResult.queueable_items || 0} queueable item{(queueTodayResult.queueable_items || 0) === 1 ? '' : 's'}
            </div>
          </div>
        ) : null}
        {visibleItems.length === 0 && inProgressItems.length === 0 && recentCompletedItems.length === 0 && recentFailedItems.length === 0 ? (
          <EmptyState
            title="No work items match this filter"
            subtitle="Try another filter or refresh the queue."
          />
        ) : (
          <div className="work-queue-list">
            {inProgressItems.map((item) => {
              const queueState = item.queue_state || {}
              const status = queueStatusLabel(queueState.status)
              const percent = queueState.progress?.percent
              const isRunning = status === 'RUNNING'
              return (
                <div key={`progress-${item.id}`} className="work-queue-item work-queue-low">
                  <div className="work-queue-item-main">
                    <div className="work-queue-item-header">
                      <Badge label={status} variant={isRunning ? 'warning' : 'info'} />
                      <Badge label={TYPE_LABELS[item.type] || item.type} variant="info" />
                      {isRunning && percent !== undefined ? <span className="row-subtitle">{percent}%</span> : null}
                    </div>
                    <div className="row-title">{item.title}</div>
                    <div className="panel-subtitle">
                      {item.subtitle}
                      {isRunning && queueState.progress?.current_label ? ` | ${queueState.progress.current_label}` : ''}
                      {!isRunning && queueState.created_at ? ` | queued ${formatDate(queueState.created_at)}` : ''}
                    </div>
                    <div className="row-subtitle">
                      {compactMeta([
                        item.opportunity?.source,
                        item.opportunity?.solicitation_number,
                        item.opportunity?.agency,
                      ])}
                    </div>
                  </div>
                  <div className="work-queue-actions">
                    <Link className="btn btn-secondary btn-sm" to={item.action_url}>
                      {item.action_label || 'Open Workspace'}
                    </Link>
                  </div>
                </div>
              )
            })}
            {recentCompletedItems.map((item) => {
              const queueState = item.queue_state || {}
              return (
                <div key={`completed-${item.id}`} className="work-queue-item work-queue-low">
                  <div className="work-queue-item-main">
                    <div className="work-queue-item-header">
                      <Badge label="COMPLETED" variant="success" />
                      <Badge label={TYPE_LABELS[item.type] || item.type} variant="info" />
                      {queueState.completed_at ? <span className="row-subtitle">{formatDate(queueState.completed_at)}</span> : null}
                    </div>
                    <div className="row-title">{item.title}</div>
                    <div className="panel-subtitle">
                      {item.subtitle}
                      {' | recently completed; will return if the opportunity changes'}
                    </div>
                    <div className="row-subtitle">
                      {compactMeta([
                        item.opportunity?.source,
                        item.opportunity?.solicitation_number,
                        item.opportunity?.agency,
                      ])}
                    </div>
                  </div>
                  <div className="work-queue-actions">
                    <Link className="btn btn-secondary btn-sm" to={item.action_url}>
                      {item.action_label || 'Open Workspace'}
                    </Link>
                  </div>
                </div>
              )
            })}
            {recentFailedItems.map((item) => {
              const queueState = item.queue_state || {}
              return (
                <div key={`failed-${item.id}`} className="work-queue-item work-queue-high">
                  <div className="work-queue-item-main">
                    <div className="work-queue-item-header">
                      <Badge label="FAILED" variant="error" />
                      <Badge label={TYPE_LABELS[item.type] || item.type} variant="info" />
                      {queueState.completed_at ? <span className="row-subtitle">{formatDate(queueState.completed_at)}</span> : null}
                    </div>
                    <div className="row-title">{item.title}</div>
                    <div className="panel-subtitle">
                      {item.subtitle}
                      {queueState.error ? ` | ${queueState.error}` : ' | collection job failed; retry when ready'}
                    </div>
                    <div className="row-subtitle">
                      {compactMeta([
                        item.opportunity?.source,
                        item.opportunity?.solicitation_number,
                        item.opportunity?.agency,
                      ])}
                    </div>
                  </div>
                  <div className="work-queue-actions">
                    <Button
                      size="sm"
                      loading={queueBackgroundMutation.isPending}
                      onClick={() => runItemAction(item)}
                    >
                      {directActionLabel(item) || 'Retry'}
                    </Button>
                    <Link className="btn btn-secondary btn-sm" to={item.action_url}>
                      {item.action_label || 'Open Workspace'}
                    </Link>
                  </div>
                </div>
              )
            })}
            {visibleItems.map((item) => (
              <div key={item.id} className={`work-queue-item work-queue-${String(item.priority || '').toLowerCase()}`}>
                <div className="work-queue-item-main">
                  <div className="work-queue-item-header">
                    <Badge label={item.priority} variant={PRIORITY_VARIANT[item.priority] || 'default'} />
                    <Badge label={TYPE_LABELS[item.type] || item.type} variant="info" />
                    {item.due_at ? <span className="row-subtitle">Due {formatDate(item.due_at)}</span> : null}
                  </div>
                  <div className="row-title">{item.title}</div>
                  <div className="panel-subtitle">{item.subtitle}</div>
                  <div className="row-subtitle">
                    {compactMeta([
                      item.opportunity?.source,
                      item.opportunity?.solicitation_number,
                      item.opportunity?.agency,
                    ])}
                  </div>
                </div>
                <div className="work-queue-actions">
                  {directActionLabel(item) ? (
                    <Button
                      size="sm"
                      loading={actionLoading(item)}
                      disabled={item.type === 'QUOTE_FOLLOW_UP_DUE' && !item.meta?.quote_id}
                      onClick={() => runItemAction(item)}
                    >
                      {directActionLabel(item)}
                    </Button>
                  ) : null}
                  <Link className="btn btn-secondary btn-sm" to={item.action_url}>
                    {item.action_label || 'Open Workspace'}
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
