import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Button, EmptyState, Input, StatusPill } from '../components/ui'

const DEFAULT_DIBBS_FSC_CODES = ['6520', '8470', '6550', '5805', '5130', '5810', '5998', '5999', '1095', '6110', '6515']
const DEFAULT_MANUAL_DIBBS_FSC = DEFAULT_DIBBS_FSC_CODES[0]
const DEFAULT_PER_CODE_SEARCH_SIZE = 25

function totalResult(result) {
  if (!result) return { inserted: 0, updated: 0, skipped: 0, errors: [] }
  if (result.results) {
    const dibbs = result.results.dibbs || {}
    const sam = result.results.sam || {}
    return {
      inserted: Number(dibbs.inserted || 0) + Number(sam.inserted || 0),
      updated: Number(dibbs.updated || 0) + Number(sam.updated || 0),
      skipped: Number(dibbs.skipped || 0) + Number(sam.skipped || 0),
      errors: [...(dibbs.errors || []), ...(sam.errors || [])],
    }
  }
  return result
}

function resultSources(result) {
  if (!result) return {}
  if (result.results) return result.results
  return result.sources || {}
}

function resultPlan(result) {
  if (!result) return null
  return result.plan || null
}

function SearchCoverage({ diagnostics, codeLabel }) {
  if (!diagnostics) return null

  const usedCodes = diagnostics.used_codes || []
  const codeResults = diagnostics.code_results || []
  const queryResults = diagnostics.queries || []

  return (
    <div className="ingest-coverage">
      {usedCodes.length > 0 ? (
        <div className="ingest-code-breakdown" aria-label={codeLabel}>
          {usedCodes.map((code) => (
            <span key={`${codeLabel}-${code}`} className="ingest-code-pill">{code}</span>
          ))}
        </div>
      ) : null}
      <div className="ingest-result-row">
        <span>Source records found</span>
        <strong>{diagnostics.raw_rows ?? 0}</strong>
      </div>
      {codeResults.length > 0 ? (
        <div className="ingest-code-breakdown">
          {codeResults.map((item) => (
            <div key={`${codeLabel}-result-${item.code}`} className="ingest-code-pill">
              <span>{item.code}</span>
              <strong>{item.raw_rows ?? 0}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {queryResults.length > 0 ? (
        <div className="ingest-query-list">
          {queryResults.slice(0, 4).map((item, index) => (
            <div key={`query-${index}`} className="ingest-query-line">
              <strong>{item.query?.title || item.query?.ncode || item.query?.ccode || `Search ${index + 1}`}</strong>
              <span>{item.naics_filtered_rows ?? item.raw_rows ?? 0} matched</span>
            </div>
          ))}
          {queryResults.length > 4 ? <div className="row-subtitle">+ {queryResults.length - 4} more searches</div> : null}
        </div>
      ) : null}
    </div>
  )
}

function SourceResult({ label, result }) {
  if (!result) return null
  const codeLabel = label === 'SAM' ? 'SAM Targeting' : 'DIBBS FSC Codes'
  const foundCount = result.diagnostics?.raw_rows ?? 0

  return (
    <div className="ingest-source-card">
      <div>
        <div className="row-title">{label}</div>
        <div className="row-subtitle">
          {foundCount > 0 ? `${foundCount} source record${foundCount === 1 ? '' : 's'} reviewed` : 'No source records matched this run'}
        </div>
      </div>
      <div className="ingest-result-row">
        <span>New opportunities</span>
        <StatusPill status={String(result.inserted ?? 0)} />
      </div>
      <div className="ingest-result-row">
        <span>Refreshed</span>
        <StatusPill status={String(result.updated ?? 0)} />
      </div>
      <div className="ingest-result-row">
        <span>Already current</span>
        <StatusPill status={String(result.skipped ?? 0)} />
      </div>
      <SearchCoverage diagnostics={result.diagnostics} codeLabel={codeLabel} />
      {(result.errors || []).length > 0 ? (
        <div className="ingest-errors">
          {(result.errors || []).map((error, index) => (
            <div key={`${label}-error-${index}`} className="form-error">{error}</div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

export default function Ingestion() {
  const queryClient = useQueryClient()
  const [query, setQuery] = useState(DEFAULT_MANUAL_DIBBS_FSC)
  const [source, setSource] = useState('DIBBS')
  const [samState, setSamState] = useState('')
  const [samZip, setSamZip] = useState('')
  const [samAgency, setSamAgency] = useState('')
  const [activeJobId, setActiveJobId] = useState(null)

  const refreshOpportunityFeeds = () => {
    queryClient.invalidateQueries({ queryKey: ['opportunities'] })
    queryClient.invalidateQueries({ queryKey: ['opportunities-search'] })
    queryClient.invalidateQueries({ queryKey: ['dashboard-opps'] })
    queryClient.invalidateQueries({ queryKey: ['pipeline-board'] })
  }

  const ingestPlanQuery = useQuery({
    queryKey: ['company-ingest-plan'],
    queryFn: async () => {
      const res = await api.get('/api/company/ingest-plan')
      return res.data
    },
  })

  const ingestMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/search-jobs', { kind: 'manual', search: payload })
      return res.data
    },
    onSuccess: (data) => {
      setActiveJobId(data.id)
      refreshOpportunityFeeds()
    },
  })

  const pdfDownloadMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/search-jobs', { kind: 'dibbs_pdf_bulk_download', ...payload })
      return res.data
    },
    onSuccess: (data) => {
      setActiveJobId(data.id)
      queryClient.invalidateQueries({ queryKey: ['company-ingest-plan'] })
    },
  })

  const profileIngestMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/search-jobs', { kind: 'profile', quick: true })
      return res.data
    },
    onSuccess: (data) => {
      setActiveJobId(data.id)
      refreshOpportunityFeeds()
      queryClient.invalidateQueries({ queryKey: ['company-ingest-plan'] })
    },
  })

  const searchJobQuery = useQuery({
    queryKey: ['search-job', activeJobId],
    enabled: Boolean(activeJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${activeJobId}`)
      return res.data
    },
  })

  useEffect(() => {
    if (searchJobQuery.data?.status !== 'success') {
      return
    }
    refreshOpportunityFeeds()
    queryClient.invalidateQueries({ queryKey: ['company-ingest-plan'] })
  }, [searchJobQuery.data?.status, searchJobQuery.data?.completed_at])

  const runManualSearch = async ({ limit = DEFAULT_PER_CODE_SEARCH_SIZE, deep = false } = {}) => {
    await ingestMutation.mutateAsync({
      q: query.trim(),
      per_code_limit: limit,
      limit_mode: deep ? 'all' : 'per_code',
      max_pages: deep ? 999 : 4,
      sources: source === 'ALL' ? ['SAM', 'DIBBS'] : [source],
      sam_state: source !== 'DIBBS' ? samState.trim() : undefined,
      sam_zip: source !== 'DIBBS' ? samZip.trim() : undefined,
      sam_agency: source !== 'DIBBS' ? samAgency.trim() : undefined,
    })
  }

  const runBulkPdfDownload = async () => {
    await pdfDownloadMutation.mutateAsync({
      fscs: query.trim(),
    })
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    await runManualSearch({ limit: DEFAULT_PER_CODE_SEARCH_SIZE })
  }

  const handleSourceChange = (nextSource) => {
    setSource(nextSource)
    if (nextSource === 'DIBBS' && !query.trim()) {
      setQuery(DEFAULT_MANUAL_DIBBS_FSC)
    }
  }

  const runProfileIngest = async () => {
    await profileIngestMutation.mutateAsync()
  }

  const activeJob = searchJobQuery.data || pdfDownloadMutation.data || profileIngestMutation.data || ingestMutation.data
  const isPdfDownloadJob = activeJob?.kind === 'dibbs_pdf_bulk_download'
  const isSearching = activeJob?.status === 'queued' || activeJob?.status === 'running'
  const result = activeJob?.result
  const resultTotals = totalResult(result)
  const sources = resultSources(result)
  const plan = resultPlan(result) || ingestPlanQuery.data
  const helperText =
    source === 'DIBBS'
      ? `Enter one or more DLA FSC codes. The search checks up to ${DEFAULT_PER_CODE_SEARCH_SIZE} records per FSC.`
      : source === 'SAM'
        ? `Enter SAM NAICS, PSC, or classification codes separated by commas. The search checks up to ${DEFAULT_PER_CODE_SEARCH_SIZE} records per code.`
        : `Use this for a combined manual run. DIBBS uses FSC codes; SAM uses NAICS/PSC/classification codes. The search checks up to ${DEFAULT_PER_CODE_SEARCH_SIZE} records per code.`
  const showSamFilters = source !== 'DIBBS'

  return (
    <div className="page">
      <h1 className="page-title">Opportunity Search</h1>

      <div className="ingestion-grid">
        <Card title="Company Profile Search">
          <div className="ingest-command-card">
            <p className="panel-subtitle">
              Uses your saved DIBBS FSCs and SAM NAICS filters. The button runs a quick search so the page stays responsive.
            </p>
            <div className="ingest-profile-plan">
              <div className="row-subtitle">
                <strong>DIBBS FSCs:</strong> {(plan?.dibbs?.fsc_codes || DEFAULT_DIBBS_FSC_CODES).join(', ')}
              </div>
              <div className="row-subtitle">
                <strong>SAM keywords:</strong> {(plan?.sam?.keywords || []).join(', ') || 'Profile keywords not loaded yet'}
              </div>
              <div className="row-subtitle">
                <strong>SAM NAICS:</strong> {(plan?.sam?.naics_codes || []).join(', ') || 'Profile NAICS not loaded yet'}
              </div>
              <div className="row-subtitle">
                <strong>Search size:</strong> Up to {DEFAULT_PER_CODE_SEARCH_SIZE} results per FSC or NAICS.
              </div>
            </div>
            <Button
              onClick={runProfileIngest}
              loading={profileIngestMutation.isPending || (isSearching && activeJob?.kind === 'profile')}
              disabled={ingestMutation.isPending || isSearching}
            >
              Search
            </Button>
          </div>
        </Card>

        <Card title="Manual Search">
          <form className="company-form" onSubmit={handleSubmit}>
            <div className="ingest-search-stack">
              <Input
                label={source === 'DIBBS' ? 'DLA FSC Codes' : 'Search Codes'}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={source === 'DIBBS' ? '6520' : '561720, 561210'}
                helperText={helperText}
              />
              <div className="ingest-controls-row">
                <div className="filter-select">
                  <label className="input-label">Source</label>
                  <select value={source} onChange={(event) => handleSourceChange(event.target.value)}>
                    <option value="DIBBS">DLA / DIBBS</option>
                    <option value="SAM">SAM</option>
                    <option value="ALL">All Sources</option>
                  </select>
                </div>
                <div className="form-action">
                  <Button
                    type="submit"
                    variant="secondary"
                    loading={ingestMutation.isPending || (isSearching && activeJob?.kind === 'manual')}
                    disabled={profileIngestMutation.isPending || isSearching}
                  >
                    Search
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    loading={ingestMutation.isPending || (isSearching && activeJob?.kind === 'manual')}
                    disabled={profileIngestMutation.isPending || isSearching}
                    onClick={() => runManualSearch({ deep: true })}
                  >
                    Deep Search
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    loading={pdfDownloadMutation.isPending || (isSearching && isPdfDownloadJob)}
                    disabled={source !== 'DIBBS' || profileIngestMutation.isPending || ingestMutation.isPending || isSearching || !query.trim()}
                    onClick={runBulkPdfDownload}
                  >
                    Bulk Download PDFs
                  </Button>
                </div>
              </div>
              {showSamFilters ? (
                <div className="sam-filter-grid">
                  <Input
                    label="SAM State"
                    value={samState}
                    onChange={(event) => setSamState(event.target.value.toUpperCase())}
                    placeholder="VA"
                    maxLength={2}
                    helperText="Optional. Applies only to SAM.gov."
                  />
                  <Input
                    label="SAM ZIP"
                    value={samZip}
                    onChange={(event) => setSamZip(event.target.value)}
                    placeholder="22102"
                    helperText="Optional location filter."
                  />
                  <Input
                    label="SAM Agency"
                    value={samAgency}
                    onChange={(event) => setSamAgency(event.target.value)}
                    placeholder="Department of Veterans Affairs"
                    helperText="Optional agency name."
                  />
                </div>
              ) : null}
              <div className="row-subtitle">
                Deep Search reviews all available source records for the selected codes and may take significantly longer on DIBBS.
              </div>
            </div>
          </form>
        </Card>
      </div>

      <Card title="Search Results">
        {isSearching ? (
          <div className="search-progress-box">
            <div className="search-progress-header">
              <div>
                <div className="row-title">Search in progress</div>
                <div className="row-subtitle">
                  {activeJob?.progress?.current_source
                    ? `${activeJob.progress.current_source}: ${activeJob.progress.current_label || 'working'}`
                    : 'Preparing search'}
                </div>
              </div>
              <strong>{activeJob?.progress?.percent || 0}%</strong>
            </div>
            <div className="search-progress-track">
              <div className="search-progress-fill" style={{ width: `${activeJob?.progress?.percent || 0}%` }} />
            </div>
            <div className="row-subtitle">
              {(activeJob?.progress?.completed_steps || 0)} of {(activeJob?.progress?.total_steps || 0)} search step{(activeJob?.progress?.total_steps || 0) === 1 ? '' : 's'} complete.
            </div>
          </div>
        ) : activeJob?.status === 'failed' ? (
          <div className="form-error">{activeJob.error || 'Search failed.'}</div>
        ) : !result ? (
          <EmptyState title="No search run yet" subtitle="Run the company profile search for the normal workflow, or use manual search for a focused DIBBS/SAM lookup." />
        ) : isPdfDownloadJob ? (
          <div className="ingest-summary-grid">
            <div className="ingest-source-card ingest-overall-card">
              <div>
                <div className="row-title">DIBBS PDF Download</div>
                <div className="row-subtitle">Main solicitation PDFs saved by FSC folder.</div>
              </div>
              <div className="ingest-result-row">
                <span>Found</span>
                <StatusPill status={String(result.found || 0)} />
              </div>
              <div className="ingest-result-row">
                <span>Downloaded</span>
                <StatusPill status={String(result.downloaded || 0)} />
              </div>
              <div className="ingest-result-row">
                <span>Failed</span>
                <StatusPill status={String(result.failed || 0)} />
              </div>
              <div className="ingest-result-row">
                <span>Missing PDF URL</span>
                <StatusPill status={String(result.missing_pdf_url || 0)} />
              </div>
            </div>
            <div className="ingest-source-card">
              <div>
                <div className="row-title">Export Location</div>
                <div className="row-subtitle">{result.output_dir || 'backend/exports/dibbs_pdfs'}</div>
              </div>
              <div className="ingest-result-row">
                <span>Limit per FSC</span>
                <strong>{result.limit_per_fsc || '-'}</strong>
              </div>
              <div className="ingest-result-row">
                <span>Manifest CSV</span>
                <strong>{result.manifest_csv ? 'Created' : '-'}</strong>
              </div>
              {result.manifest_csv ? <div className="row-subtitle">{result.manifest_csv}</div> : null}
            </div>
            <div className="ingest-source-card">
              <div>
                <div className="row-title">FSC Coverage</div>
                <div className="row-subtitle">{(result.fscs || []).join(', ') || 'No FSCs selected'}</div>
              </div>
              <div className="ingest-code-breakdown">
                {Object.entries(result.by_fsc || {}).map(([fsc, item]) => (
                  <div key={`pdf-${fsc}`} className="ingest-code-pill">
                    <span>{fsc}</span>
                    <strong>{item.downloaded || 0}/{item.found || 0}</strong>
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            <div className="ingest-summary-grid">
              <div className="ingest-source-card ingest-overall-card">
                <div>
                  <div className="row-title">Overall</div>
                  <div className="row-subtitle">Latest search result</div>
                </div>
                <div className="ingest-result-row">
                  <span>New opportunities</span>
                  <StatusPill status={String(resultTotals.inserted ?? 0)} />
                </div>
                <div className="ingest-result-row">
                  <span>Refreshed</span>
                  <StatusPill status={String(resultTotals.updated ?? 0)} />
                </div>
                <div className="ingest-result-row">
                  <span>Already current</span>
                  <StatusPill status={String(resultTotals.skipped ?? 0)} />
                </div>
              </div>

              <SourceResult label="DIBBS" result={sources?.dibbs} />
              <SourceResult label="SAM" result={sources?.sam} />
            </div>

            {(result.notices || []).length > 0 ? (
              <div className="ingest-notices">
                {(result.notices || []).map((notice, index) => (
                  <div key={`notice-${index}`} className="panel-subtitle">{notice}</div>
                ))}
              </div>
            ) : null}

            {(resultTotals.errors || []).length > 0 ? (
              <div className="ingest-errors">
                {(resultTotals.errors || []).map((error, index) => (
                  <div key={`overall-error-${index}`} className="form-error">{error}</div>
                ))}
              </div>
            ) : null}
          </>
        )}
      </Card>
    </div>
  )
}
