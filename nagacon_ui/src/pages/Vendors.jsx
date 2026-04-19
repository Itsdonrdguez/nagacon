import { useState } from 'react'
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

export default function Vendors() {
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

  async function executeSearch() {
    setError('')
    setIsLoading(true)

    try {
      const payload = {
        ...form,
        keywords: form.keywords.split(',').map((item) => item.trim()).filter(Boolean),
        page: Number(form.page),
        limit: Number(form.limit),
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

  async function executeProviderSearch() {
    setProviderError('')
    setIsProviderLoading(true)
    try {
      const res = await api.get('/api/providers', {
        params: {
          q: providerForm.q || undefined,
          nsn: providerForm.nsn || undefined,
          fsc: providerForm.fsc || undefined,
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

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Research Desk</div>
          <h1 className="page-title">Vendor Intelligence</h1>
          <div className="page-subtitle">Search likely awardees and vendor signals with a cleaner intelligence view.</div>
        </div>
      </div>

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
