import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingState,
  StatusPill,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'

const TYPE_OPTIONS = ['Manufacturer', 'Distributor', 'Awardee', 'Approved Source', 'Incumbent', 'Unknown']
const SOURCE_OPTIONS = ['Manual', 'DIBBS Approved Source', 'DIBBS Solicitation PDF', 'DIBBS RFQ', 'USAspending', 'SAM.gov', 'Import', 'Workspace Vendor Lead']

const EMPTY_FORM = {
  company_name: '',
  cage: '',
  website: '',
  relationship_type: 'Unknown',
  source: 'Manual',
  nsn: '',
  fsc: '',
  nomenclature: '',
  source_url: '',
  email: '',
  phone: '',
  notes: '',
}

function providerPayload(form) {
  return {
    company_name: form.company_name.trim(),
    cage: form.cage.trim() || null,
    website: form.website.trim() || null,
    email: form.email.trim() || null,
    phone: form.phone.trim() || null,
    notes: form.notes.trim() || null,
    item: {
      nsn: form.nsn.trim() || null,
      fsc: form.fsc.trim() || null,
      nomenclature: form.nomenclature.trim() || null,
      relationship_type: form.relationship_type || 'Unknown',
      source: form.source || 'Manual',
      source_url: form.source_url.trim() || null,
    },
  }
}

