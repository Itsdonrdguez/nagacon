import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Button, EmptyState, Input, LoadingState, Badge, Table, TableHeader, TableBody, TableRow, TableHead, TableCell, MultiSelect } from '../components/ui'
import { FSC_CODE_OPTIONS, NAICS_CODE_OPTIONS, withCustomOptions } from '../data/codeCatalogs'

const SET_ASIDE_OPTIONS = [
  'Small Business',
  '8(a)',
  'SDVOSB',
  'WOSB',
  'EDWOSB',
  'HUBZone',
  'VOSB',
]

const DEFAULT_DIBBS_FSC_CODES = ['6520', '8470', '6550', '5805', '5130', '5810', '5998', '5999', '1095', '6110', '6515']
const DEFAULT_SAM_NAICS_CODES = ['561720', '561210', '561730', '561740', '561790', '484110', '484121', '484122', '488510', '492110', '492210', '485999', '488999']
const DEFAULT_SAM_KEYWORDS = ['janitorial', 'custodial', 'cleaning', 'facilities support', 'transportation', 'freight', 'trucking', 'logistics', 'courier', 'delivery']

const EMPTY_FORM = {
  legal_name: '',
  uei: '',
  cage: '',
  website: '',
  primary_contact_name: '',
  primary_contact_email: '',
  primary_contact_phone: '',
  address_line1: '',
  address_line2: '',
  city: '',
  state: '',
  postal_code: '',
  country: 'United States',
  naics_codes: [],
  certifications: [],
  capability_statement_url: '',
  core_competencies: '',
  differentiators: '',
  past_performance_summary: '',
  annual_revenue: '',
  preferred_dibbs_fsc_codes: DEFAULT_DIBBS_FSC_CODES,
  preferred_sam_naics_codes: DEFAULT_SAM_NAICS_CODES,
  preferred_sam_keywords: DEFAULT_SAM_KEYWORDS.join(', '),
  preferred_sam_agencies: '',
  preferred_sam_states: '',
  auto_ingest_enabled: false,
  auto_ingest_limit: '25',
  auto_ingest_interval_hours: '24',
  dibbs_pdf_download_limit: '25',
}

const EMPTY_PERFORMANCE_FORM = {
  client_name: '',
  project_title: '',
  project_value: '',
  start_date: '',
  end_date: '',
  description: '',
  naics_code: '',
  relevance_tags: '',
}

function formFromProfile(profile) {
  if (!profile) return EMPTY_FORM

  return {
    legal_name: profile.legal_name || '',
    uei: profile.uei || '',
    cage: profile.cage || '',
    website: profile.website || '',
    primary_contact_name: profile.primary_contact_name || '',
    primary_contact_email: profile.primary_contact_email || '',
    primary_contact_phone: profile.primary_contact_phone || '',
    address_line1: profile.address_line1 || '',
    address_line2: profile.address_line2 || '',
    city: profile.city || '',
    state: profile.state || '',
    postal_code: profile.postal_code || '',
    country: profile.country || 'United States',
    naics_codes: profile.naics_codes || [],
    certifications: profile.certifications || [],
    capability_statement_url: profile.capability_statement_url || '',
    core_competencies: profile.core_competencies || '',
    differentiators: profile.differentiators || '',
    past_performance_summary: profile.past_performance_summary || '',
    annual_revenue: profile.annual_revenue ?? '',
    preferred_dibbs_fsc_codes: profile.preferred_dibbs_fsc_codes || DEFAULT_DIBBS_FSC_CODES,
    preferred_sam_naics_codes: profile.preferred_sam_naics_codes || DEFAULT_SAM_NAICS_CODES,
    preferred_sam_keywords: (profile.preferred_sam_keywords || DEFAULT_SAM_KEYWORDS).join(', '),
    preferred_sam_agencies: (profile.preferred_sam_agencies || []).join(', '),
    preferred_sam_states: (profile.preferred_sam_states || (profile.state ? [profile.state] : [])).join(', '),
    auto_ingest_enabled: Boolean(profile.auto_ingest_enabled),
    auto_ingest_limit: profile.auto_ingest_limit ?? 25,
    auto_ingest_interval_hours: profile.auto_ingest_interval_hours ?? 24,
    dibbs_pdf_download_limit: profile.dibbs_pdf_download_limit ?? 25,
  }
}

