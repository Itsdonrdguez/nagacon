import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useFilters } from '../hooks'
import {
  EmptyState,
  Badge,
  Card,
  Input,
  Button,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  LoadingState,
  StatusPill,
} from '../components/ui'
import { setAsideBadgeVariant, setAsideBadgeLabel } from '../utils/badges'

const PAGE_SIZE_OPTIONS = [25, 50, 100]

const DEFAULT_FILTERS = { source: 'all', setAside: 'all', dueWindow: 'all' }

const formatDueDate = (dueAt) => {
  if (!dueAt) return '-'
  const due = new Date(dueAt)
  const now = new Date()
  const daysLeft = Math.ceil((due - now) / (1000 * 60 * 60 * 24))
  const formatted = due.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

  if (daysLeft < 0) return 'Closed'
  if (daysLeft === 0) return 'Today'
  if (daysLeft === 1) return 'Tomorrow'
  return `${formatted} (${daysLeft}d)`
}

export default function Opportunities() {
  const queryClient = useQueryClient()
  const [sortBy, setSortBy] = useState('due_at')
  const [sortOrder, setSortOrder] = useState('asc')
  const [searchTerm, setSearchTerm] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [nsnFilter, setNsnFilter] = useState('')
  const [submittedNsn, setSubmittedNsn] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const { filters, updateFilter } = useFilters(DEFAULT_FILTERS)

  const opportunitiesQuery = useQuery({
    queryKey: ['opportunities-search', submittedSearch, submittedNsn, filters.source, filters.setAside, filters.dueWindow, sortBy, sortOrder, page, pageSize],
    queryFn: async () => {
      const res = await api.get('/api/opportunities/search', {
        params: {
          page,
          page_size: pageSize,
          q: submittedSearch || undefined,
          nsn: submittedNsn || undefined,
          source: filters.source === 'all' ? undefined : filters.source,
          set_aside_type: filters.setAside === 'all' ? undefined : filters.setAside,
          due_window: filters.dueWindow === 'all' ? undefined : filters.dueWindow,
          sort_by: sortBy,
          sort_order: sortOrder,
        },
      })
      return res.data
    },
    retry: 1,
  })

  const createPipelineMutation = useMutation({
    mutationFn: async (opportunityId) => {
      const res = await api.post(`/api/pipeline/by-opportunity/${opportunityId}`)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunities-search'] })
    },
  })

  const data = opportunitiesQuery.data?.items || []
  const total = opportunitiesQuery.data?.total || 0
  const totalPages = Math.max(Math.ceil(total / pageSize), 1)

  useEffect(() => {
    setPage(1)
  }, [submittedSearch, submittedNsn, filters.source, filters.setAside, filters.dueWindow, sortBy, sortOrder, pageSize])

  const sortedData = useMemo(() => {
    if (sortBy !== 'due_at') {
      return data
    }
    return [...data].sort((a, b) => {
      let aVal = a[sortBy]
      let bVal = b[sortBy]

      if (sortBy === 'due_at') {
        aVal = new Date(aVal || '9999-12-31')
        bVal = new Date(bVal || '9999-12-31')
      }

      if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1
      if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1
      return 0
    })
  }, [data, sortBy, sortOrder])

  const setAsideTypes = useMemo(() => {
    return Array.from(new Set(data.map((opp) => opp.set_aside_type).filter(Boolean))).sort()
  }, [data])

  const toggleSort = (field) => {
    if (sortBy === field) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
      return
    }
    setSortBy(field)
    setSortOrder('asc')
  }

  const handleSearch = (event) => {
    event.preventDefault()
    setSubmittedSearch(searchTerm.trim())
    setSubmittedNsn(nsnFilter.trim())
  }

  const resetFilters = () => {
    setSearchTerm('')
    setSubmittedSearch('')
    setNsnFilter('')
    setSubmittedNsn('')
    setPageSize(25)
    setSortBy('due_at')
    setSortOrder('asc')
    setPage(1)
    updateFilter('source', DEFAULT_FILTERS.source)
    updateFilter('setAside', DEFAULT_FILTERS.setAside)
    updateFilter('dueWindow', DEFAULT_FILTERS.dueWindow)
  }

  const activeFilterSummary = [
    filters.source !== 'all' ? `Source: ${filters.source}` : null,
    filters.setAside !== 'all' ? `Set-Aside: ${filters.setAside === 'none' ? 'No Set-Aside' : filters.setAside}` : null,
    filters.dueWindow !== 'all' ? `Due: ${filters.dueWindow === 'open' ? 'Still Open' : filters.dueWindow === 'closed' ? 'Closed' : `Within ${filters.dueWindow}`}` : null,
    submittedSearch ? `Search: "${submittedSearch}"` : null,
    submittedNsn ? `NSN: ${submittedNsn}` : null,
  ].filter(Boolean)

  const startRecord = total === 0 ? 0 : (page - 1) * pageSize + 1
  const endRecord = Math.min(page * pageSize, total)

  if (opportunitiesQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading opportunities..." />
        </Card>
      </div>
    )
  }

  if (opportunitiesQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Failed to load opportunities"
          subtitle={opportunitiesQuery.error.message || 'Unable to search opportunities.'}
          action={<Button onClick={() => opportunitiesQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Market Feed</div>
          <h1 className="page-title">Opportunities</h1>
          <div className="page-subtitle">Browse, filter, and open solicitation workspaces with a cleaner pipeline-first view.</div>
        </div>
      </div>

      <Card title="Search Opportunities">
        <form className="filters-form" onSubmit={handleSearch}>
          <div className="filters-grid filters-grid-wide">
            <div className="search-input">
              <Input
                label="Keyword"
                type="text"
                placeholder="Search title, agency, solicitation, NAICS, or FSC..."
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
              />
            </div>
            <Input
              label="NSN"
              type="text"
              placeholder="6520-01-123-4567"
              value={nsnFilter}
              onChange={(event) => setNsnFilter(event.target.value)}
            />
            <div className="filter-select">
              <label className="input-label">Source</label>
              <select value={filters.source} onChange={(event) => updateFilter('source', event.target.value)}>
                <option value="all">All Sources</option>
                <option value="SAM">SAM</option>
                <option value="DIBBS">DIBBS</option>
              </select>
            </div>
            <div className="filter-select">
              <label className="input-label">Set-Aside</label>
              <select value={filters.setAside} onChange={(event) => updateFilter('setAside', event.target.value)}>
                <option value="all">All Set-Asides</option>
                <option value="none">No Set-Aside</option>
                {setAsideTypes.map((type) => (
                  <option key={type} value={type}>{type}</option>
                ))}
              </select>
            </div>
            <div className="filter-select">
              <label className="input-label">Due Date</label>
              <select value={filters.dueWindow} onChange={(event) => updateFilter('dueWindow', event.target.value)}>
                <option value="all">Any Due Date</option>
                <option value="7d">Due in 7 Days</option>
                <option value="30d">Due in 30 Days</option>
                <option value="open">Still Open</option>
                <option value="closed">Closed</option>
              </select>
            </div>
            <div className="form-action">
              <Button type="submit">Search</Button>
            </div>
          </div>
        </form>

        <div className="results-toolbar">
          <div className="results-count">
            Showing {startRecord}-{endRecord} of {total}
            {submittedSearch ? ` for "${submittedSearch}"` : ''}
          </div>
          <div className="page-size-control">
            <label className="input-label" htmlFor="page_size">Rows</label>
            <select id="page_size" value={pageSize} onChange={(event) => setPageSize(Number(event.target.value))}>
              {PAGE_SIZE_OPTIONS.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="panel-subtitle">
          Dataset view: {filters.source === 'all' ? 'all sources' : filters.source} | {filters.dueWindow === 'all' ? 'any due date' : filters.dueWindow === 'open' ? 'still open only' : filters.dueWindow === 'closed' ? 'closed only' : `due in ${filters.dueWindow}`}
        </div>
        <div className="results-toolbar">
          <div className="badge-stack">
            {activeFilterSummary.length === 0 ? (
              <Badge label="No extra filters applied" variant="default" />
            ) : (
              activeFilterSummary.map((item) => (
                <Badge key={item} label={item} variant="info" />
              ))
            )}
          </div>
          <Button variant="secondary" onClick={resetFilters}>Reset Filters</Button>
        </div>
      </Card>

      <Card title="Opportunities">
        {sortedData.length === 0 ? (
          <EmptyState title="No matching opportunities" subtitle="Try a broader search or adjust your filters." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead sortable sortDirection={sortBy === 'solicitation_number' ? sortOrder : null} onSort={() => toggleSort('solicitation_number')}>
                  Title / NSN
                </TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Agency</TableHead>
                <TableHead>Set-Aside</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>NAICS/FSC</TableHead>
                <TableHead sortable sortDirection={sortBy === 'due_at' ? sortOrder : null} onSort={() => toggleSort('due_at')}>
                  Due Date
                </TableHead>
                <TableHead>Workspace</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedData.map((opp) => (
                <TableRow key={opp.id}>
                  <TableCell>
                    <div className="row-title">{opp.display_title || opp.title}</div>
                    <div className="row-subtitle">{opp.solicitation_number || 'Solicitation unavailable'}</div>
                  </TableCell>
                  <TableCell>
                    <Badge label={opp.source} variant={opp.source === 'SAM' ? 'success' : 'info'} />
                  </TableCell>
                  <TableCell className="agency-cell">{opp.agency || '-'}</TableCell>
                  <TableCell>
                    {opp.set_aside_type ? (
                      <Badge label={setAsideBadgeLabel(opp.set_aside_type)} variant={setAsideBadgeVariant(opp.set_aside_type)} />
                    ) : (
                      <span className="text-muted">Open</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <StatusPill status={opp.solicitation_status || 'OPEN'} />
                  </TableCell>
                  <TableCell>{opp.naics_code || opp.fsc_code || '-'}</TableCell>
                  <TableCell className="due-date-cell">
                    <span className={opp.due_at ? 'due-date' : ''}>{formatDueDate(opp.due_at)}</span>
                  </TableCell>
                  <TableCell>
                    <div className="table-action-stack">
                      <Link className="action-btn-small" to={`/workspace/${opp.id}`}>Open</Link>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={createPipelineMutation.isPending}
                        disabled={(opp.solicitation_status || '').toUpperCase() === 'CLOSED'}
                        onClick={() => createPipelineMutation.mutate(opp.id)}
                      >
                        {(opp.solicitation_status || '').toUpperCase() === 'CLOSED' ? 'Research Only' : 'Create Workspace'}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}

        <div className="pagination-bar">
          <Button variant="secondary" disabled={page <= 1} onClick={() => setPage((current) => Math.max(current - 1, 1))}>
            Previous
          </Button>
          <div className="panel-subtitle">Page {page} of {totalPages}</div>
          <Button variant="secondary" disabled={page >= totalPages} onClick={() => setPage((current) => Math.min(current + 1, totalPages))}>
            Next
          </Button>
        </div>
      </Card>
    </div>
  )
}
