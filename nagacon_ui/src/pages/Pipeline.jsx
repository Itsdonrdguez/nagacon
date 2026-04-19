import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, Button, Card, EmptyState, Input, LoadingState, StatusPill } from '../components/ui'
import { setAsideBadgeLabel, setAsideBadgeVariant } from '../utils/badges'

const STATUSES = ['NEW', 'IN_PROGRESS', 'BID', 'NO_BID', 'SUBMITTED']

const formatDueDate = (dueAt) => {
  if (!dueAt) return 'No due date'
  const due = new Date(dueAt)
  const now = new Date()
  if (Number.isNaN(due.getTime())) return 'No due date'
  if (due < now) return 'Closed'
  return due.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Pipeline() {
  const [searchTerm, setSearchTerm] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [source, setSource] = useState('all')
  const [includeClosed, setIncludeClosed] = useState(false)

  const boardQuery = useQuery({
    queryKey: ['pipeline-board', submittedSearch, source, includeClosed],
    queryFn: async () => {
      const res = await api.get('/api/pipeline/board', {
        params: {
          q: submittedSearch || undefined,
          source: source === 'all' ? undefined : source,
          include_closed: includeClosed,
          limit: 200,
        },
      })
      return res.data
    },
    retry: 1,
  })

  const grouped = useMemo(() => {
    const base = Object.fromEntries(STATUSES.map((status) => [status, []]))
    const items = boardQuery.data?.items || []
    items.forEach((item) => {
      const key = item.decision_status || 'NEW'
      if (!base[key]) {
        base[key] = []
      }
      base[key].push(item)
    })
    return base
  }, [boardQuery.data])

  const handleSearch = (event) => {
    event.preventDefault()
    setSubmittedSearch(searchTerm.trim())
  }

  if (boardQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading pipeline..." />
        </Card>
      </div>
    )
  }

  if (boardQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Pipeline unavailable"
          subtitle={boardQuery.error.message || 'Unable to load the pipeline board.'}
          action={<Button onClick={() => boardQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  const total = boardQuery.data?.total || 0
  const summary = boardQuery.data?.summary || {}

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Execution Board</div>
          <h1 className="page-title">Pipeline</h1>
          <div className="page-subtitle">See active bid motion by stage, owner, and source without losing track of closed research items.</div>
        </div>
      </div>

      <Card title="Pipeline Filters">
        <form className="filters-form" onSubmit={handleSearch}>
          <div className="filters-grid">
            <div className="search-input">
              <Input
                type="text"
                placeholder="Search title, solicitation, agency, or owner..."
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
              />
            </div>
            <div className="filter-select">
              <select value={source} onChange={(event) => setSource(event.target.value)}>
                <option value="all">All Sources</option>
                <option value="SAM">SAM</option>
                <option value="DIBBS">DIBBS</option>
              </select>
            </div>
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={includeClosed}
                onChange={(event) => setIncludeClosed(event.target.checked)}
              />
              Include closed
            </label>
            <div className="results-count">Tracking {total} workspace records</div>
            <div className="form-action">
              <Button type="submit">Search</Button>
            </div>
          </div>
        </form>
      </Card>

      <div className="stats-grid pipeline-stats-grid">
        {STATUSES.map((status) => (
          <Card key={status}>
            <div className="stat-label">{status.replace('_', ' ')}</div>
            <div className="stat-value">{summary[status] || 0}</div>
            <div className="stat-subtitle">Pipeline items</div>
          </Card>
        ))}
      </div>

      {total === 0 ? (
        <EmptyState
          title="No pipeline items yet"
          subtitle="Create workspace records from the opportunities page to start managing your bid pipeline."
          action={<Link className="action-btn-small" to="/opportunities">Browse opportunities</Link>}
        />
      ) : (
        <div className="pipeline-board">
          {STATUSES.map((status) => (
            <Card key={status} title={`${status.replace('_', ' ')} (${grouped[status]?.length || 0})`}>
              <div className="pipeline-column">
                {(grouped[status] || []).length === 0 ? (
                  <div className="panel-subtitle">No items in this stage.</div>
                ) : (
                  grouped[status].map((item) => (
                    <Link key={item.id} to={`/workspace/${item.opportunity_id}`} className="pipeline-card-link">
                      <div className="pipeline-card">
                        <div className="pipeline-card-header">
                          <Badge label={item.opportunity.source} variant={item.opportunity.source === 'SAM' ? 'success' : 'info'} />
                          <StatusPill status={item.priority || 'Normal'} />
                        </div>
                        <div className="pipeline-card-header">
                          <StatusPill status={item.opportunity.solicitation_status || 'OPEN'} />
                        </div>
                        <div className="pipeline-card-title">
                          {item.opportunity.display_title || item.opportunity.title}
                        </div>
                        <div className="row-subtitle">
                          {item.opportunity.solicitation_number || 'Solicitation unavailable'}
                        </div>
                        <div className="pipeline-card-meta">
                          <span>{item.opportunity.agency || 'Agency unavailable'}</span>
                          <span>Due: {formatDueDate(item.opportunity.due_at)}</span>
                        </div>
                        <div className="pipeline-card-footer">
                          <span>Owner: {item.owner || 'Unassigned'}</span>
                          {item.opportunity.set_aside_type ? (
                            <Badge
                              label={setAsideBadgeLabel(item.opportunity.set_aside_type)}
                              variant={setAsideBadgeVariant(item.opportunity.set_aside_type)}
                            />
                          ) : null}
                        </div>
                      </div>
                    </Link>
                  ))
                )}
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
