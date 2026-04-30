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
  QUOTE_FOLLOW_UP_DUE: 'Quote Chase',
  QUOTE_REQUESTED_NO_RESPONSE: 'Awaiting Quote',
  RFQ_CLOSING_SOON: 'Due Soon',
  MISSING_VENDOR_LEADS: 'Sourcing',
  MISSING_PART_FINDER: 'NSN Intelligence',
  RFQ_NOT_SENT: 'Supplier Outreach',
  READY_TO_SUBMIT: 'Package Prep',
  MISSING_SUBMISSION_PACKAGE: 'Submission Prep',
  AWARDEE_ENRICHMENT_READY: 'Closed Intelligence',
  NSN_INTELLIGENCE_REFRESH: 'NSN Intelligence',
  SAM_CHECKLIST_MISSING: 'Proposal Setup',
  SAM_COMPLIANCE_MATRIX_MISSING: 'Compliance Review',
  SAM_CO_EMAIL_MISSING: 'CO Outreach',
  SAM_TARGET_SUBMIT_DATE_MISSING: 'Proposal Setup',
  SAM_TASKS_NOT_SEEDED: 'Proposal Setup',
  SAM_OPEN_TASKS_MISSING: 'Proposal Review',
  SAM_SUBMISSION_PACKAGE_MISSING: 'Submission Prep',
  DIBBS_RFQ_PACKAGE_MISSING: 'RFQ Package',
}

const FILTERS = [
  ['all', 'All'],
  ['due_soon', 'Due Soon'],
  ['needs_suppliers', 'Needs Suppliers'],
  ['rfq_not_sent', 'RFQ Not Sent'],
  ['follow_up_due', 'Follow-up Due'],
  ['ready_to_submit', 'Ready to Submit'],
  ['submission_prep', 'Submission Prep'],
  ['closed_intelligence', 'Closed Intelligence'],
  ['failed', 'Failed'],
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
  READY_TO_SUBMIT: 1,
  RFQ_NOT_SENT: 2,
  MISSING_VENDOR_LEADS: 3,
  MISSING_PART_FINDER: 4,
  NSN_INTELLIGENCE_REFRESH: 5,
  DIBBS_RFQ_PACKAGE_MISSING: 6,
  RFQ_CLOSING_SOON: 7,
  MISSING_SUBMISSION_PACKAGE: 8,
  QUOTE_REQUESTED_NO_RESPONSE: 9,
  AWARDEE_ENRICHMENT_READY: 10,
}

