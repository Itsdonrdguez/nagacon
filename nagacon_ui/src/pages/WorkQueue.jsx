import { Link } from 'react-router-dom'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
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
  const visibleItems = items.filter((item) => {
    if (filter === 'all') return true
    return item.priority === filter || item.type === filter
  })

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
                <Link className="btn btn-secondary btn-sm" to={item.action_url}>
                  {item.action_label || 'Open Workspace'}
                </Link>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}
