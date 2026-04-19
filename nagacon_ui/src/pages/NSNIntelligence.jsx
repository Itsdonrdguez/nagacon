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
  const [input, setInput] = useState(DEFAULT_NSN)
  const [submittedNsn, setSubmittedNsn] = useState(DEFAULT_NSN)

  const cleanNsn = normalizeSearch(submittedNsn)
  const nsnQuery = useQuery({
    queryKey: ['nsn-intelligence', cleanNsn],
    enabled: cleanNsn.length === 13,
    queryFn: async () => {
      const res = await api.get(`/api/nsn/${cleanNsn}`)
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
      const res = await api.post(`/api/nsn/${cleanNsn}/build`, null, {
        params: {
          run_usaspending: true,
          seed_providers: true,
          limit: 50,
        },
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['nsn-intelligence', cleanNsn] })
      queryClient.invalidateQueries({ queryKey: ['providers'] })
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
  const awardSignalCount = Number(awards.count || 0) + Number(nsnAwardEvidence.count || 0)

  const summaryStats = useMemo(() => ([
    { label: 'Vendor Candidates', value: numberLabel(recommendations.length), subtitle: data?.confidence?.has_vendor_recommendations ? 'Ranked by evidence' : 'Needs more evidence' },
    { label: 'Catalog References', value: numberLabel(references.length), subtitle: data?.confidence?.has_reference_records ? 'CAGE and part links' : 'Import PUB LOG' },
    { label: 'Awards', value: numberLabel(awardSignalCount), subtitle: snapshotUsaspending ? `${numberLabel(snapshotUsaspending.awards_found)} refresh hits` : awardSignalCount ? 'Persisted evidence' : 'Run refresh' },
    { label: 'Unit Price Avg', value: pricing.unit_average ? money(pricing.unit_average) : 'Not available', subtitle: pricing.count ? `${numberLabel(pricing.count)} price facts` : 'No pricing yet' },
  ]), [recommendations.length, references.length, awardSignalCount, pricing.unit_average, pricing.count, data?.confidence, snapshotUsaspending])

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
              loading={buildMutation.isPending}
              disabled={cleanNsn.length !== 13 || buildMutation.isPending}
              onClick={() => buildMutation.mutate()}
            >
              Build Intelligence
            </Button>
            <Button
              type="button"
              variant="secondary"
              loading={importPublogMutation.isPending}
              disabled={!data || importPublogMutation.isPending}
              onClick={() => importPublogMutation.mutate()}
            >
              Import PUB LOG
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

          {(buildMutation.data || importPublogMutation.data || refreshMutation.data || seedMutation.data) ? (
            <Card title="Last Action">
              <div className="nsn-action-result">
                {buildMutation.data ? (
                  <div>
                    <div className="row-title">Intelligence build</div>
                    <div className="row-subtitle">
                      PUB LOG {buildMutation.data.publog?.status || 'unknown'} | Snapshot #{buildMutation.data.refresh?.snapshot_id || 'pending'} | Vendors {numberLabel(buildMutation.data.summary?.vendor_recommendations?.length)}
                    </div>
                  </div>
                ) : null}
                {importPublogMutation.data ? (
                  <div>
                    <div className="row-title">PUB LOG import</div>
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
            <Card title="Catalog References">
              {references.length ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>CAGE</TableHead>
                      <TableHead>Company</TableHead>
                      <TableHead>Part</TableHead>
                      <TableHead>Source</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {references.slice(0, 12).map((row, index) => (
                      <TableRow key={`${row.cage}-${row.part_number}-${index}`}>
                        <TableCell>{row.cage || 'Unknown'}</TableCell>
                        <TableCell>{row.company_name || 'Unknown'}</TableCell>
                        <TableCell>{row.part_number || 'Unknown'}</TableCell>
                        <TableCell>{row.source_name || 'Catalog'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState title="No catalog references" subtitle="Import PUB LOG reference data to populate CAGE and part-number relationships." />
              )}
            </Card>

            <Card title="Next Actions">
              <SectionList items={data.next_actions || []} empty="No next actions." />
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
