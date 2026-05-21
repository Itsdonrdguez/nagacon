import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { useFilters } from '../hooks'
import {
  EmptyState,
  Badge,
  Card,
  StatCard,
  Input,
  Button,
  MultiSelect,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
  LoadingState,
  StatusPill,
} from '../components/ui'
import { setAsideBadgeVariant, setAsideBadgeLabel, setAsideOptionLabel } from '../utils/badges'
import { FSC_CODE_OPTIONS, NAICS_CODE_OPTIONS, withCustomOptions } from '../data/codeCatalogs'

const PAGE_SIZE_OPTIONS = [25, 50, 100]

const DEFAULT_FILTERS = { source: 'all', setAside: 'all', dueWindow: 'open' }

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

const formatAwardDate = (value) => {
  if (!value) return null
  return new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

const opportunitySignalLabel = (opp) => {
  if (opp?.requested_quantity_display) return opp.requested_quantity_display
  if (opp?.opportunity_lifecycle === 'ARCHIVED') return 'Archive record'
  if (opp?.award_intelligence_status === 'ACTIVE_RFQ') return null
  const status = opp?.award_intelligence_status
  if (status === 'READY_FOR_USASPENDING_CHECK') return 'Award follow-up due'
  if (status === 'AWAITING_USASPENDING') return 'Awaiting USAspending'
  if (status === 'USASPENDING_CONFIRMED') return 'Award evidence found'
  return null
}

export default function Opportunities() {
  const queryClient = useQueryClient()
  const [sortBy, setSortBy] = useState('due_at')
  const [sortOrder, setSortOrder] = useState('asc')
  const [searchTerm, setSearchTerm] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const [nsnFilter, setNsnFilter] = useState('')
  const [submittedNsn, setSubmittedNsn] = useState('')
  const [agencyFilter, setAgencyFilter] = useState('')
  const [submittedAgency, setSubmittedAgency] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [submittedState, setSubmittedState] = useState('')
  const [fscCodesFilter, setFscCodesFilter] = useState([])
  const [submittedFscCodes, setSubmittedFscCodes] = useState([])
  const [naicsCodesFilter, setNaicsCodesFilter] = useState([])
  const [submittedNaicsCodes, setSubmittedNaicsCodes] = useState([])
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(25)
  const [awardJobId, setAwardJobId] = useState(null)
  const [selectedOpportunityIds, setSelectedOpportunityIds] = useState([])
  const [bulkPrepareResult, setBulkPrepareResult] = useState(null)
  const { filters, updateFilter } = useFilters(DEFAULT_FILTERS)
  const fscCodeOptions = useMemo(
    () => withCustomOptions(FSC_CODE_OPTIONS, [...fscCodesFilter, ...submittedFscCodes], 'fsc'),
    [fscCodesFilter, submittedFscCodes],
  )
  const naicsCodeOptions = useMemo(
    () => withCustomOptions(NAICS_CODE_OPTIONS, [...naicsCodesFilter, ...submittedNaicsCodes], 'naics'),
    [naicsCodesFilter, submittedNaicsCodes],
  )
  const filterOptionsQuery = useQuery({
    queryKey: ['opportunity-filter-options'],
    queryFn: async () => {
      const res = await api.get('/api/opportunities/filters')
      return res.data
    },
    staleTime: 5 * 60 * 1000,
  })

  const opportunitiesQuery = useQuery({
    queryKey: ['opportunities-search', submittedSearch, submittedNsn, submittedAgency, submittedState, submittedFscCodes.join(','), submittedNaicsCodes.join(','), filters.source, filters.setAside, filters.dueWindow, sortBy, sortOrder, page, pageSize],
    queryFn: async () => {
      const res = await api.get('/api/opportunities/search', {
        params: {
          page,
          page_size: pageSize,
          q: submittedSearch || undefined,
          nsn: submittedNsn || undefined,
          agency: submittedAgency || undefined,
          state: submittedState || undefined,
          fsc_codes: submittedFscCodes.length ? submittedFscCodes.join(',') : undefined,
          naics_codes: submittedNaicsCodes.length ? submittedNaicsCodes.join(',') : undefined,
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

  const awardEnrichmentMutation = useMutation({
    mutationFn: async ({ opportunityId, force = false }) => {
      const res = await api.post(`/api/opportunities/${opportunityId}/awardee-enrichment-job`, null, {
        params: { force },
      })
      return res.data
    },
    onSuccess: (job) => {
      setAwardJobId(job.id)
      queryClient.invalidateQueries({ queryKey: ['opportunities-search'] })
    },
  })

  const bulkPrepareMutation = useMutation({
    mutationFn: async (opportunityIds) => {
      const res = await api.post('/api/opportunities/bulk/workspace-intake', {
        opportunity_ids: opportunityIds,
        download_documents: true,
        run_usaspending: true,
      })
      return res.data
    },
    onSuccess: (result) => {
      setBulkPrepareResult(result)
      setSelectedOpportunityIds([])
      queryClient.invalidateQueries({ queryKey: ['opportunities-search'] })
      queryClient.invalidateQueries({ queryKey: ['work-queue-today'] })
    },
  })

  const awardJobQuery = useQuery({
    queryKey: ['awardee-enrichment-job', awardJobId],
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${awardJobId}`)
      return res.data
    },
    enabled: Boolean(awardJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
  })

  const data = opportunitiesQuery.data?.items || []
  const total = opportunitiesQuery.data?.total || 0
  const totalPages = Math.max(Math.ceil(total / pageSize), 1)
  const selectableIds = useMemo(
    () => data.filter((opp) => opp.opportunity_lifecycle !== 'ARCHIVED').map((opp) => opp.id),
    [data],
  )
  const allSelectableSelected = selectableIds.length > 0 && selectableIds.every((id) => selectedOpportunityIds.includes(id))
  const hasSelection = selectedOpportunityIds.length > 0
  useEffect(() => {
    setPage(1)
  }, [submittedSearch, submittedNsn, submittedAgency, submittedState, submittedFscCodes, submittedNaicsCodes, filters.source, filters.setAside, filters.dueWindow, sortBy, sortOrder, pageSize])

  useEffect(() => {
    setSelectedOpportunityIds((current) => current.filter((id) => data.some((opp) => opp.id === id)))
  }, [data])

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

  const sourceOptions = filterOptionsQuery.data?.sources?.length ? filterOptionsQuery.data.sources : ['SAM', 'DIBBS']
  const setAsideCategories = filterOptionsQuery.data?.set_aside_categories || []
  const exactSetAsideTypes = filterOptionsQuery.data?.set_asides || []
  const exactSetAsideLabels = filterOptionsQuery.data?.set_aside_exact_labels || []
  const statusOptions = filterOptionsQuery.data?.status_filters?.length
    ? filterOptionsQuery.data.status_filters
    : [
        { value: 'open', label: 'Active' },
        { value: '7d', label: 'Closing Soon' },
        { value: '30d', label: 'Due in 30 Days' },
        { value: 'closed', label: 'Closed / Intelligence' },
        { value: 'recently_closed', label: 'Recently Closed' },
        { value: 'archived', label: 'Archived' },
        { value: 'award_followup', label: 'Award Follow-Up Due' },
        { value: 'all', label: 'All Records' },
      ]

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
    setSubmittedAgency(agencyFilter.trim())
    setSubmittedState(stateFilter.trim())
    setSubmittedFscCodes(fscCodesFilter)
    setSubmittedNaicsCodes(naicsCodesFilter)
  }

  const resetFilters = () => {
    setSearchTerm('')
    setSubmittedSearch('')
    setNsnFilter('')
    setSubmittedNsn('')
    setAgencyFilter('')
    setSubmittedAgency('')
    setStateFilter('')
    setSubmittedState('')
    setFscCodesFilter([])
    setSubmittedFscCodes([])
    setNaicsCodesFilter([])
    setSubmittedNaicsCodes([])
    setPageSize(25)
    setSortBy('due_at')
    setSortOrder('asc')
    setPage(1)
    updateFilter('source', DEFAULT_FILTERS.source)
    updateFilter('setAside', DEFAULT_FILTERS.setAside)
    updateFilter('dueWindow', DEFAULT_FILTERS.dueWindow)
  }

  const toggleOpportunitySelection = (opportunityId) => {
    setSelectedOpportunityIds((current) => (
      current.includes(opportunityId)
        ? current.filter((id) => id !== opportunityId)
        : [...current, opportunityId]
    ))
  }

  const toggleSelectAllOnPage = () => {
    if (allSelectableSelected) {
      setSelectedOpportunityIds((current) => current.filter((id) => !selectableIds.includes(id)))
      return
    }
    setSelectedOpportunityIds((current) => Array.from(new Set([...current, ...selectableIds])))
  }

  const activeFilterSummary = [
    filters.source !== 'all' ? `Source: ${filters.source}` : null,
    filters.setAside !== 'all' ? `Set-Aside: ${filters.setAside === 'none' ? 'No Set-Aside' : filters.setAside}` : null,
    filters.dueWindow !== 'all' ? `Status: ${statusOptions.find((item) => item.value === filters.dueWindow)?.label || filters.dueWindow}` : null,
    submittedSearch ? `Search: "${submittedSearch}"` : null,
    submittedNsn ? `NSN: ${submittedNsn}` : null,
    submittedAgency ? `Agency: ${submittedAgency}` : null,
    submittedState ? `State: ${submittedState}` : null,
    submittedFscCodes.length ? `FSC: ${submittedFscCodes.join(', ')}` : null,
    submittedNaicsCodes.length ? `NAICS: ${submittedNaicsCodes.join(', ')}` : null,
  ].filter(Boolean)

  const startRecord = total === 0 ? 0 : (page - 1) * pageSize + 1
  const endRecord = Math.min(page * pageSize, total)
  const summaryStats = useMemo(() => {
    const now = new Date()
    const dueSoonCount = sortedData.filter((opp) => {
      if (!opp.due_at || opp.solicitation_status === 'CLOSED') return false
      const due = new Date(opp.due_at)
      const days = Math.ceil((due - now) / (1000 * 60 * 60 * 24))
      return days >= 0 && days <= 7
    }).length
    const workspaceReadyCount = sortedData.filter((opp) => opp.has_workspace).length
    const closedIntelligenceCount = sortedData.filter((opp) => opp.solicitation_status === 'CLOSED' || opp.opportunity_lifecycle === 'ARCHIVED').length
    const needsResearchCount = sortedData.filter((opp) => !opp.has_workspace && opp.opportunity_lifecycle !== 'ARCHIVED').length
    return [
      { label: 'Needs Research', value: needsResearchCount, subtitle: 'No workspace footprint yet' },
      { label: 'Workspace Ready', value: workspaceReadyCount, subtitle: 'Prep evidence already exists' },
      { label: 'Due Soon', value: dueSoonCount, subtitle: 'Closing within 7 days' },
      { label: 'Closed Intelligence', value: closedIntelligenceCount, subtitle: 'Source for pricing and vendor learning' },
    ]
  }, [sortedData])
  const exportOpportunitiesUrl = useMemo(() => {
    const params = new URLSearchParams()
    if (submittedSearch) params.set('q', submittedSearch)
    if (submittedNsn) params.set('nsn', submittedNsn)
    if (submittedAgency) params.set('agency', submittedAgency)
    if (submittedState) params.set('state', submittedState)
    if (submittedFscCodes.length) params.set('fsc_codes', submittedFscCodes.join(','))
    if (submittedNaicsCodes.length) params.set('naics_codes', submittedNaicsCodes.join(','))
    if (filters.source !== 'all') params.set('source', filters.source)
    if (filters.setAside !== 'all') params.set('set_aside_type', filters.setAside)
    if (filters.dueWindow !== 'all') params.set('due_window', filters.dueWindow)
    const query = params.toString()
    return `${api.defaults.baseURL}/api/export/opportunities.csv${query ? `?${query}` : ''}`
  }, [
    submittedSearch,
    submittedNsn,
    submittedAgency,
    submittedState,
    submittedFscCodes,
    submittedNaicsCodes,
    filters.source,
    filters.setAside,
    filters.dueWindow,
  ])

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
          <div className="page-kicker">Operator Intake</div>
          <h1 className="page-title">Opportunities</h1>
          <div className="page-subtitle">Triage new work, move prepared solicitations into workspace processing, and keep closed records available for intelligence and pricing reuse.</div>
        </div>
        <a className="btn btn-secondary btn-sm" href={exportOpportunitiesUrl} target="_blank" rel="noreferrer">
          Export Opportunities CSV
        </a>
      </div>

      <div className="stats-grid">
        {summaryStats.map((stat) => (
          <StatCard key={stat.label} label={stat.label} value={stat.value} subtitle={stat.subtitle} />
        ))}
      </div>

      <Card title="Find and Triage" className="opportunity-search-card">
        <div className="panel-subtitle">
          Use keyword search for broad matching, then narrow with exact FSC or NAICS filters when you want a cleaner result set.
        </div>
        <form className="filters-form" onSubmit={handleSearch}>
          <div className="filters-grid filters-grid-wide opportunity-filters-grid">
            <div className="search-input filter-span-2">
              <Input
                label="Keyword Search"
                type="text"
                placeholder="Search title, agency, solicitation, NAICS, or FSC..."
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
                helperText="Broad search across the opportunity record."
              />
            </div>
            <Input
              label="NSN"
              type="text"
              placeholder="6520-01-123-4567"
              value={nsnFilter}
              onChange={(event) => setNsnFilter(event.target.value)}
              helperText="Best for DIBBS item lookups."
            />
            <Input
              label="Agency"
              type="text"
              placeholder="VA, Army, GSA..."
              value={agencyFilter}
              onChange={(event) => setAgencyFilter(event.target.value)}
              helperText="Matches buying agency text."
            />
            <Input
              label="State / POP"
              type="text"
              placeholder="TX, CA, Virginia..."
              value={stateFilter}
              onChange={(event) => setStateFilter(event.target.value)}
              helperText="Filters place of performance text."
            />
            <MultiSelect
              label="FSC Codes"
              value={fscCodesFilter}
              options={fscCodeOptions}
              onChange={setFscCodesFilter}
              placeholder="Search FSC codes"
              helperText="Exact FSC matches. You can select more than one."
              allowCustom
              customTypeLabel="FSC code"
              normalizeValue={(item) => String(item || '').replace(/\D/g, '').slice(0, 4)}
            />
            <MultiSelect
              label="NAICS Codes"
              value={naicsCodesFilter}
              options={naicsCodeOptions}
              onChange={setNaicsCodesFilter}
              placeholder="Search NAICS codes"
              helperText="Exact NAICS matches. You can select more than one."
              allowCustom
              customTypeLabel="NAICS code"
              normalizeValue={(item) => String(item || '').replace(/\D/g, '').slice(0, 6)}
            />
            <div className="filter-select">
              <label className="input-label">Source</label>
              <select value={filters.source} onChange={(event) => updateFilter('source', event.target.value)}>
                <option value="all">All Sources</option>
                {sourceOptions.map((source) => (
                  <option key={source} value={source}>{source}</option>
                ))}
              </select>
              <span className="input-helper-text">Choose DIBBS, SAM, or both.</span>
            </div>
            <div className="filter-select">
              <label className="input-label">Set-Aside</label>
              <select value={filters.setAside} onChange={(event) => updateFilter('setAside', event.target.value)}>
                <option value="all">All Set-Asides</option>
                {setAsideCategories.map((type) => (
                  <option key={type.value} value={type.value}>{type.label}</option>
                ))}
                {exactSetAsideTypes.length ? <option disabled>Exact labels</option> : null}
                {(exactSetAsideLabels.length ? exactSetAsideLabels : exactSetAsideTypes.map((type) => ({ value: type, label: setAsideOptionLabel(type) }))).map((type) => (
                  <option key={`exact-${type.value}`} value={type.value}>{type.label}</option>
                ))}
              </select>
              <span className="input-helper-text">Use category filters first, then exact labels if needed.</span>
            </div>
            <div className="filter-select">
              <label className="input-label">Status</label>
              <select value={filters.dueWindow} onChange={(event) => updateFilter('dueWindow', event.target.value)}>
                {statusOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
              <span className="input-helper-text">Limits by active, closing soon, or closed records.</span>
            </div>
            <div className="form-action opportunity-filter-action">
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
          Dataset view: {filters.source === 'all' ? 'all sources' : filters.source} | {filters.dueWindow === 'all' ? 'all records' : statusOptions.find((item) => item.value === filters.dueWindow)?.label || filters.dueWindow}
        </div>
        {awardJobId ? (
          <div className="search-progress-box">
            <div className="search-progress-header">
              <div>
                <div className="row-title">Awardee enrichment</div>
                <div className="row-subtitle">
                  {awardJobQuery.data?.progress?.current_label || awardJobQuery.data?.status || 'Queued'}
                </div>
              </div>
              <strong>{awardJobQuery.data?.progress?.percent || 0}%</strong>
            </div>
            <div className="search-progress-track">
              <div className="search-progress-fill" style={{ width: `${awardJobQuery.data?.progress?.percent || 0}%` }} />
            </div>
            {awardJobQuery.data?.status === 'failed' ? (
              <div className="row-subtitle text-danger">{awardJobQuery.data?.error || 'Awardee enrichment failed.'}</div>
            ) : null}
            {awardJobQuery.data?.status === 'success' ? (
              <div className="row-subtitle">Awardees promoted: {awardJobQuery.data?.result?.promoted_awardees?.promoted || 0}</div>
            ) : null}
          </div>
        ) : null}
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

      <Card title="Opportunities" className="opportunity-results-card">
        {bulkPrepareResult ? (
          <div className="settings-summary-box">
            <div className="row-title">Workspace preparation queued</div>
            <div className="row-subtitle">
              Queued {bulkPrepareResult.queued_count || 0}
              {` | `}
              Already running {bulkPrepareResult.skipped_duplicate_count || 0}
              {` | `}
              Archived skipped {bulkPrepareResult.archived_skip_count || 0}
            </div>
            <div className="panel-subtitle">
              Those jobs now show up in <Link to="/work-queue">Today</Link> while the prep runs.
            </div>
          </div>
        ) : null}
        <div className="opportunity-bulk-toolbar">
          <div>
            <div className="row-title">Safe workspace processing</div>
            <div className="row-subtitle">
              Select opportunities on this page and queue full workspace preparation, including documents, Part Finder, vendor leads, and workspace artifacts.
            </div>
          </div>
          <div className="opportunity-bulk-toolbar-actions">
            <Badge label={hasSelection ? `${selectedOpportunityIds.length} selected` : 'No selection'} variant={hasSelection ? 'info' : 'default'} />
            <Button
              variant="secondary"
              onClick={() => setSelectedOpportunityIds([])}
              disabled={!hasSelection}
            >
              Clear
            </Button>
            <Button
              onClick={() => bulkPrepareMutation.mutate(selectedOpportunityIds)}
              disabled={!hasSelection}
              loading={bulkPrepareMutation.isPending}
            >
              Prepare Selected Workspaces
            </Button>
          </div>
        </div>
        {sortedData.length === 0 ? (
          <EmptyState title="No matching opportunities" subtitle="Try a broader search or adjust your filters." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="opportunity-select-column">
                  <input
                    type="checkbox"
                    aria-label="Select all opportunities on this page"
                    checked={allSelectableSelected}
                    onChange={toggleSelectAllOnPage}
                  />
                </TableHead>
                <TableHead sortable sortDirection={sortBy === 'solicitation_number' ? sortOrder : null} onSort={() => toggleSort('solicitation_number')}>
                  Title / NSN
                </TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Agency</TableHead>
                <TableHead>Set-Aside</TableHead>
                <TableHead>Signal</TableHead>
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
                  <TableCell className="opportunity-select-column">
                    <input
                      type="checkbox"
                      aria-label={`Select opportunity ${opp.solicitation_number || opp.id}`}
                      checked={selectedOpportunityIds.includes(opp.id)}
                      disabled={opp.opportunity_lifecycle === 'ARCHIVED'}
                      onChange={() => toggleOpportunitySelection(opp.id)}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="row-title">{opp.display_title || opp.title}</div>
                    <div className="row-subtitle">
                      {opp.solicitation_number || 'Solicitation unavailable'}
                      {opp.workflow_label ? ` | ${opp.workflow_label}` : ''}
                      {opportunitySignalLabel(opp) ? ` | ${opportunitySignalLabel(opp)}` : ''}
                    </div>
                    {opp.source === 'SAM' && (opp.prepared_summary || (opp.prepared_risk_flags || []).length) ? (
                      <div className="row-subtitle">
                        {opp.prepared_summary || 'Prepared summary available'}
                        {(opp.prepared_risk_flags || []).length ? ` | ${opp.prepared_risk_flags.length} risk flag${opp.prepared_risk_flags.length === 1 ? '' : 's'}` : ''}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <Badge label={opp.source} variant={opp.source === 'SAM' ? 'success' : 'info'} />
                  </TableCell>
                  <TableCell className="agency-cell">{opp.agency || '-'}</TableCell>
                  <TableCell>
                    {opp.set_aside_type ? (
                      <Badge label={setAsideBadgeLabel(opp.set_aside_type)} variant={setAsideBadgeVariant(opp.set_aside_type)} />
                    ) : (
                      <span className="text-muted">Full/Open</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="workspace-action-column">
                      <StatusPill status={opp.solicitation_status || 'OPEN'} />
                      {opp.decision_status ? <StatusPill status={opp.decision_status} /> : null}
                      {opp.pipeline_owner ? <div className="row-subtitle">Owner: {opp.pipeline_owner}</div> : null}
                    </div>
                  </TableCell>
                  <TableCell>{opp.naics_code || opp.fsc_code || '-'}</TableCell>
                  <TableCell className="due-date-cell">
                    <span className={opp.due_at ? 'due-date' : ''}>{formatDueDate(opp.due_at)}</span>
                    {opp.target_submit_date ? (
                      <div className="row-subtitle">Target submit: {formatAwardDate(opp.target_submit_date)}</div>
                    ) : null}
                    {opp.solicitation_status === 'CLOSED' ? (
                      <div className="row-subtitle">
                        {opp.days_since_close ?? 0}d closed
                        {opp.award_expected_after ? ` | Check after ${formatAwardDate(opp.award_expected_after)}` : ''}
                      </div>
                    ) : null}
                  </TableCell>
                  <TableCell>
                    <div className="table-action-stack">
                      <Link className="action-btn-small" to={`/workspace/${opp.id}`}>
                        {opp.opportunity_lifecycle === 'ARCHIVED' ? 'Open Archive' : 'Open'}
                      </Link>
                      {opp.opportunity_lifecycle !== 'ARCHIVED' ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={createPipelineMutation.isPending}
                          disabled={opp.bid_eligible === false}
                          onClick={() => createPipelineMutation.mutate(opp.id)}
                        >
                          {opp.bid_eligible === false ? 'Research Only' : (opp.has_workspace ? 'Prepare Workspace' : 'Create Workspace')}
                        </Button>
                      ) : null}
                      {opp.solicitation_status === 'CLOSED' && opp.opportunity_lifecycle !== 'ARCHIVED' ? (
                        <Button
                          size="sm"
                          variant={opp.award_follow_up_eligible ? 'primary' : 'secondary'}
                          loading={awardEnrichmentMutation.isPending}
                          onClick={() => awardEnrichmentMutation.mutate({ opportunityId: opp.id, force: opp.award_follow_up_eligible })}
                        >
                          {opp.award_follow_up_eligible ? 'Run Award Follow-Up' : 'Refresh Award Leads'}
                        </Button>
                      ) : null}
                      {opp.opportunity_lifecycle === 'ARCHIVED' && opp.url ? (
                        <a className="btn btn-secondary btn-sm" href={opp.url} target="_blank" rel="noreferrer">
                          Source Link
                        </a>
                      ) : null}
                    </div>
                    {opp.opportunity_lifecycle === 'ARCHIVED' ? (
                      <div className="row-subtitle">Archive view keeps the source link, documents, and extracted intelligence without active queue actions.</div>
                    ) : opp.bid_eligible === false ? (
                      <div className="row-subtitle">Use for pricing, sourcing, and future RFQs.</div>
                    ) : null}
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
