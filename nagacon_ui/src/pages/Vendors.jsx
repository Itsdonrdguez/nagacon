import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api/client'
import {
  EmptyState,
  Badge,
  Card,
  Button,
  Input,
  LoadingState,
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell,
} from '../components/ui'
import { Link } from 'react-router-dom'

function buildVendorReadiness(todayContext, providerData, awardData) {
  const providerCount = Number((providerData?.items || []).length)
  const awardCount = Number((awardData?.results || []).length)
  const missing = []
  const nextSteps = []

  if (todayContext?.nsn && providerCount === 0) {
    missing.push('Provider matches')
    nextSteps.push('Search providers')
  }
  if (todayContext?.agency && awardCount === 0) {
    missing.push('Past award signals')
    nextSteps.push('Search USAspending')
  }

  if (missing.length === 0 && (providerCount > 0 || awardCount > 0)) {
    return {
      status: 'READY TO REVIEW',
      tone: 'success',
      summary: 'Vendor research is loaded and ready for comparison.',
      missing,
      nextSteps: ['Review providers', 'Review past awardees'],
    }
  }
  if (missing.length > 0) {
    return {
      status: 'PARTIAL',
      tone: 'warning',
      summary: 'This research thread has context, but it still needs more vendor evidence.',
      missing,
      nextSteps,
    }
  }
  return {
    status: 'START RESEARCH',
    tone: 'info',
    summary: 'Search by provider, NSN, FSC, or agency to continue vendor research.',
    missing: [],
    nextSteps: ['Search providers', 'Search USAspending'],
  }
}