export default function Providers() {
  const queryClient = useQueryClient()
  const [filters, setFilters] = useState({ q: '', nsn: '', fsc: '', relationship_type: 'all', source: 'all' })
  const [submittedFilters, setSubmittedFilters] = useState(filters)
  const [form, setForm] = useState(EMPTY_FORM)
  const [csvContent, setCsvContent] = useState('')

  const providersQuery = useQuery({
    queryKey: ['providers', submittedFilters],
    queryFn: async () => {
      const res = await api.get('/api/providers', {
        params: {
          q: submittedFilters.q || undefined,
          nsn: submittedFilters.nsn || undefined,
          fsc: submittedFilters.fsc || undefined,
          relationship_type: submittedFilters.relationship_type === 'all' ? undefined : submittedFilters.relationship_type,
          source: submittedFilters.source === 'all' ? undefined : submittedFilters.source,
          limit: 100,
        },
      })
      return res.data
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/providers', payload)
      return res.data
    },
    onSuccess: () => {
      setForm(EMPTY_FORM)
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const importMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/providers/import-csv', { content: csvContent })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const seedMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/providers/seed/vendor-leads')
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const pdfExtractMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/providers/extract/dibbs-pdfs', null, {
        params: { enrich_with_sam: true },
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const samWebsiteMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/providers/enrich/sam-websites')
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const contactDiscoveryMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/providers/discover-contacts')
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const rows = providersQuery.data?.items || []
  const total = providersQuery.data?.total || 0

  const sourceCounts = useMemo(() => {
    const counts = {}
    rows.forEach((row) => {
      const sources = row.sources?.length ? row.sources : [row.source || 'No Source']
      sources.forEach((source) => {
        const key = source || 'No Source'
        counts[key] = (counts[key] || 0) + 1
      })
    })
    return counts
  }, [rows])

  const handleFilterSubmit = (event) => {
    event.preventDefault()
    setSubmittedFilters({ ...filters })
  }

  const handleCreate = async (event) => {
    event.preventDefault()
    await createMutation.mutateAsync(providerPayload(form))
  }

  const handleCsvFile = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    const text = await file.text()
    setCsvContent(text)
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Provider Intelligence</div>
          <h1 className="page-title">Providers</h1>
          <div className="page-subtitle">A reusable database of distributors, manufacturers, approved sources, and awardees tied to NSNs and FSCs.</div>
        </div>
      </div>

      <Card title="Provider Search">
        <form className="filters-form" onSubmit={handleFilterSubmit}>
          <div className="filters-grid filters-grid-wide">
            <Input label="Provider / Item" value={filters.q} onChange={(event) => setFilters({ ...filters, q: event.target.value })} placeholder="Company, item, CAGE..." />
            <Input label="NSN" value={filters.nsn} onChange={(event) => setFilters({ ...filters, nsn: event.target.value })} placeholder="6520-01..." />
            <Input label="FSC" value={filters.fsc} onChange={(event) => setFilters({ ...filters, fsc: event.target.value })} placeholder="6520" />
            <div className="filter-select">
              <label className="input-label">Type</label>
              <select value={filters.relationship_type} onChange={(event) => setFilters({ ...filters, relationship_type: event.target.value })}>
                <option value="all">All Types</option>
                {TYPE_OPTIONS.map((type) => <option key={type} value={type}>{type}</option>)}
              </select>
            </div>
            <div className="filter-select">
              <label className="input-label">Source</label>
              <select value={filters.source} onChange={(event) => setFilters({ ...filters, source: event.target.value })}>
                <option value="all">All Sources</option>
                {SOURCE_OPTIONS.map((source) => <option key={source} value={source}>{source}</option>)}
              </select>
            </div>
            <div className="form-action">
              <Button type="submit">Search</Button>
            </div>
          </div>
        </form>
      </Card>

      <div className="provider-grid">
        <Card title="Add Provider">
          <form className="company-form" onSubmit={handleCreate}>
            <div className="company-form-grid">
              <Input label="Company Name" value={form.company_name} onChange={(event) => setForm({ ...form, company_name: event.target.value })} required />
              <Input label="CAGE" value={form.cage} onChange={(event) => setForm({ ...form, cage: event.target.value.toUpperCase() })} />
              <Input label="Website / URL" value={form.website} onChange={(event) => setForm({ ...form, website: event.target.value })} />
              <Input label="Email" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
              <Input label="Phone" value={form.phone} onChange={(event) => setForm({ ...form, phone: event.target.value })} />
              <Input label="NSN" value={form.nsn} onChange={(event) => setForm({ ...form, nsn: event.target.value })} />
              <Input label="FSC" value={form.fsc} onChange={(event) => setForm({ ...form, fsc: event.target.value })} />
              <Input label="Item / Nomenclature" value={form.nomenclature} onChange={(event) => setForm({ ...form, nomenclature: event.target.value })} />
              <div className="filter-select">
                <label className="input-label">Type</label>
                <select value={form.relationship_type} onChange={(event) => setForm({ ...form, relationship_type: event.target.value })}>
                  {TYPE_OPTIONS.map((type) => <option key={type} value={type}>{type}</option>)}
                </select>
              </div>
              <div className="filter-select">
                <label className="input-label">Source</label>
                <select value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })}>
                  {SOURCE_OPTIONS.map((source) => <option key={source} value={source}>{source}</option>)}
                </select>
              </div>
              <Input label="Source URL" value={form.source_url} onChange={(event) => setForm({ ...form, source_url: event.target.value })} />
            </div>
            <div className="company-form-stack">
              <label className="textarea-label" htmlFor="provider_notes">Notes</label>
              <textarea id="provider_notes" className="textarea-field" value={form.notes} onChange={(event) => setForm({ ...form, notes: event.target.value })} placeholder="Optional sourcing or contact notes." />
            </div>
            <div className="company-form-actions">
              <Button type="submit" loading={createMutation.isPending}>Save Provider</Button>
              {createMutation.error ? <span className="form-error">{createMutation.error.message || 'Failed to save provider.'}</span> : null}
            </div>
          </form>
        </Card>

        <Card title="Import Providers">
          <div className="company-form">
            <p className="panel-subtitle">
              CSV headers supported: company_name, type, cage, uei, nsn, fsc, nomenclature, url, source, email, phone, notes.
            </p>
            <Input type="file" accept=".csv,text/csv" onChange={handleCsvFile} />
            <div className="company-form-stack">
              <label className="textarea-label" htmlFor="provider_csv">CSV Preview / Paste</label>
              <textarea id="provider_csv" className="textarea-field" value={csvContent} onChange={(event) => setCsvContent(event.target.value)} placeholder="company_name,type,cage,nsn,fsc,nomenclature,source,url" />
            </div>
            <div className="company-form-actions">
              <Button variant="secondary" loading={importMutation.isPending} disabled={!csvContent.trim()} onClick={() => importMutation.mutate()}>
                Import CSV
              </Button>
              <Button variant="secondary" loading={seedMutation.isPending} onClick={() => seedMutation.mutate()}>
                Seed From Vendor Leads
              </Button>
              <Button variant="secondary" loading={pdfExtractMutation.isPending} onClick={() => pdfExtractMutation.mutate()}>
                Extract From DIBBS PDFs
              </Button>
              <Button variant="secondary" loading={samWebsiteMutation.isPending} onClick={() => samWebsiteMutation.mutate()}>
                Enrich SAM Websites
              </Button>
              <Button variant="secondary" loading={contactDiscoveryMutation.isPending} onClick={() => contactDiscoveryMutation.mutate()}>
                Discover Contacts
              </Button>
            </div>
            {importMutation.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest Import</div>
                <div className="row-subtitle">Inserted {importMutation.data.inserted || 0}, updated {importMutation.data.updated || 0}, skipped {importMutation.data.skipped || 0}</div>
                {(importMutation.data.errors || []).slice(0, 3).map((error, index) => <div key={index} className="form-error">{error}</div>)}
              </div>
            ) : null}
            {seedMutation.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest Auto Seed</div>
                <div className="row-subtitle">Inserted {seedMutation.data.inserted || 0}, updated {seedMutation.data.updated || 0}, skipped {seedMutation.data.skipped || 0}</div>
                {(seedMutation.data.errors || []).slice(0, 3).map((error, index) => <div key={index} className="form-error">{error}</div>)}
              </div>
            ) : null}
            {pdfExtractMutation.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest PDF Extraction</div>
                <div className="row-subtitle">
                  Scanned {pdfExtractMutation.data.scanned_files || 0} PDFs, found {pdfExtractMutation.data.cages_found || 0} CAGEs, inserted {pdfExtractMutation.data.inserted || 0}, updated {pdfExtractMutation.data.updated || 0}.
                </div>
                <div className="row-subtitle">
                  Valid PDFs: {pdfExtractMutation.data.valid_pdfs || 0} | Skipped invalid: {pdfExtractMutation.data.invalid_pdfs || 0} | SAM names filled: {pdfExtractMutation.data.sam_enriched || 0}
                </div>
                {(pdfExtractMutation.data.errors || []).slice(0, 3).map((error, index) => <div key={index} className="form-error">{error}</div>)}
              </div>
            ) : null}
            {samWebsiteMutation.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest SAM Website Enrichment</div>
                <div className="row-subtitle">Checked {samWebsiteMutation.data.checked || 0}, updated {samWebsiteMutation.data.updated || 0}</div>
                {(samWebsiteMutation.data.errors || []).slice(0, 3).map((error, index) => <div key={index} className="form-error">{error}</div>)}
              </div>
            ) : null}
            {contactDiscoveryMutation.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest Contact Discovery</div>
                <div className="row-subtitle">Checked {contactDiscoveryMutation.data.checked || 0}, updated {contactDiscoveryMutation.data.updated || 0}</div>
                {(contactDiscoveryMutation.data.errors || []).slice(0, 3).map((error, index) => <div key={index} className="form-error">{error}</div>)}
              </div>
            ) : null}
          </div>
        </Card>
      </div>

      <Card title="Provider Database">
        {providersQuery.isLoading ? (
          <LoadingState label="Loading providers..." />
        ) : rows.length === 0 ? (
          <EmptyState title="No providers yet" subtitle="Add a provider manually or import a CSV to start building your sourcing database." />
        ) : (
          <>
            <div className="results-toolbar">
              <div className="results-count">Showing {rows.length} of {total}</div>
              <div className="badge-stack">
                {Object.entries(sourceCounts).slice(0, 5).map(([source, count]) => (
                  <Badge key={source} label={`${source}: ${count}`} variant="info" />
                ))}
              </div>
            </div>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Provider</TableHead>
                  <TableHead>NSN / Item</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Website</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.provider_id}>
                    <TableCell>
                      <div className="row-title">{row.company_name}</div>
                      <div className="row-subtitle">
                        {row.cage ? `CAGE ${row.cage}` : 'CAGE not set'}
                        {row.email ? ` | ${row.email}` : ''}
                        {row.item_count ? ` | ${row.item_count} item link${row.item_count === 1 ? '' : 's'}` : ''}
                      </div>
                    </TableCell>
                    <TableCell>
                      {(row.item_summaries || []).slice(0, 3).map((item) => (
                        <div key={item.provider_item_id || `${item.nsn}-${item.relationship_type}`} className="provider-item-line">
                          <div className="row-title">{item.nomenclature || item.nsn || 'Item not specified'}</div>
                          <div className="row-subtitle">
                            {item.nsn || 'NSN not set'}
                            {item.fsc ? ` | FSC ${item.fsc}` : ''}
                            {item.source ? ` | ${item.source}` : ''}
                          </div>
                        </div>
                      ))}
                      {(row.item_summaries || []).length === 0 ? (
                        <>
                          <div className="row-title">{row.nomenclature || 'Item not specified'}</div>
                          <div className="row-subtitle">{row.nsn || 'NSN not set'}{row.fsc ? ` | FSC ${row.fsc}` : ''}</div>
                        </>
                      ) : null}
                      {(row.item_summaries || []).length > 3 ? (
                        <div className="row-subtitle">+{row.item_summaries.length - 3} more item links</div>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <div className="badge-stack">
                        {(row.relationship_types?.length ? row.relationship_types : [row.relationship_type || 'Unknown']).slice(0, 4).map((type) => (
                          <Badge key={type} label={type || 'Unknown'} variant="default" />
                        ))}
                        {(row.relationship_types || []).length > 4 ? <Badge label={`+${row.relationship_types.length - 4}`} variant="info" /> : null}
                      </div>
                    </TableCell>
                    <TableCell>{(row.sources?.length ? row.sources : [row.source]).filter(Boolean).join(', ') || '-'}</TableCell>
                    <TableCell>
                      {row.website ? (
                        <a href={row.website} target="_blank" rel="noreferrer">Open</a>
                      ) : '-'}
                    </TableCell>
                    <TableCell><StatusPill status={row.status || 'active'} /></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </>
        )}
      </Card>
    </div>
  )
}
