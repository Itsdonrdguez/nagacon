import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
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

const ACTION_RANK = {
  QUOTE_FOLLOW_UP_DUE: 0,
  RFQ_CLOSING_SOON: 1,
  MISSING_VENDOR_LEADS: 2,
  MISSING_PART_FINDER: 3,
  MISSING_SUBMISSION_PACKAGE: 4,
  AWARDEE_ENRICHMENT_READY: 5,
  NSN_INTELLIGENCE_REFRESH: 6,
  QUOTE_REQUESTED_NO_RESPONSE: 7,
}

const READINESS_LABELS = {
  RFQ_CLOSING_SOON: 'Review due timing',
  QUOTE_FOLLOW_UP_DUE: 'Vendor response needed',
  QUOTE_REQUESTED_NO_RESPONSE: 'Quote still pending',
  MISSING_VENDOR_LEADS: 'Vendor research missing',
  MISSING_PART_FINDER: 'Part research missing',
  MISSING_SUBMISSION_PACKAGE: 'Submission package missing',
  AWARDEE_ENRICHMENT_READY: 'Closed item ready for enrichment',
  NSN_INTELLIGENCE_REFRESH: 'NSN intelligence missing',
}

const PRIMARY_ACTIONS = {
  QUOTE_FOLLOW_UP_DUE: {
    heading: 'Follow up with vendor',
    detail: 'A quote follow-up is due now. Log the outreach so the queue stops treating this like a waiting item.',
  },
  QUOTE_REQUESTED_NO_RESPONSE: {
    heading: 'Check quote progress',
    detail: 'A quote request exists, but no response is logged yet.',
  },
  RFQ_CLOSING_SOON: {
    heading: 'Review the RFQ now',
    detail: 'This solicitation is closing soon. Confirm the bid path before the window gets tighter.',
  },
  MISSING_VENDOR_LEADS: {
    heading: 'Find vendor leads',
    detail: 'There are no vendor leads attached yet, so vendor research is the best next move.',
  },
  MISSING_PART_FINDER: {
    heading: 'Run Part Finder',
    detail: 'This NSN has not been researched with Part Finder yet.',
  },
  MISSING_SUBMISSION_PACKAGE: {
    heading: 'Prepare the submission package',
    detail: 'Quote work exists, but the submission package has not been assembled yet.',
  },
  AWARDEE_ENRICHMENT_READY: {
    heading: 'Enrich the closed award',
    detail: 'This closed solicitation can improve vendor and award history for future bids.',
  },
  NSN_INTELLIGENCE_REFRESH: {
    heading: 'Build NSN intelligence',
    detail: 'This NSN still needs a saved intelligence record.',
  },
}

function buildVendorResearchUrl(item) {
  const params = new URLSearchParams()
  params.set('source', 'today')
  params.set('opportunity_id', String(item.opportunity?.id || ''))
  if (item.meta?.title || item.opportunity?.title) params.set('title', item.meta?.title || item.opportunity?.title)
  if (item.meta?.agency || item.opportunity?.agency) params.set('agency', item.meta?.agency || item.opportunity?.agency)
  if (item.opportunity?.solicitation_number) params.set('sol', item.opportunity.solicitation_number)
  if (item.meta?.nsn) params.set('nsn', item.meta.nsn)
  if (item.meta?.fsc || item.opportunity?.fsc) params.set('fsc', item.meta?.fsc || item.opportunity?.fsc)
  if (item.meta?.title || item.opportunity?.title) params.set('q', item.meta?.title || item.opportunity?.title)
  return `/vendors?${params.toString()}`
}

function buildNsnIntelligenceUrl(item, mode = 'lookup') {
  const params = new URLSearchParams()
  params.set('source', 'today')
  params.set('mode', mode)
  params.set('opportunity_id', String(item.opportunity?.id || ''))
  if (item.opportunity?.solicitation_number) params.set('sol', item.opportunity.solicitation_number)
  if (item.opportunity?.title) params.set('title', item.opportunity.title)
  if (item.meta?.nsn) params.set('nsn', item.meta.nsn)
  return `/nsn-intelligence?${params.toString()}`
}

function recommendedActionLink(item) {
  if (!item) return { to: item?.action_url || '/work-queue', label: 'Open Workspace' }
  if (item.type === 'MISSING_VENDOR_LEADS') {
    return { to: buildVendorResearchUrl(item), label: 'Start Vendor Research' }
  }
  if (item.type === 'MISSING_PART_FINDER') {
    return { to: buildNsnIntelligenceUrl(item, 'lookup'), label: 'Analyze This NSN' }
  }
  if (item.type === 'NSN_INTELLIGENCE_REFRESH') {
    return { to: buildNsnIntelligenceUrl(item, 'build'), label: 'Open NSN Intelligence' }
  }
  if (item.type === 'RFQ_CLOSING_SOON') {
    return { to: item.action_url, label: 'Review RFQ' }
  }
  if (item.type === 'MISSING_SUBMISSION_PACKAGE') {
    return { to: item.action_url, label: 'Prepare Submission' }
  }
  if (item.type === 'QUOTE_REQUESTED_NO_RESPONSE') {
    return { to: item.action_url, label: 'Review Quote Progress' }
  }
  if (item.type === 'AWARDEE_ENRICHMENT_READY') {
    return { to: item.action_url, label: 'Review Closed Intelligence' }
  }
  return { to: item.action_url, label: item.action_label || 'Open Workspace' }
}

