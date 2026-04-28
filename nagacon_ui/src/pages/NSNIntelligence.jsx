import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
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

const DEFAULT_NSN = '4110015342682'

function normalizeSearch(value) {
  return String(value || '').replace(/\D+/g, '')
}

function money(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 'Not available'
  return numeric.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 2 })
}

function numberLabel(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '0'
  return numeric.toLocaleString()
}

function SectionList({ items, empty }) {
  if (!items?.length) {
    return <div className="row-subtitle">{empty}</div>
  }
  return (
    <div className="simple-list">
      {items.map((item, index) => (
        <div className="simple-list-row" key={`${item}-${index}`}>
          <div className="row-title">{item}</div>
        </div>
      ))}
    </div>
  )
}

export default function NSNIntelligence() {
  const queryClient = useQueryClient()
  const [searchParams] = useSearchParams()
  const initialNsn = normalizeSearch(searchParams.get('nsn')) || DEFAULT_NSN
  const [input, setInput] = useState(initialNsn)
  const [submittedNsn, setSubmittedNsn] = useState(initialNsn)
  const [buildJobId, setBuildJobId] = useState(null)
  const [autoImportedNsns, setAutoImportedNsns] = useState({})

  const cleanNsn = normalizeSearch(submittedNsn)
  const nsnQuery = useQuery({
    queryKey: ['nsn-intelligence', cleanNsn],
    enabled: cleanNsn.length === 13,
    queryFn: async () => {
      const res = await api.get(`/api/nsn/${cleanNsn}`)
      return res.data
    },
  })
  const publogStatusQuery = useQuery({
    queryKey: ['publog-status'],
    staleTime: 60000,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      const res = await api.get('/api/nsn/publog/status')
      return res.data
    },
  })
  const buildJobQuery = useQuery({
    queryKey: ['search-job', buildJobId],
    enabled: Boolean(buildJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${buildJobId}`)
      return res.data
    },
  })

  const refreshMutation = useMutation({
    mutationFn: async ({ seedProviders = false }) => {
      const res = await api.post(`/api/nsn/${cleanNsn}/refresh`, null, {
        params: {
          run_usaspending: true,
          seed_providers: seedProviders,
          limit: 50,
        },
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['nsn-intelligence', cleanNsn] })
    },
  })

  const importPublogMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/api/nsn/${cleanNsn}/import-publog`, null, {
        params: { dry_run: false },
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['nsn-intelligence', cleanNsn] })
    },
  })

  const buildMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/api/nsn/${cleanNsn}/build-job`, null, {
        params: {
          run_usaspending: true,
          seed_providers: true,
          limit: 50,
        },
      })
      return res.data
    },
    onSuccess: (job) => {
      setBuildJobId(job.id)
    },
  })

  const seedMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/api/nsn/${cleanNsn}/seed-providers`, null, {
        params: { limit: 100 },
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['nsn-intelligence', cleanNsn] })
      queryClient.invalidateQueries({ queryKey: ['providers'] })
    },
  })

  const data = nsnQuery.data
  const identity = data?.identity || {}
  const target = data?.target || {}
  const recommendations = data?.vendor_recommendations || []
  const references = data?.references || []
  const awards = data?.award_history || {}
  const nsnAwardEvidence = data?.nsn_award_evidence || {}
  const pricing = data?.pricing || {}
  const snapshot = data?.snapshot || null
  const snapshotUsaspending = snapshot?.usaspending || null
  const sourceFreshness = data?.source_freshness || {}
  const cageProfiles = data?.cage_profiles || []
  const alternateGraph = data?.alternate_graph || {}
  const buildJob = buildJobQuery.data
  const buildJobDone = buildJob?.status === 'success'
  const buildJobFailed = buildJob?.status === 'failed'
  const awardSignalCount = Number(awards.count || 0) + Number(nsnAwardEvidence.count || 0)
  const todayContext = useMemo(() => {
    if (searchParams.get('source') !== 'today') return null
    return {
      mode: searchParams.get('mode') || 'lookup',
      title: searchParams.get('title') || '',
      solicitation: searchParams.get('sol') || '',
      nsn: normalizeSearch(searchParams.get('nsn')),
    }
  }, [searchParams])

  useEffect(() => {
    if (!buildJobDone) return
    queryClient.invalidateQueries({ queryKey: ['nsn-intelligence', cleanNsn] })
    queryClient.invalidateQueries({ queryKey: ['providers'] })
  }, [buildJobDone, cleanNsn, queryClient])

  useEffect(() => {
    if (cleanNsn.length !== 13 || !data || importPublogMutation.isPending || autoImportedNsns[cleanNsn]) return
    if (publogStatusQuery.data?.status !== 'ready') return

    const needsCatalogHelp = !data?.confidence?.has_catalog_record || !data?.confidence?.has_reference_records
    if (!needsCatalogHelp) return

    setAutoImportedNsns((current) => ({ ...current, [cleanNsn]: true }))
    importPublogMutation.mutate()
  }, [
    autoImportedNsns,
    cleanNsn,
    data,
    importPublogMutation,
    publogStatusQuery.data?.status,
  ])

  useEffect(() => {
    const prefilledNsn = normalizeSearch(searchParams.get('nsn'))
    if (!prefilledNsn || prefilledNsn === submittedNsn) return
    setInput(prefilledNsn)
    setSubmittedNsn(prefilledNsn)
  }, [searchParams, submittedNsn])

  const summaryStats = useMemo(() => ([
    { label: 'Vendor Candidates', value: numberLabel(recommendations.length), subtitle: data?.confidence?.has_vendor_recommendations ? 'Ranked by evidence' : 'Needs more evidence' },
    {
      label: 'Catalog References',
      value: numberLabel(references.length),
      subtitle: data?.confidence?.has_reference_records
        ? 'CAGE and part links'
        : publogStatusQuery.data?.status === 'ready'
          ? 'Checking the catalog package'
          : 'Catalog package not ready yet',
    },
    { label: 'Awards', value: numberLabel(awardSignalCount), subtitle: snapshotUsaspending ? `${numberLabel(snapshotUsaspending.awards_found)} refresh hits` : awardSignalCount ? 'Persisted evidence' : 'Run refresh' },
    { label: 'Unit Price Avg', value: pricing.unit_average ? money(pricing.unit_average) : 'Not available', subtitle: pricing.count ? `${numberLabel(pricing.count)} price facts` : 'No pricing yet' },
  ]), [recommendations.length, references.length, awardSignalCount, pricing.unit_average, pricing.count, data?.confidence, snapshotUsaspending, publogStatusQuery.data?.status])

  const handleSearch = (event) => {
    event.preventDefault()
    setSubmittedNsn(input)
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">NSN Intelligence</div>
          <h1 className="page-title">NSN Intelligence</h1>
          <div className="page-subtitle">
            Resolve an NSN, review vendor candidates, inspect award and pricing signals, then seed providers when the evidence is useful.
          </div>
        </div>
      </div>

      {todayContext ? (
        <Card title="Picked Up From Today" className="research-warning-box">
          <div className="row-title">
            {todayContext.mode === 'build' ? 'Recommended next step: Build intelligence' : 'Recommended next step: Review this NSN'}
          </div>
          <div className="row-subtitle">
            {[todayContext.solicitation, todayContext.title, todayContext.nsn ? `NSN ${todayContext.nsn}` : ''].filter(Boolean).join(' | ')}
          </div>
          <div className="panel-subtitle">
            We carried the NSN over from Today so you can keep researching without starting over.
          </div>
        </Card>
      ) : null}

      <Card title="Lookup">
        <form className="nsn-search-form" onSubmit={handleSearch}>
          <Input
            label="NSN"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="4110015342682"
          />
          <div className="nsn-actions">
            <Button type="submit" disabled={normalizeSearch(input).length !== 13}>Lookup</Button>
            <Button
              type="button"
              loading={buildMutation.isPending || (buildJob && !buildJobDone && !buildJobFailed)}
              disabled={cleanNsn.length !== 13 || buildMutation.isPending || (buildJob && !buildJobDone && !buildJobFailed)}
              onClick={() => buildMutation.mutate()}
            >
              Build Intelligence
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={refreshMutation.isPending}
              disabled={!data || refreshMutation.isPending}
              onClick={() => refreshMutation.mutate({ seedProviders: false })}
            >
              Refresh
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={seedMutation.isPending}
              disabled={!data || seedMutation.isPending}
              onClick={() => seedMutation.mutate()}
            >
              Seed Providers
            </Button>
          </div>
        </form>
        <div className="simple-list">
          <div className="simple-list-row">
            <div className="row-title">Lookup</div>
            <div className="row-subtitle">Loads the current NSN record, references, vendors, pricing, and any saved evidence already in the system.</div>
          </div>
          <div className="simple-list-row">
            <div className="row-title">Build Intelligence</div>
            <div className="row-subtitle">Runs the fuller pipeline for this NSN: catalog package refresh, awards research, and provider seeding.</div>
          </div>
          <div className="simple-list-row">
            <div className="row-title">Refresh</div>
            <div className="row-subtitle">Updates awards and pricing signals without running the full provider-building workflow.</div>
          </div>
          <div className="simple-list-row">
            <div className="row-title">Seed Providers</div>
            <div className="row-subtitle">Creates or updates provider candidates from the evidence already tied to this NSN.</div>
          </div>
        </div>
        {normalizeSearch(input).length > 0 && normalizeSearch(input).length !== 13 ? (
          <div className="form-hint error">Enter a 13 digit NSN.</div>
        ) : null}
      </Card>

      {nsnQuery.isLoading ? (
        <Card>
          <LoadingState label="Loading NSN intelligence..." />
        </Card>
      ) : nsnQuery.error ? (
        <EmptyState
          title="NSN lookup failed"
          subtitle={nsnQuery.error?.response?.data?.detail || nsnQuery.error.message || 'The lookup could not be completed.'}
          action={<Button onClick={() => nsnQuery.refetch()}>Retry</Button>}
        />
      ) : data ? (
        <>
          <div className="nsn-identity-band">
            <div>
              <div className="page-kicker">Resolved Item</div>
              <div className="nsn-title">{identity.item_name || 'Catalog identity not loaded'}</div>
              <div className="row-subtitle">
                {target.nsn || submittedNsn} | FSC {target.fsc || 'Unknown'} | NIIN {target.niin || 'Unknown'}
              </div>
            </div>
            <div className="nsn-status-stack">
              <StatusPill status={identity.status || 'Unknown'} />
              <StatusPill status={data.confidence?.identity || 'Unknown'} />
            </div>
          </div>

          <div className="stats-grid">
            {summaryStats.map((stat) => (
              <Card key={stat.label} className="stat-card">
                <div className="stat-label">{stat.label}</div>
                <div className="stat-value nsn-stat-value">{stat.value}</div>
                <div className="stat-subtitle">{stat.subtitle}</div>
              </Card>
            ))}
          </div>

          {(buildJob || buildMutation.data || importPublogMutation.data || refreshMutation.data || seedMutation.data) ? (
            <Card title="Last Action">
              <div className="nsn-action-result">
                {buildJob ? (
                  <div>
                    <div className="row-title">Intelligence build job</div>
                    <div className="row-subtitle">
                      {buildJob.status} | {numberLabel(buildJob.progress?.percent)}% | {buildJob.progress?.current_label || 'Queued'}
                      {buildJob.error ? ` | ${buildJob.error}` : ''}
                    </div>
                  </div>
                ) : null}
                {buildMutation.data && !buildJob ? (
                  <div>
                    <div className="row-title">Intelligence build</div>
                    <div className="row-subtitle">
                      PUB LOG {buildMutation.data.publog?.status || 'unknown'} | Snapshot #{buildMutation.data.refresh?.snapshot_id || 'pending'} | Vendors {numberLabel(buildMutation.data.summary?.vendor_recommendations?.length)}
                    </div>
                  </div>
                ) : null}
                {importPublogMutation.data ? (
                  <div>
                    <div className="row-title">Catalog package refresh</div>
                    <div className="row-subtitle">
                      Identity rows {numberLabel(importPublogMutation.data.identity_rows)} | Part rows {numberLabel(importPublogMutation.data.part_rows)}
                    </div>
                  </div>
                ) : null}
                {refreshMutation.data ? (
                  <div>
                    <div className="row-title">Refresh snapshot #{refreshMutation.data.snapshot_id}</div>
                    <div className="row-subtitle">
                      USAspending awards found: {numberLabel(refreshMutation.data.confidence?.usaspending_awards_found)}
                    </div>
                  </div>
                ) : null}
                {seedMutation.data ? (
                  <div>
                    <div className="row-title">Provider seeding</div>
                    <div className="row-subtitle">
                      Inserted {numberLabel(seedMutation.data.inserted)} | Updated {numberLabel(seedMutation.data.updated)} | Skipped {numberLabel(seedMutation.data.skipped)}
                    </div>
                  </div>
                ) : null}
                {refreshMutation.data?.summary?.award_provider_seed ? (
                  <div>
                    <div className="row-title">Awardee provider seeding</div>
                    <div className="row-subtitle">
                      Inserted {numberLabel(refreshMutation.data.summary.award_provider_seed.inserted)} | Updated {numberLabel(refreshMutation.data.summary.award_provider_seed.updated)} | Checked {numberLabel(refreshMutation.data.summary.award_provider_seed.award_rows_checked)}
                    </div>
                  </div>
                ) : null}
              </div>
            </Card>
          ) : null}

          <Card title="Vendor Recommendations">
            {recommendations.length ? (
              <div className="nsn-candidate-grid">
                {recommendations.map((vendor) => (
                  <div className="nsn-candidate" key={`${vendor.cage || vendor.company_name}`}>
                    <div className="nsn-candidate-head">
                      <div>
                        <div className="row-title">{vendor.company_name}</div>
                        <div className="row-subtitle">{vendor.cage || 'No CAGE'}{vendor.website ? ` | ${vendor.website}` : ''}</div>
                      </div>
                      <StatusPill status={vendor.confidence || 'Unknown'} />
                    </div>
                    <div className="nsn-score-line">
                      <span>Score {vendor.score}</span>
                      {vendor.provider_id ? <span>Provider #{vendor.provider_id}</span> : null}
                    </div>
                    <div className="badge-row">
                      {(vendor.roles || []).slice(0, 4).map((role) => <Badge key={role} label={role} />)}
                    </div>
                    <SectionList items={(vendor.reasons || []).slice(0, 3)} empty="No reasons recorded." />
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                title="No vendor recommendations yet"
                subtitle="Import catalog references, run refresh, or seed providers from DIBBS PDFs to build candidates."
                action={<Button loading={refreshMutation.isPending} onClick={() => refreshMutation.mutate({ seedProviders: false })}>Run Refresh</Button>}
              />
            )}
          </Card>

          <div className="nsn-two-column">
            <Card title="Alternate Part Graph">
              {(alternateGraph.part_numbers?.length || alternateGraph.related_nodes?.length || alternateGraph.cages?.length) ? (
                <div className="simple-list">
                  <div className="simple-list-row">
                    <div className="row-title">Connected Part Numbers</div>
                    <div className="row-subtitle">{numberLabel(alternateGraph.part_numbers?.length || 0)} linked part numbers</div>
                  </div>
                  {alternateGraph.actual_related_nsn_count ? (
                    <div className="simple-list-row">
                      <div className="row-title">Connected NSNs</div>
                      <div className="row-subtitle">{numberLabel(alternateGraph.actual_related_nsn_count)} resolved related NSN candidates</div>
                    </div>
                  ) : null}
                  {(alternateGraph.part_numbers || []).slice(0, 6).map((row, index) => (
                    <div className="simple-list-row" key={`${row.part_number}-${row.cage}-${index}`}>
                      <div className="row-title">{row.part_number || 'Unknown part'}{row.company_name ? ` | ${row.company_name}` : ''}</div>
                      <div className="row-subtitle">{row.cage || 'No CAGE'} | {row.relationship_type || 'reference'} | {row.source || 'PUB LOG'}</div>
                    </div>
                  ))}
                  {(alternateGraph.related_nodes || []).slice(0, 6).map((row, index) => (
                    <div className="simple-list-row" key={`${row.related_value}-${row.relationship_type}-${index}`}>
                      <div className="row-title">
                        {row.related_value || 'Related item'}
                        {row.related_item_name ? ` | ${row.related_item_name}` : ''}
                      </div>
                      <div className="row-subtitle">
                        {row.relationship_type || 'related'}
                        {row.related_fsc ? ` | FSC ${row.related_fsc}` : ''}
                        {row.notes ? ` | ${row.notes}` : ''}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState title="No alternate graph yet" subtitle="Expand PUB LOG coverage to surface more part links and related item concepts." />
              )}
            </Card>

            <Card title="Catalog References">
              {references.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>CAGE</TableHead>
                      <TableHead>Company</TableHead>
                      <TableHead>Part</TableHead>
                      <TableHead>Role</TableHead>
                      <TableHead>Source</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {references.slice(0, 12).map((row, index) => (
                      <TableRow key={`${row.cage}-${row.part_number}-${index}`}>
                        <TableCell>{row.cage || 'Unknown'}</TableCell>
                        <TableCell>{row.company_name || 'Unknown'}</TableCell>
                        <TableCell>{row.part_number || 'Unknown'}</TableCell>
                        <TableCell>{row.relationship_type || row.reference_type || 'Reference'}</TableCell>
                        <TableCell>{row.source_name || 'Catalog'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  title="No catalog references"
                  subtitle={
                    publogStatusQuery.data?.status === 'ready'
                      ? 'We checked the catalog package, but this item still does not have reference links yet.'
                      : 'The catalog package is not ready yet, so reference links have not been loaded.'
                  }
                />
              )}
            </Card>

            <Card title="Next Actions">
              <SectionList items={data.next_actions || []} empty="No next actions." />
            </Card>
          </div>

          <div className="nsn-two-column">
            <Card title="Characteristics">
              {(data.evidence || []).filter((row) => row.claim_type === 'characteristic').length ? (
                <div className="simple-list">
                  {(data.evidence || []).filter((row) => row.claim_type === 'characteristic').slice(0, 8).map((row, index) => (
                    <div className="simple-list-row" key={`${row.claim_value}-${index}`}>
                      <div className="row-title">{row.claim_value || 'Characteristic'}</div>
                      <div className="row-subtitle">{row.evidence_text || row.source_name || 'PUB LOG characteristic'}</div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="row-subtitle">No characteristics loaded yet for this NSN.</div>
              )}
            </Card>

            <Card title="Source Freshness">
              <div className="simple-list">
                <div className="simple-list-row">
                  <div className="row-title">PUB LOG</div>
                  <div className="row-subtitle">{sourceFreshness.publog_source_version || 'Not loaded'} | {sourceFreshness.catalog_updated_at || 'No catalog timestamp'}</div>
                </div>
                <div className="simple-list-row">
                  <div className="row-title">Latest Snapshot</div>
                  <div className="row-subtitle">{sourceFreshness.latest_snapshot_generated_at || 'No snapshot yet'}</div>
                </div>
                <div className="simple-list-row">
                  <div className="row-title">Source Labels</div>
                  <div className="row-subtitle">Catalog official | Awards API | Providers organization scoped</div>
                </div>
              </div>
            </Card>

            <Card title="CAGE Profiles">
              {cageProfiles.length ? (
                <div className="simple-list">
                  {cageProfiles.slice(0, 8).map((profile) => (
                    <div className="simple-list-row" key={profile.cage}>
                      <div className="row-title">{profile.cage} | {profile.company_name || profile.official_profile?.company || 'Unknown company'}</div>
                      <div className="row-subtitle">
                        {(profile.part_numbers || []).slice(0, 3).join(', ') || 'No part numbers'} | {profile.official_profile?.city || 'No city'} {profile.official_profile?.state || ''}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="row-subtitle">Run Build Intelligence to enrich CAGE profile evidence.</div>
              )}
            </Card>
          </div>

          <Card title="Historical Signals">
            <div className="nsn-history-grid">
              <div>
                <div className="row-title">Award History</div>
                <div className="row-subtitle">
                  {numberLabel(awards.count)} persisted awards | Low {money(awards.amount_low)} | High {money(awards.amount_high)}
                </div>
              </div>
              <div>
                <div className="row-title">Standalone NSN Evidence</div>
                <div className="row-subtitle">
                  {numberLabel(nsnAwardEvidence.count)} USAspending evidence rows | Low {money(nsnAwardEvidence.amount_low)} | High {money(nsnAwardEvidence.amount_high)}
                </div>
              </div>
              <div>
                <div className="row-title">Refresh Results</div>
                <div className="row-subtitle">
                  {snapshotUsaspending ? `${numberLabel(snapshotUsaspending.awards_found)} USAspending hits | ${snapshotUsaspending.history_match_label}` : 'No refresh snapshot yet.'}
                </div>
              </div>
              <div>
                <div className="row-title">Pricing</div>
                <div className="row-subtitle">
                  {numberLabel(pricing.count)} price facts | Average {pricing.unit_average ? money(pricing.unit_average) : 'Not available'}
                </div>
              </div>
            </div>
          </Card>
        </>
      ) : (
        <EmptyState title="Enter an NSN" subtitle="Start with a 13 digit National Stock Number." />
      )}
    </div>
  )
}