const PRIMARY_ACTIONS = {
  QUOTE_FOLLOW_UP_DUE: {
    heading: 'Send follow-up',
    detail: 'RFQ outreach has gone quiet and the follow-up window has passed.',
  },
  QUOTE_REQUESTED_NO_RESPONSE: {
    heading: 'Check quote progress',
    detail: 'A quote request has been sent, but the response is still missing.',
  },
  RFQ_CLOSING_SOON: {
    heading: 'Review the due date now',
    detail: 'This opportunity is approaching its deadline and needs a decision on the next move.',
  },
  MISSING_VENDOR_LEADS: {
    heading: 'Find suppliers',
    detail: 'No usable supplier candidates are attached yet, so sourcing is the best next move.',
  },
  MISSING_PART_FINDER: {
    heading: 'Build NSN intelligence',
    detail: 'The item still needs part and source intelligence before supplier outreach will be reliable.',
  },
  RFQ_NOT_SENT: {
    heading: 'Open RFQ draft',
    detail: 'Suppliers exist, but RFQ outreach has not been sent yet.',
  },
  READY_TO_SUBMIT: {
    heading: 'Prepare submission package',
    detail: 'A usable quote exists, and the package can move toward submission.',
  },
  MISSING_SUBMISSION_PACKAGE: {
    heading: 'Prepare package',
    detail: 'The operational pieces are in motion, but the package is not assembled yet.',
  },
  AWARDEE_ENRICHMENT_READY: {
    heading: 'Review closed intelligence',
    detail: 'This closed solicitation can sharpen future vendor and awardee research.',
  },
  NSN_INTELLIGENCE_REFRESH: {
    heading: 'Open NSN intelligence',
    detail: 'This NSN still needs a saved intelligence record before sourcing is complete.',
  },
  SAM_CHECKLIST_MISSING: {
    heading: 'Start win strategy review',
    detail: 'This SAM workspace still needs the basic proposal setup work before it can move cleanly.',
  },
  SAM_COMPLIANCE_MATRIX_MISSING: {
    heading: 'Build the compliance matrix',
    detail: 'Submission requirements still need to be captured into a usable review matrix.',
  },
  SAM_CO_EMAIL_MISSING: {
    heading: 'Draft contracting officer outreach',
    detail: 'There is no saved contracting officer draft yet for this SAM opportunity.',
  },
  SAM_TARGET_SUBMIT_DATE_MISSING: {
    heading: 'Set the target submit date',
    detail: 'Proposal tracking exists, but the internal target submit date is still missing.',
  },
  SAM_TASKS_NOT_SEEDED: {
    heading: 'Set up the proposal plan',
    detail: 'The workspace still needs the core planning steps that move the pursuit into execution.',
  },
  SAM_OPEN_TASKS_MISSING: {
    heading: 'Add active proposal steps',
    detail: 'The proposal is active, but there are no open work items driving it forward.',
  },
  SAM_SUBMISSION_PACKAGE_MISSING: {
    heading: 'Build the submission package',
    detail: 'Proposal work is active, but the final submission package has not been assembled yet.',
  },
  DIBBS_RFQ_PACKAGE_MISSING: {
    heading: 'Download the RFQ package',
    detail: 'The RFQ package is still missing, so the sourcing team cannot review the actual requirements yet.',
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

function buildWorkspaceUrl(item, tab = '') {
  const oppId = item?.opportunity?.id
  if (!oppId) return '/work-queue'
  const params = new URLSearchParams()
  if (tab) params.set('tab', tab)
  const query = params.toString()
  return `/workspace/${oppId}${query ? `?${query}` : ''}`
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

function missionBucket(item) {
  const explicit = String(item?.mission_bucket || '').trim()
  if (explicit) return explicit
  const type = String(item?.type || '').toUpperCase()
  if (type === 'RFQ_CLOSING_SOON') return 'due_soon'
  if (['MISSING_VENDOR_LEADS', 'MISSING_PART_FINDER', 'NSN_INTELLIGENCE_REFRESH'].includes(type)) return 'needs_suppliers'
  if (type === 'RFQ_NOT_SENT') return 'rfq_not_sent'
  if (['QUOTE_FOLLOW_UP_DUE', 'QUOTE_REQUESTED_NO_RESPONSE'].includes(type)) return 'follow_up_due'
  if (type === 'READY_TO_SUBMIT') return 'ready_to_submit'
  if (['MISSING_SUBMISSION_PACKAGE', 'SAM_CHECKLIST_MISSING', 'SAM_COMPLIANCE_MATRIX_MISSING', 'SAM_CO_EMAIL_MISSING', 'SAM_TARGET_SUBMIT_DATE_MISSING', 'SAM_TASKS_NOT_SEEDED', 'SAM_OPEN_TASKS_MISSING', 'SAM_SUBMISSION_PACKAGE_MISSING', 'DIBBS_RFQ_PACKAGE_MISSING'].includes(type)) return 'submission_prep'
  if (type === 'AWARDEE_ENRICHMENT_READY') return 'closed_intelligence'
  return 'manual_review'
}

function missionBucketLabel(bucket) {
  const labels = {
    due_soon: 'Due Soon',
    needs_suppliers: 'Needs Suppliers',
    rfq_not_sent: 'RFQ Not Sent',
    follow_up_due: 'Follow-up Due',
    ready_to_submit: 'Ready to Submit',
    submission_prep: 'Submission Prep',
    closed_intelligence: 'Closed Intelligence',
    failed: 'Failed',
    manual_review: 'Manual Review',
  }
  return labels[bucket] || 'Manual Review'
}

function recommendedActionLink(item) {
  if (!item) return { to: item?.action_url || '/work-queue', label: 'Open Workspace' }
  if (item.type === 'MISSING_VENDOR_LEADS') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Find Suppliers' }
  }
  if (item.type === 'MISSING_PART_FINDER') {
    return { to: buildNsnIntelligenceUrl(item, 'lookup'), label: 'Analyze NSN' }
  }
  if (item.type === 'NSN_INTELLIGENCE_REFRESH') {
    return { to: buildNsnIntelligenceUrl(item, 'build'), label: 'Open NSN Intelligence' }
  }
  if (item.type === 'RFQ_NOT_SENT') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Open RFQ Draft' }
  }
  if (item.type === 'READY_TO_SUBMIT') {
    return { to: buildWorkspaceUrl(item, 'submission-package'), label: 'Open Submission Package' }
  }
  if (item.type === 'RFQ_CLOSING_SOON') {
    return { to: buildWorkspaceUrl(item), label: 'Review Opportunity' }
  }
  if (item.type === 'MISSING_SUBMISSION_PACKAGE') {
    return { to: buildWorkspaceUrl(item, 'submission-package'), label: 'Prepare Package' }
  }
  if (item.type === 'QUOTE_REQUESTED_NO_RESPONSE') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Review Quote Progress' }
  }
  if (item.type === 'QUOTE_FOLLOW_UP_DUE') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Send Follow-up' }
  }
  if (item.type === 'DIBBS_RFQ_PACKAGE_MISSING') {
    return { to: buildWorkspaceUrl(item, 'rfq-package'), label: 'Open RFQ Package' }
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
  const recentCompletedItems = data.recent_completed_items || []
  const recentFailedItems = data.recent_failed_items || []
  const summary = data.summary || {}
  const inProgressSummary = data.in_progress_summary || {}
  const collectionSummary = data.collection_summary || {}
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
  const groupedVisibleItems = useMemo(() => groupActionItems(items), [items])
  const missionCards = useMemo(() => {
    const cards = []

    for (const item of inProgressItems) {
      cards.push({
        kind: 'job',
        filterKey: missionBucket(item),
        statusLabel: String(item.display_status || queueStatusLabel(item.queue_state?.status)).toUpperCase(),
        bucketLabel: missionBucketLabel(missionBucket(item)),
        item,
      })
    }

    for (const item of recentFailedItems) {
      cards.push({
        kind: 'failed',
        filterKey: 'failed',
        statusLabel: 'FAILED',
        bucketLabel: 'Failed',
        item,
      })
    }

    for (const group of groupedVisibleItems) {
      const primary = group.primary
      const filterKey = missionBucket(primary)
      cards.push({
        kind: filterKey === 'closed_intelligence' ? 'closed' : 'group',
        filterKey,
        statusLabel: String(primary.display_status || 'OPEN').toUpperCase(),
        bucketLabel: missionBucketLabel(filterKey),
        item: primary,
        group,
      })
    }

    return cards
  }, [groupedVisibleItems, inProgressItems, recentFailedItems])

  const filterCounts = useMemo(() => {
    const counts = { all: missionCards.length }
    for (const card of missionCards) {
      counts[card.filterKey] = (counts[card.filterKey] || 0) + 1
    }
    return counts
  }, [missionCards])

  const visibleCards = useMemo(() => {
    if (filter === 'all') return missionCards
    return missionCards.filter((card) => card.filterKey === filter)
  }, [missionCards, filter])

  const spotlightStats = useMemo(() => ([
    { key: 'all', label: 'Open Actions', value: filterCounts.all || 0, subtitle: 'Items needing work today' },
    { key: 'due_soon', label: 'Due Soon', value: filterCounts.due_soon || 0, subtitle: 'Due within 7 days' },
    { key: 'needs_suppliers', label: 'Needs Suppliers', value: filterCounts.needs_suppliers || 0, subtitle: 'No usable supplier yet' },
    { key: 'rfq_not_sent', label: 'RFQs Not Sent', value: filterCounts.rfq_not_sent || 0, subtitle: 'Suppliers found, outreach pending' },
    { key: 'follow_up_due', label: 'Follow-ups Due', value: filterCounts.follow_up_due || 0, subtitle: 'Quotes not received yet' },
    { key: 'ready_to_submit', label: 'Ready to Submit', value: filterCounts.ready_to_submit || 0, subtitle: 'Quote received and package pending' },
  ]), [filterCounts])
  useEffect(() => {
    if (backgroundJobQuery.data?.status === 'success') {
      refreshQueue()
    }
  }, [backgroundJobQuery.data?.status])
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
            Queue Work
          </Button>
          <Button variant="secondary" onClick={() => workQueueQuery.refetch()}>
            Refresh Status
          </Button>
          <a className="btn btn-secondary btn-sm" href={`${api.defaults.baseURL}/api/export/work_queue.csv`}>
            Export CSV
          </a>
        </div>
      </div>

      <div className="stats-grid">
        {spotlightStats.map((stat) => (
          <button
            key={stat.label}
            type="button"
            className="card stat-card work-queue-stat"
            onClick={() => setFilter(stat.key)}
          >
            <div className="stat-label">{stat.label}</div>
            <div className="stat-value">{stat.value}</div>
            <div className="stat-subtitle">{stat.subtitle}</div>
          </button>
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
              {label} {filterCounts[value] || 0}
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
        {(collectionSummary.tracked_total || backgroundJobQuery.data || queueTodayResult) ? (
          <div className="settings-summary-box">
            <div className="row-title">Collection Activity</div>
            <div className="row-subtitle">
              Queued {collectionSummary.queued || 0}
              {` | `}
              Running {collectionSummary.running || 0}
              {` | `}
              Completed {collectionSummary.completed || 0}
              {` | `}
              Failed {collectionSummary.failed || 0}
              {` | `}
              Skipped {queueTodayResult?.skipped_duplicate_count || 0}
            </div>
            {backgroundJobQuery.data ? (
              <div className="panel-subtitle">
                Latest queued job: {String(backgroundJobQuery.data.status || '').toUpperCase() || 'QUEUED'}
                {backgroundJobQuery.data.progress?.current_label ? ` | ${backgroundJobQuery.data.progress.current_label}` : ''}
                {backgroundJobQuery.data.progress?.percent !== undefined ? ` | ${backgroundJobQuery.data.progress.percent}%` : ''}
              </div>
            ) : null}
          </div>
        ) : null}
        {visibleCards.length === 0 ? (
          <EmptyState
            title="No work items match this filter"
            subtitle="Try another filter or refresh the queue."
          />
        ) : (
          <div className="work-queue-list">
            {visibleCards.map((card, index) => {
              const item = card.item
              const queueState = item.queue_state || {}
              const actionMeta = primaryActionMeta(item)
              const recommendedAction = recommendedActionLink(item)
              const isRunning = String(card.statusLabel || '').toUpperCase() === 'RUNNING'
              const progress = queueState.progress?.percent
              const group = card.group
              const contextTitle = group?.opportunity?.title || item.opportunity?.title || item.title
              const contextMeta = compactMeta([
                item.opportunity?.source,
                item.meta?.nsn,
                item.opportunity?.solicitation_number,
                item.opportunity?.agency,
                item.meta?.company_name,
              ])
              const explanation = [
                item.subtitle,
                isRunning && queueState.progress?.current_label ? queueState.progress.current_label : '',
                card.kind === 'failed' ? (queueState.error || 'Collection job failed and needs attention.') : '',
              ].filter(Boolean).join(' | ')
              const secondaryText = group?.additionalItems?.length
                ? `Also needs attention: ${group.additionalItems.map((entry) => TYPE_LABELS[entry.type] || entry.type).join(', ')}.`
                : ''
              return (
                <div key={`${card.kind}-${item.id}-${index}`} className={`work-queue-item work-queue-${String(item.priority || '').toLowerCase()} work-queue-item-spotlight`}>
                  <div className="work-queue-item-main">
                    <div className="work-queue-item-header">
                      <Badge label={card.statusLabel} variant={card.kind === 'failed' ? 'error' : (isRunning ? 'warning' : (PRIORITY_VARIANT[item.priority] || 'default'))} />
                      <Badge label={card.bucketLabel} variant="info" />
                      <Badge label={TYPE_LABELS[item.type] || item.type} variant="default" />
                      {item.due_at ? <span className="row-subtitle">Due {formatDate(item.due_at)}</span> : null}
                      {isRunning && progress !== undefined ? <span className="row-subtitle">{progress}%</span> : null}
                    </div>
                    <div className="row-title">{contextTitle}</div>
                    <div className="panel-subtitle">{explanation || actionMeta.detail}</div>
                    <div className="row-subtitle">{contextMeta}</div>
                    <div className="work-queue-next-step">
                      <div className="row-title">{actionMeta.heading}</div>
                      <div className="panel-subtitle">{actionMeta.detail}</div>
                    </div>
                    {secondaryText ? <div className="panel-subtitle">{secondaryText}</div> : null}
                  </div>
                  <div className="work-queue-actions">
                    <Link className="btn btn-sm" to={recommendedAction.to}>
                      {recommendedAction.label}
                    </Link>
                    {card.kind === 'failed' && queueBackgroundMutation.isPending === false && ['AWARDEE_ENRICHMENT_READY', 'NSN_INTELLIGENCE_REFRESH'].includes(item.type) ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => queueBackgroundMutation.mutate(item)}
                      >
                        Retry Job
                      </Button>
                    ) : null}
                    <Link className="row-subtitle" to={item.action_url}>
                      Open workspace
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