function parseCsv(value) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Company() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState(EMPTY_FORM)
  const [performanceForm, setPerformanceForm] = useState(EMPTY_PERFORMANCE_FORM)
  const [saveMessage, setSaveMessage] = useState('')

  const companyQuery = useQuery({
    queryKey: ['company-profile-editor'],
    queryFn: async () => {
      const res = await api.get('/api/company/profile')
      return res.data
    },
    retry: 1,
  })

  const pastPerformanceQuery = useQuery({
    queryKey: ['past-performance', companyQuery.data?.id],
    queryFn: async () => {
      const res = await api.get(`/api/company/past-performance/${companyQuery.data.id}`)
      return res.data
    },
    enabled: !!companyQuery.data?.id,
    retry: 1,
  })

  const ingestPlanQuery = useQuery({
    queryKey: ['company-ingest-plan'],
    queryFn: async () => {
      const res = await api.get('/api/company/ingest-plan')
      return res.data
    },
    enabled: !!companyQuery.data?.id,
    retry: 1,
  })

  useEffect(() => {
    if (companyQuery.data) {
      setForm(formFromProfile(companyQuery.data))
    }
    if (companyQuery.data === null) {
      setForm(EMPTY_FORM)
    }
  }, [companyQuery.data])

  const saveMutation = useMutation({
    mutationFn: async (payload) => {
      if (companyQuery.data?.id) {
        const res = await api.patch(`/api/company/profile/${companyQuery.data.id}`, payload)
        return res.data
      }
      const res = await api.post('/api/company/profile', payload)
      return res.data
    },
    onSuccess: (saved) => {
      setSaveMessage('Company profile saved.')
      queryClient.setQueryData(['company-profile-editor'], saved)
      queryClient.setQueryData(['company-profile'], saved)
      queryClient.invalidateQueries({ queryKey: ['company-profile'] })
      queryClient.invalidateQueries({ queryKey: ['company-profile-editor'] })
      queryClient.invalidateQueries({ queryKey: ['company-ingest-plan'] })
    },
  })

  const createPastPerformanceMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/company/past-performance', payload)
      return res.data
    },
    onSuccess: () => {
      setPerformanceForm(EMPTY_PERFORMANCE_FORM)
      queryClient.invalidateQueries({ queryKey: ['past-performance', companyQuery.data?.id] })
    },
  })

  const runRecommendedIngestMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/company/ingest-run')
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['opportunities'] })
      queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })

  const selectedSetAsides = form.certifications
  const naicsCodeOptions = useMemo(
    () => withCustomOptions(NAICS_CODE_OPTIONS, [...(form.naics_codes || []), ...(form.preferred_sam_naics_codes || [])], 'naics'),
    [form.naics_codes, form.preferred_sam_naics_codes],
  )
  const fscCodeOptions = useMemo(
    () => withCustomOptions(FSC_CODE_OPTIONS, form.preferred_dibbs_fsc_codes || [], 'fsc'),
    [form.preferred_dibbs_fsc_codes],
  )

  const payload = useMemo(() => ({
    legal_name: form.legal_name.trim(),
    uei: form.uei.trim() || null,
    cage: form.cage.trim() || null,
    website: form.website.trim() || null,
    primary_contact_name: form.primary_contact_name.trim() || null,
    primary_contact_email: form.primary_contact_email.trim() || null,
    primary_contact_phone: form.primary_contact_phone.trim() || null,
    address_line1: form.address_line1.trim() || null,
    address_line2: form.address_line2.trim() || null,
    city: form.city.trim() || null,
    state: form.state.trim() || null,
    postal_code: form.postal_code.trim() || null,
    country: form.country.trim() || null,
    naics_codes: form.naics_codes,
    certifications: selectedSetAsides,
    capability_statement_url: form.capability_statement_url.trim() || null,
    core_competencies: form.core_competencies.trim() || null,
    differentiators: form.differentiators.trim() || null,
    past_performance_summary: form.past_performance_summary.trim() || null,
    annual_revenue: form.annual_revenue === '' ? null : Number(form.annual_revenue),
    preferred_dibbs_fsc_codes: form.preferred_dibbs_fsc_codes,
    preferred_sam_naics_codes: form.preferred_sam_naics_codes,
    preferred_sam_keywords: parseCsv(form.preferred_sam_keywords),
    preferred_sam_agencies: parseCsv(form.preferred_sam_agencies),
    preferred_sam_states: parseCsv(form.preferred_sam_states),
    auto_ingest_enabled: Boolean(form.auto_ingest_enabled),
    auto_ingest_limit: form.auto_ingest_limit === '' ? 25 : Number(form.auto_ingest_limit),
    auto_ingest_interval_hours: form.auto_ingest_interval_hours === '' ? 24 : Number(form.auto_ingest_interval_hours),
    dibbs_pdf_download_limit: form.dibbs_pdf_download_limit === '' ? 25 : Number(form.dibbs_pdf_download_limit),
  }), [form, selectedSetAsides])

  const toggleSetAside = (option) => {
    setForm((current) => ({
      ...current,
      certifications: current.certifications.includes(option)
        ? current.certifications.filter((item) => item !== option)
        : [...current.certifications, option],
    }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    setSaveMessage('')
    await saveMutation.mutateAsync(payload)
  }

  const handlePastPerformanceSubmit = async (event) => {
    event.preventDefault()
    if (!companyQuery.data?.id) return

    await createPastPerformanceMutation.mutateAsync({
      company_profile_id: companyQuery.data.id,
      client_name: performanceForm.client_name.trim(),
      project_title: performanceForm.project_title.trim(),
      project_value: performanceForm.project_value === '' ? null : Number(performanceForm.project_value),
      start_date: performanceForm.start_date || null,
      end_date: performanceForm.end_date || null,
      description: performanceForm.description.trim() || null,
      naics_code: performanceForm.naics_code.trim() || null,
      relevance_tags: parseCsv(performanceForm.relevance_tags),
    })
  }

  if (companyQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading company profile..." />
        </Card>
      </div>
    )
  }

  if (companyQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Company profile unavailable"
          subtitle={companyQuery.error.message || 'Could not load company information.'}
          action={<Button onClick={() => companyQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <h1 className="page-title">Company Profile</h1>

      <Card title="Business Information">
        <form className="company-form" onSubmit={handleSubmit}>
          <div className="company-form-grid">
            <Input label="Legal Name" value={form.legal_name} onChange={(event) => setForm({ ...form, legal_name: event.target.value })} placeholder="Your registered business name" required />
            <Input label="Website" value={form.website} onChange={(event) => setForm({ ...form, website: event.target.value })} placeholder="https://yourcompany.com" />
            <Input label="UEI" value={form.uei} onChange={(event) => setForm({ ...form, uei: event.target.value })} placeholder="Entity Identifier" />
            <Input label="CAGE" value={form.cage} onChange={(event) => setForm({ ...form, cage: event.target.value })} placeholder="CAGE code" />
            <Input label="Primary Contact" value={form.primary_contact_name} onChange={(event) => setForm({ ...form, primary_contact_name: event.target.value })} placeholder="Contact name" />
            <Input label="Contact Email" value={form.primary_contact_email} onChange={(event) => setForm({ ...form, primary_contact_email: event.target.value })} placeholder="name@company.com" />
            <Input label="Contact Phone" value={form.primary_contact_phone} onChange={(event) => setForm({ ...form, primary_contact_phone: event.target.value })} placeholder="(555) 555-5555" />
            <Input label="Annual Revenue" type="number" min="0" value={form.annual_revenue} onChange={(event) => setForm({ ...form, annual_revenue: event.target.value })} placeholder="0" />
          </div>

          <div className="company-form-grid">
            <Input label="Address Line 1" value={form.address_line1} onChange={(event) => setForm({ ...form, address_line1: event.target.value })} placeholder="Street address" />
            <Input label="Address Line 2" value={form.address_line2} onChange={(event) => setForm({ ...form, address_line2: event.target.value })} placeholder="Suite, unit, or building" />
            <Input label="City" value={form.city} onChange={(event) => setForm({ ...form, city: event.target.value })} placeholder="City" />
            <Input label="State" value={form.state} onChange={(event) => setForm({ ...form, state: event.target.value })} placeholder="State" />
            <Input label="Postal Code" value={form.postal_code} onChange={(event) => setForm({ ...form, postal_code: event.target.value })} placeholder="ZIP / postal code" />
            <Input label="Country" value={form.country} onChange={(event) => setForm({ ...form, country: event.target.value })} placeholder="Country" />
          </div>

          <MultiSelect
            label="NAICS Codes"
            value={form.naics_codes}
            options={naicsCodeOptions}
            onChange={(next) => setForm({ ...form, naics_codes: next })}
            placeholder="Search NAICS codes"
            helperText="Search and select one or more NAICS codes for your company profile."
            allowCustom
            customTypeLabel="NAICS code"
            normalizeValue={(item) => String(item || '').replace(/\D/g, '').slice(0, 6)}
          />

          <div className="company-section">
            <div className="company-section-label">Set-Asides / Certifications</div>
            <div className="set-aside-picker">
              {SET_ASIDE_OPTIONS.map((option) => {
                const isSelected = selectedSetAsides.includes(option)
                return (
                  <button key={option} type="button" className={`set-aside-chip ${isSelected ? 'selected' : ''}`} onClick={() => toggleSetAside(option)}>
                    {option}
                  </button>
                )
              })}
            </div>
            {selectedSetAsides.length > 0 ? (
              <div className="badge-stack company-badge-stack">
                {selectedSetAsides.map((item) => (
                  <Badge key={item} label={item} variant="info" />
                ))}
              </div>
            ) : null}
          </div>

          <Input label="Capability Statement URL" value={form.capability_statement_url} onChange={(event) => setForm({ ...form, capability_statement_url: event.target.value })} placeholder="https://..." />

          <div className="company-form-stack">
            <label className="textarea-label" htmlFor="core_competencies">Core Competencies</label>
            <textarea id="core_competencies" className="textarea-field" value={form.core_competencies} onChange={(event) => setForm({ ...form, core_competencies: event.target.value })} placeholder="Summarize your delivery strengths, technical capabilities, and service lines." />
          </div>

          <div className="company-form-stack">
            <label className="textarea-label" htmlFor="differentiators">Differentiators</label>
            <textarea id="differentiators" className="textarea-field" value={form.differentiators} onChange={(event) => setForm({ ...form, differentiators: event.target.value })} placeholder="What makes your company stand out?" />
          </div>

          <div className="company-form-stack">
            <label className="textarea-label" htmlFor="past_performance_summary">Past Performance Summary</label>
            <textarea id="past_performance_summary" className="textarea-field" value={form.past_performance_summary} onChange={(event) => setForm({ ...form, past_performance_summary: event.target.value })} placeholder="Summarize relevant contracts and delivery experience." />
          </div>

          <Card title="Opportunity Targeting">
            <div className="company-form-stack">
              <div className="panel-subtitle">
                These preferences drive recommended ingest. DIBBS uses FSC codes, and SAM uses janitorial / transportation targeting with keyword and NAICS filtering.
              </div>
            </div>
            <div className="company-form-grid">
              <MultiSelect
                label="DIBBS FSC Codes"
                value={form.preferred_dibbs_fsc_codes}
                options={fscCodeOptions}
                onChange={(next) => setForm({ ...form, preferred_dibbs_fsc_codes: next })}
                placeholder="Search FSC codes"
                helperText="Search and select the FSC codes used for DIBBS ingestion."
                allowCustom
                customTypeLabel="FSC code"
                normalizeValue={(item) => String(item || '').replace(/\D/g, '').slice(0, 4)}
              />
              <MultiSelect
                label="SAM NAICS Codes"
                value={form.preferred_sam_naics_codes}
                options={naicsCodeOptions}
                onChange={(next) => setForm({ ...form, preferred_sam_naics_codes: next })}
                placeholder="Search NAICS codes"
                helperText="Search and select the NAICS filters used for SAM opportunities."
                allowCustom
                customTypeLabel="NAICS code"
                normalizeValue={(item) => String(item || '').replace(/\D/g, '').slice(0, 6)}
              />
              <Input
                label="SAM Keywords"
                value={form.preferred_sam_keywords}
                onChange={(event) => setForm({ ...form, preferred_sam_keywords: event.target.value })}
                helperText="Keywords that shape SAM searches and keep intake focused."
              />
              <Input
                label="SAM Agencies"
                value={form.preferred_sam_agencies}
                onChange={(event) => setForm({ ...form, preferred_sam_agencies: event.target.value })}
                helperText="Optional agency names to narrow federal searches."
              />
              <Input
                label="SAM States"
                value={form.preferred_sam_states}
                onChange={(event) => setForm({ ...form, preferred_sam_states: event.target.value })}
                helperText="Optional state filter for SAM searches."
              />
              <Input
                label="Auto Ingest Limit"
                type="number"
                min="1"
                max="100"
                value={form.auto_ingest_limit}
                onChange={(event) => setForm({ ...form, auto_ingest_limit: event.target.value })}
                helperText="Rows per FSC / keyword query."
              />
              <Input
                label="Auto Ingest Every (Hours)"
                type="number"
                min="1"
                max="168"
                value={form.auto_ingest_interval_hours}
                onChange={(event) => setForm({ ...form, auto_ingest_interval_hours: event.target.value })}
                helperText="Scheduler cadence for profile-driven ingestion."
              />
              <Input
                label="DIBBS PDF Download Limit"
                type="number"
                min="1"
                max="250"
                value={form.dibbs_pdf_download_limit}
                onChange={(event) => setForm({ ...form, dibbs_pdf_download_limit: event.target.value })}
                helperText="Main solicitation PDFs to download per saved FSC."
              />
            </div>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={Boolean(form.auto_ingest_enabled)}
                onChange={(event) => setForm({ ...form, auto_ingest_enabled: event.target.checked })}
              />
              <span>Auto ingest enabled</span>
            </label>

            {ingestPlanQuery.data ? (
              <div className="settings-summary-box">
                <div className="row-title">Current Ingest Plan</div>
                <div className="row-subtitle">
                  DIBBS FSCs: {(ingestPlanQuery.data.dibbs?.fsc_codes || []).join(', ') || '-'}
                </div>
                <div className="row-subtitle">
                  SAM keywords: {(ingestPlanQuery.data.sam?.keywords || []).join(', ') || '-'}
                </div>
                <div className="row-subtitle">
                  SAM NAICS: {(ingestPlanQuery.data.sam?.naics_codes || []).join(', ') || '-'}
                </div>
                <div className="row-subtitle">
                  Auto ingest: {ingestPlanQuery.data.auto_ingest_enabled ? 'Enabled' : 'Disabled'} every {ingestPlanQuery.data.auto_ingest_interval_hours || 24} hour(s)
                </div>
                <div className="row-subtitle">
                  Last run: {ingestPlanQuery.data.last_auto_ingest_at ? formatDate(ingestPlanQuery.data.last_auto_ingest_at) : 'Not run yet'}
                </div>
                <div className="row-subtitle">
                  DIBBS PDF download limit: {ingestPlanQuery.data.dibbs_pdf_download_limit || ingestPlanQuery.data.dibbs?.pdf_download_limit || 25} per FSC
                </div>
              </div>
            ) : null}
          </Card>

          <div className="company-form-actions">
            <Button type="submit" loading={saveMutation.isPending}>Save Company Profile</Button>
            <Button
              type="button"
              variant="secondary"
              loading={runRecommendedIngestMutation.isPending}
              disabled={!companyQuery.data?.id}
              onClick={() => runRecommendedIngestMutation.mutate()}
            >
              Run Recommended Ingest
            </Button>
            {saveMessage ? <span className="form-success">{saveMessage}</span> : null}
            {saveMutation.error ? <span className="form-error">{saveMutation.error.message || 'Failed to save profile.'}</span> : null}
          </div>
          {runRecommendedIngestMutation.data ? (
            <div className="settings-summary-box">
              <div className="row-title">Latest Recommended Ingest</div>
              <div className="row-subtitle">
                DIBBS: inserted {runRecommendedIngestMutation.data.results?.dibbs?.inserted || 0}, updated {runRecommendedIngestMutation.data.results?.dibbs?.updated || 0}, skipped {runRecommendedIngestMutation.data.results?.dibbs?.skipped || 0}
              </div>
              <div className="row-subtitle">
                SAM: inserted {runRecommendedIngestMutation.data.results?.sam?.inserted || 0}, updated {runRecommendedIngestMutation.data.results?.sam?.updated || 0}, skipped {runRecommendedIngestMutation.data.results?.sam?.skipped || 0}
              </div>
            </div>
          ) : null}
        </form>
      </Card>

      <Card title="Past Performance">
        {!companyQuery.data?.id ? (
          <EmptyState title="Save the company profile first" subtitle="Past performance entries attach to a saved company record." />
        ) : (
          <div className="company-form">
            <form className="company-form" onSubmit={handlePastPerformanceSubmit}>
              <div className="company-form-grid">
                <Input label="Client Name" value={performanceForm.client_name} onChange={(event) => setPerformanceForm({ ...performanceForm, client_name: event.target.value })} placeholder="Agency or customer" required />
                <Input label="Project Title" value={performanceForm.project_title} onChange={(event) => setPerformanceForm({ ...performanceForm, project_title: event.target.value })} placeholder="Contract or project title" required />
                <Input label="Project Value" type="number" min="0" value={performanceForm.project_value} onChange={(event) => setPerformanceForm({ ...performanceForm, project_value: event.target.value })} placeholder="0" />
                <Input label="NAICS Code" value={performanceForm.naics_code} onChange={(event) => setPerformanceForm({ ...performanceForm, naics_code: event.target.value })} placeholder="541512" />
                <Input label="Start Date" type="date" value={performanceForm.start_date} onChange={(event) => setPerformanceForm({ ...performanceForm, start_date: event.target.value })} />
                <Input label="End Date" type="date" value={performanceForm.end_date} onChange={(event) => setPerformanceForm({ ...performanceForm, end_date: event.target.value })} />
              </div>
              <Input label="Relevance Tags" value={performanceForm.relevance_tags} onChange={(event) => setPerformanceForm({ ...performanceForm, relevance_tags: event.target.value })} placeholder="cloud, cybersecurity, logistics" helperText="Use commas to separate multiple tags." />
              <div className="company-form-stack">
                <label className="textarea-label" htmlFor="performance_description">Description</label>
                <textarea id="performance_description" className="textarea-field" value={performanceForm.description} onChange={(event) => setPerformanceForm({ ...performanceForm, description: event.target.value })} placeholder="What was delivered and why it matters for upcoming bids?" />
              </div>
              <div className="company-form-actions">
                <Button type="submit" loading={createPastPerformanceMutation.isPending}>Add Past Performance</Button>
                {createPastPerformanceMutation.error ? <span className="form-error">{createPastPerformanceMutation.error.message || 'Failed to add entry.'}</span> : null}
              </div>
            </form>

            {pastPerformanceQuery.isLoading ? (
              <LoadingState label="Loading past performance..." />
            ) : (pastPerformanceQuery.data || []).length === 0 ? (
              <EmptyState title="No past performance entries yet" subtitle="Add a few relevant contracts so future bid analysis can use them." />
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Client</TableHead>
                    <TableHead>Project</TableHead>
                    <TableHead>Value</TableHead>
                    <TableHead>Dates</TableHead>
                    <TableHead>NAICS</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {pastPerformanceQuery.data.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell>{entry.client_name}</TableCell>
                      <TableCell>
                        <div className="row-title">{entry.project_title}</div>
                        <div className="row-subtitle">{entry.description || 'No description provided'}</div>
                      </TableCell>
                      <TableCell>{entry.project_value ?? '-'}</TableCell>
                      <TableCell>{formatDate(entry.start_date)} - {formatDate(entry.end_date)}</TableCell>
                      <TableCell>{entry.naics_code || '-'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </div>
        )}
      </Card>
    </div>
  )
}