function groupActionItems(items) {
  const groups = new Map()
  for (const item of items) {
    const oppId = item.opportunity?.id || item.id
    const current = groups.get(oppId) || {
      opportunity: item.opportunity,
      items: [],
    }
    current.items.push(item)
    groups.set(oppId, current)
  }
  return Array.from(groups.values())
    .map((group) => {
      const sorted = [...group.items].sort((a, b) => {
        const priorityOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
        const priorityGap = (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9)
        if (priorityGap !== 0) return priorityGap
        return (ACTION_RANK[a.type] ?? 99) - (ACTION_RANK[b.type] ?? 99)
      })
      const primary = sorted[0]
      return {
        ...group,
        primary,
        additionalItems: sorted.slice(1),
      }
    })
    .sort((a, b) => {
      const priorityOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
      const primaryGap = (priorityOrder[a.primary?.priority] ?? 9) - (priorityOrder[b.primary?.priority] ?? 9)
      if (primaryGap !== 0) return primaryGap
      return (a.primary?.due_at || '9999').localeCompare(b.primary?.due_at || '9999')
    })
}

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
  const groupedVisibleItems = useMemo(() => groupActionItems(visibleItems), [visibleItems])
  const spotlightStats = useMemo(() => ([
    { label: 'Total Actions', value: data.total || 0, subtitle: "Open items in today's queue" },
    { label: 'High Priority', value: summary.HIGH || 0, subtitle: 'Needs attention first' },
    { label: 'Closing Soon', value: summary.RFQ_CLOSING_SOON || 0, subtitle: 'Solicitations nearing deadline' },
    { label: 'Vendor Leads', value: summary.MISSING_VENDOR_LEADS || 0, subtitle: 'Items still missing vendor coverage' },
  ]), [data.total, summary])
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
  const primaryActionMeta = (item) => PRIMARY_ACTIONS[item?.type] || {
    heading: item?.action_label || 'Open workspace',
    detail: item?.subtitle || 'Open the workspace and continue the next step.',
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
          <div className="page-kicker">Mission Control</div>
          <h1 className="page-title">Today</h1>
          <div className="page-subtitle">Start with the next best action for each opportunity instead of sorting through a raw queue by hand.</div>
        </div>
        <div className="company-form-actions">
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
      </div>

      <div className="stats-grid">
        {spotlightStats.map((stat) => (
          <Card key={stat.label} className="stat-card work-queue-stat">
            <div className="stat-label">{stat.label}</div>
            <div className="stat-value">{stat.value}</div>
            <div className="stat-subtitle">{stat.subtitle}</div>
          </Card>
        ))}
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

      <Card title="Recommended Next Steps">
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
        {groupedVisibleItems.length === 0 && inProgressItems.length === 0 && recentFailedItems.length === 0 ? (
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
            {groupedVisibleItems.map((group) => {
              const item = group.primary
              const actionMeta = primaryActionMeta(item)
              const recommendedAction = recommendedActionLink(item)
              const supportingLabels = [item.type, ...group.additionalItems.map((entry) => entry.type)]
              return (
                <div key={group.opportunity?.id || item.id} className={`work-queue-item work-queue-${String(item.priority || '').toLowerCase()} work-queue-item-spotlight`}>
                  <div className="work-queue-item-main">
                    <div className="work-queue-item-header">
                      <Badge label={item.priority} variant={PRIORITY_VARIANT[item.priority] || 'default'} />
                      <Badge label={READINESS_LABELS[item.type] || TYPE_LABELS[item.type] || item.type} variant="info" />
                      {item.due_at ? <span className="row-subtitle">Due {formatDate(item.due_at)}</span> : null}
                    </div>
                    <div className="row-title">{group.opportunity?.title || item.title}</div>
                    <div className="row-subtitle">
                      {compactMeta([
                        group.opportunity?.source,
                        group.opportunity?.solicitation_number,
                        group.opportunity?.agency,
                      ])}
                    </div>
                    <div className="work-queue-next-step">
                      <div className="row-title">{actionMeta.heading}</div>
                      <div className="panel-subtitle">{actionMeta.detail}</div>
                    </div>
                    <div className="work-queue-signal-list">
                      {supportingLabels.map((type) => (
                        <span key={`${group.opportunity?.id}-${type}`} className="ingest-code-pill">
                          {TYPE_LABELS[type] || type}
                        </span>
                      ))}
                    </div>
                    {group.additionalItems.length > 0 ? (
                      <div className="panel-subtitle">
                        Also needs attention: {group.additionalItems.map((entry) => TYPE_LABELS[entry.type] || entry.type).join(', ')}.
                      </div>
                    ) : null}
                  </div>
                  <div className="work-queue-actions">
                    <Link className="btn btn-sm" to={recommendedAction.to}>
                      {recommendedAction.label}
                    </Link>
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
                      Open Workspace
                    </Link>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
