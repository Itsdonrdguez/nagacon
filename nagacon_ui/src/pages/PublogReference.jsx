import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, API_BASE_URL } from '../api/client'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingState,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'

const DATASETS = [
  ['references', 'References'],
  ['master', 'Master'],
  ['interchangeability', 'Interchangeability'],
]

const MODES = [
  ['all', 'All Rows'],
  ['best_rows', 'Best Rows'],
  ['manufacturer_candidates', 'Manufacturer Candidates'],
]

const COLUMN_SETS = {
  references: {
    all: [
      'nsn',
      'part_number',
      'display_company_name',
      'cage',
      'reference_type_label',
    ],
    best_rows: [
      'nsn',
      'part_number',
      'display_company_name',
      'cage',
      'reference_type_label',
    ],
    manufacturer_candidates: [
      'display_company_name',
      'cage',
      'part_number',
      'reference_type_label',
    ],
  },
  master: [
    'nsn',
    'item_name',
    'fsc',
    'niin',
  ],
  interchangeability: [
    'nsn',
    'related_nsn',
  ],
}

function labelForColumn(column) {
  const labels = {
    nsn: 'NSN',
    compact_nsn: 'Compact NSN',
    fsc: 'FSC',
    niin: 'NIIN',
    cage: 'CAGE',
    display_company_name: 'Company',
    part_number: 'Part Number',
    company_name: 'Company',
    reference_type_label: 'Reference Type',
    relationship_type_label: 'Relationship',
    source_version: 'Source Version',
    item_name: 'Item Name',
    related_nsn: 'Related NSN',
    order_of_use: 'Order Of Use',
    claim_type: 'Claim Type',
    claim_value: 'Claim Value',
    matched_by: 'Matched By',
    confidence: 'Confidence',
  }
  return labels[column] || column.replace(/_/g, ' ')
}

function pickColumns(dataset, mode, rows) {
  const firstRow = rows[0] || {}
  const available = new Set(Object.keys(firstRow))
  const configured =
    dataset === 'references'
      ? (COLUMN_SETS.references[mode] || COLUMN_SETS.references.all)
      : (COLUMN_SETS[dataset] || [])
  const picked = configured.filter((column) => available.has(column))
  if (picked.length) return picked
  return Object.keys(firstRow).filter((key) => key !== 'dataset')
}

function buildExportUrl(format, dataset, mode, query) {
  const params = new URLSearchParams()
  params.set('dataset', dataset)
  params.set('mode', mode)
  if (query) params.set('q', query)
  return `${API_BASE_URL}/api/nsn/publog/reference/export.${format}?${params.toString()}`
}

export default function PublogReference() {
  const [dataset, setDataset] = useState('references')
  const [mode, setMode] = useState('all')
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')

  const searchQuery = useQuery({
    queryKey: ['publog-reference', dataset, mode, submittedQuery],
    queryFn: async () => {
      const res = await api.get('/api/nsn/publog/reference/search', {
        params: {
          dataset,
          mode,
          q: submittedQuery || undefined,
          limit: 100,
        },
      })
      return res.data
    },
  })

  const rows = searchQuery.data?.rows || []
  const columns = useMemo(() => {
    if (!rows.length) return []
    return pickColumns(dataset, mode, rows)
  }, [dataset, mode, rows])
  const helperText = useMemo(() => {
    if (dataset === 'interchangeability') {
      return 'Related NSN means another stock number linked to the current NSN as an alternate, substitute, or otherwise associated item in PUB LOG.'
    }
    if (dataset === 'references') {
      return 'Company names prefer the SAM registration name for the same CAGE when a SAM match is available.'
    }
    return null
  }, [dataset])

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">PUB LOG Reference</h1>
          <p className="page-subtitle">
            Search imported PUB LOG records without leaving the local workspace.
          </p>
        </div>
        <div className="row-actions">
          <Button variant="secondary" size="sm" onClick={() => { window.location.href = buildExportUrl('csv', dataset, mode, submittedQuery) }}>
            Export CSV
          </Button>
          <Button variant="secondary" size="sm" onClick={() => { window.location.href = buildExportUrl('json', dataset, mode, submittedQuery) }}>
            Export JSON
          </Button>
        </div>
      </div>

      <Card>
        <div className="toolbar" style={{ gap: 12, flexWrap: 'wrap' }}>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search NSN, part number, CAGE, company, claim..."
          />
          <Button onClick={() => setSubmittedQuery(query.trim())}>Search</Button>
        </div>
        <div className="row-actions" style={{ marginTop: 12, flexWrap: 'wrap' }}>
          {DATASETS.map(([value, label]) => (
            <Button
              key={value}
              variant={dataset === value ? 'primary' : 'secondary'}
              size="sm"
              onClick={() => setDataset(value)}
            >
              {label}
            </Button>
          ))}
          {dataset === 'references'
            ? MODES.map(([value, label]) => (
                <Button
                  key={value}
                  variant={mode === value ? 'primary' : 'secondary'}
                  size="sm"
                  onClick={() => setMode(value)}
                >
                  {label}
                </Button>
              ))
            : null}
          <Badge tone="info">{searchQuery.data?.total || 0} rows</Badge>
        </div>
        {helperText ? <div className="panel-subtitle" style={{ marginTop: 12 }}>{helperText}</div> : null}
      </Card>

      <Card>
        {searchQuery.isLoading ? (
          <LoadingState label="Loading PUB LOG reference..." />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No PUB LOG rows found"
            description="Try a different dataset or a broader search term."
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((column) => (
                  <TableHead key={column}>{labelForColumn(column)}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, index) => (
                <TableRow key={`${row.compact_nsn || row.nsn || 'row'}-${index}`}>
                  {columns.map((column) => (
                    <TableCell key={column}>{row[column] ?? ''}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