export default function Vendors() {
  const [searchParams] = useSearchParams()
  const [form, setForm] = useState({
    naics_code: '621910',
    keywords: 'medical, transportation',
    awarding_agency: 'JUSTICE, DEPARTMENT OF',
    page: 1,
    limit: 5,
  })
  const [data, setData] = useState(null)
  const [providerForm, setProviderForm] = useState({ q: '', nsn: '', fsc: '' })
  const [providerData, setProviderData] = useState(null)
  const [error, setError] = useState('')
  const [providerError, setProviderError] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isProviderLoading, setIsProviderLoading] = useState(false)
  const [appliedPrefillKey, setAppliedPrefillKey] = useState('')

  const todayContext = useMemo(() => {
    if (searchParams.get('source') !== 'today') return null
    return {
      opportunityId: searchParams.get('opportunity_id') || '',
      title: searchParams.get('title') || '',
      solicitation: searchParams.get('sol') || '',
      agency: searchParams.get('agency') || '',
      nsn: searchParams.get('nsn') || '',
      fsc: searchParams.get('fsc') || '',
      q: searchParams.get('q') || '',
    }
  }, [searchParams])
  const readiness = useMemo(
    () => buildVendorReadiness(todayContext, providerData, data),
    [todayContext, providerData, data],
  )

  async function executeSearch(nextForm = form) {
    setError('')
    setIsLoading(true)

    try {
      const payload = {
        ...nextForm,
        keywords: String(nextForm.keywords || '').split(',').map((item) => item.trim()).filter(Boolean),
        page: Number(nextForm.page),
        limit: Number(nextForm.limit),
      }
      const res = await api.post('/api/vendors/usaspending/search', payload)
      setData(res.data)
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Vendor search failed')
      setData(null)
    } finally {
      setIsLoading(false)
    }
  }

  async function runSearch(event) {
    event.preventDefault()
    await executeSearch()
  }

  async function executeProviderSearch(nextProviderForm = providerForm) {
    setProviderError('')
    setIsProviderLoading(true)
    try {
      const res = await api.get('/api/providers', {
        params: {
          q: nextProviderForm.q || undefined,
          nsn: nextProviderForm.nsn || undefined,
          fsc: nextProviderForm.fsc || undefined,
          limit: 25,
        },
      })
      setProviderData(res.data)
    } catch (err) {
      setProviderError(err?.response?.data?.detail || err?.message || 'Provider search failed')
      setProviderData(null)
    } finally {
      setIsProviderLoading(false)
    }
  }

  async function runProviderSearch(event) {
    event.preventDefault()
    await executeProviderSearch()
  }

  useEffect(() => {
    const currentKey = searchParams.toString()
    if (!currentKey || currentKey === appliedPrefillKey || !todayContext) return

    const nextProviderForm = {
      q: todayContext.q || '',
      nsn: todayContext.nsn || '',
      fsc: todayContext.fsc || '',
    }
    const hasProviderPrefill = Boolean(nextProviderForm.q || nextProviderForm.nsn || nextProviderForm.fsc)
    if (hasProviderPrefill) {
      setProviderForm(nextProviderForm)
      executeProviderSearch(nextProviderForm)
    }

    const nextAwardForm = {
      ...form,
      awarding_agency: todayContext.agency || form.awarding_agency,
    }
    if (todayContext.agency && !hasProviderPrefill) {
      setForm(nextAwardForm)
    }

    setAppliedPrefillKey(currentKey)
  }, [appliedPrefillKey, form, searchParams, todayContext])

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Research Desk</div>
          <h1 className="page-title">Vendor Intelligence</h1>
          <div className="page-subtitle">Search likely awardees and vendor signals with a cleaner intelligence view.</div>
        </div>
      </div>

      {todayContext ? (
        <Card title="Picked Up From Today" className="research-warning-box">
          <div className="row-title">{todayContext.title || 'Opportunity context loaded'}</div>
          <div className="row-subtitle">
            {[
              todayContext.solicitation,
              todayContext.agency,
              todayContext.nsn ? `NSN ${todayContext.nsn}` : '',
              todayContext.fsc ? `FSC ${todayContext.fsc}` : '',
            ].filter(Boolean).join(' | ')}
          </div>
          <div className="panel-subtitle">
            We prefilled vendor research using the opportunity context from Today so you can keep moving without retyping the basics.
          </div>
        </Card>
      ) : null}

      <Card title="Research Status" className={readiness.tone === 'warning' ? 'research-warning-box' : ''}>
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Badge label={readiness.status} variant={readiness.tone === 'success' ? 'success' : readiness.tone === 'warning' ? 'warning' : 'info'} />
            {todayContext?.opportunityId ? (
              <Link className="btn btn-secondary btn-sm" to={`/workspace/${todayContext.opportunityId}`}>
                Open Workspace
              </Link>
            ) : null}
          </div>
          <div className="row-title">{readiness.summary}</div>
          <div className="row-subtitle">
            {readiness.missing.length ? `Missing: ${readiness.missing.join(' | ')}` : 'Use this page to compare providers and past awardees.'}
          </div>
          <div className="simple-list">
            {readiness.nextSteps.map((step, index) => (
              <div className="simple-list-row" key={`vendor-next-step-${index}`}>
                <div className="row-title">{step}</div>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card title="USAspending Search">
        <form className="form-grid" onSubmit={runSearch}>
          <Input
            value={form.naics_code}
            onChange={(event) => setForm({ ...form, naics_code: event.target.value })}
            placeholder="NAICS"
            label="NAICS"
          />
          <Input
            value={form.awarding_agency}
            onChange={(event) => setForm({ ...form, awarding_agency: event.target.value })}
            placeholder="Awarding agency"
            label="Awarding Agency"
          />
          <Input
            value={form.keywords}
            onChange={(event) => setForm({ ...form, keywords: event.target.value })}
            placeholder="Comma-separated keywords"
            label="Keywords"
          />
          <div className="form-action">
            <Button type="submit" loading={isLoading}>
              Search USAspending
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Provider Database Search">
        <form className="form-grid" onSubmit={runProviderSearch}>
          <Input
            value={providerForm.q}
            onChange={(event) => setProviderForm({ ...providerForm, q: event.target.value })}
            placeholder="Company, CAGE, item..."
            label="Provider / CAGE"
          />
          <Input
            value={providerForm.nsn}
            onChange={(event) => setProviderForm({ ...providerForm, nsn: event.target.value })}
            placeholder="6520-01..."
            label="NSN"
          />
          <Input
            value={providerForm.fsc}
            onChange={(event) => setProviderForm({ ...providerForm, fsc: event.target.value })}
            placeholder="6520"
            label="FSC"
          />
          <div className="form-action">
            <Button type="submit" loading={isProviderLoading}>
              Search Providers
            </Button>
          </div>
        </form>
      </Card>

      <Card title="Provider Matches">
        {isProviderLoading ? (
          <LoadingState label="Searching provider database..." />
        ) : providerError ? (
          <EmptyState title="Provider search failed" subtitle={providerError} action={<Button onClick={() => executeProviderSearch()}>Retry search</Button>} />
        ) : !providerData ? (
          <EmptyState title="Search providers" subtitle="Search by NSN, FSC, CAGE, company, or item name to reuse PDF/SAM-enriched provider records." />
        ) : (providerData.items || []).length === 0 ? (
          <EmptyState title="No provider matches" subtitle="Try an exact NSN, a CAGE code, or a broader FSC." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Provider</TableHead>
                <TableHead>Item</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Source</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(providerData.items || []).map((row) => (
                <TableRow key={`${row.provider_id}-${row.provider_item_id || 'provider'}`}>
                  <TableCell>
                    <div className="row-title">{row.company_name || '-'}</div>
                    <div className="row-subtitle">{row.cage ? `CAGE ${row.cage}` : 'CAGE not set'}</div>
                  </TableCell>
                  <TableCell>
                    <div className="row-title">{row.nomenclature || 'Item not specified'}</div>
                    <div className="row-subtitle">{row.nsn || 'NSN not set'}{row.fsc ? ` | FSC ${row.fsc}` : ''}</div>
                  </TableCell>
                  <TableCell><Badge label={row.relationship_type || 'Unknown'} variant="default" /></TableCell>
                  <TableCell>{row.source || '-'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>

      <Card title="Results">
        {isLoading ? (
          <LoadingState label="Searching vendor intelligence..." />
        ) : error ? (
          <EmptyState title="Vendor search failed" subtitle={error} action={<Button onClick={() => executeSearch()}>Retry search</Button>} />
        ) : !data ? (
          <EmptyState title="Run a vendor search" subtitle="Search by NAICS, agency, and keywords to identify likely awardees." />
        ) : (data.results || []).length === 0 ? (
          <EmptyState title="No results" subtitle="Try broadening the agency or keyword filters." />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Award Amount</TableHead>
                <TableHead>Agency</TableHead>
                <TableHead>Award ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(data.results || []).map((row, idx) => (
                <TableRow key={`${row.award_id || 'award'}-${idx}`}>
                  <TableCell>{row.name || '-'}</TableCell>
                  <TableCell>{row.award_amount || '-'}</TableCell>
                  <TableCell>{row.awarding_agency || '-'}</TableCell>
                  <TableCell>
                    <Badge label={row.award_id || 'N/A'} variant="info" />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
