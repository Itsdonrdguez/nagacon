import { Link } from 'react-router-dom'
import { useState } from 'react'
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

export default function WorkQueue() {
  const [filter, setFilter] = useState('all')
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
  const summary = data.summary || {}
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
  const visibleItems = items.filter((item) => {
    if (filter === 'all') return true
    return item.priority === filter || item.type === filter
  })
  const actionLoading = (item) => {
    if (item.type === 'MISSING_PART_FINDER') return runPartFinderMutation.isPending
    if (item.type === 'MISSING_VENDOR_LEADS') return syncVendorLeadsMutation.isPending
    if (item.type === 'QUOTE_FOLLOW_UP_DUE') return logFollowUpMutation.isPending
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
    }
  }
  const directActionLabel = (item) => {
    if (item.type === 'MISSING_PART_FINDER') return 'Run Part Finder'
    if (item.type === 'MISSING_VENDOR_LEADS') return 'Sync Leads'
    if (item.type === 'QUOTE_FOLLOW_UP_DUE') return 'Log Follow-up'
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
        <Button variant="secondary" onClick={() => workQueueQuery.refetch()}>
          Refresh
        </Button>
        <a className="btn btn-secondary btn-sm" href={`${api.defaults.baseURL}/api/export/work_queue.csv`}>
          Export CSV
        </a>
      </div>

      <div className="stats-grid">
        <Card className="work-queue-stat">
          <div className="stat-label">Total Actions</div>
          <div className="stat-value">{data.total || 0}</div>
          <div className="stat-subtitle">Generated {formatDate(data.generated_at)}</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">High Priority</div>
          <div className="stat-value">{summary.HIGH || 0}</div>
          <div className="stat-subtitle">Follow these first</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Quote Follow-ups</div>
          <div className="stat-value">{summary.QUOTE_FOLLOW_UP_DUE || 0}</div>
          <div className="stat-subtitle">Vendor action needed</div>
        </Card>
        <Card className="work-queue-stat">
          <div className="stat-label">Closing Soon</div>
          <div className="stat-value">{summary.RFQ_CLOSING_SOON || 0}</div>
          <div className="stat-subtitle">Deadline pressure</div>
        </Card>
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
        {visibleItems.length === 0 ? (
          <EmptyState
            title="No work items match this filter"
            subtitle="Try another filter or refresh the queue."
          />
        ) : (
          <div className="work-queue-list">
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
