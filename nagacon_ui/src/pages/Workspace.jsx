import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, API_BASE_URL } from '../api/client'
import { EmptyState, Tabs, Badge, Card, Button, Input, LoadingState, StatusPill, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui'
import { setAsideBadgeLabel, setAsideBadgeVariant } from '../utils/badges'

const PROGRESS_OPTIONS = [
  { value: 'NEW', label: 'New' },
  { value: 'IN_PROGRESS', label: 'Reviewing' },
  { value: 'BID', label: 'Proposal Started' },
  { value: 'SUBMITTED', label: 'Submitted' },
  { value: 'NO_BID', label: 'Archived' },
]
const TASK_STATUSES = ['OPEN', 'IN_PROGRESS', 'DONE']
const SUBMISSION_STATUSES = ['DRAFT', 'SUBMITTED', 'AWARDED', 'LOST', 'NO_BID']
const AGENT_PHASE_LABELS = {
  phase_1: 'Read the Solicitation',
  phase_2: 'Reach Out and Qualify',
  phase_3: 'Prepare to Submit',
}

const AGENT_FALLBACK_LABELS = {
  missing_openai_key: 'OpenAI key missing',
  missing_openai_sdk: 'OpenAI SDK missing',
  empty_openai_response: 'OpenAI returned an empty response',
  invalid_openai_json: 'OpenAI returned invalid JSON',
  openai_quota_exceeded: 'OpenAI quota exceeded',
  openai_auth_failed: 'OpenAI authentication failed',
  openai_permission_denied: 'OpenAI permission denied',
  openai_connection_error: 'OpenAI connection error',
  openai_http_error: 'OpenAI HTTP error',
  openai_unknown_error: 'OpenAI error',
}

function formatAgentFallback(result) {
  if (!result?.fallback_reason) return ''
  const label = AGENT_FALLBACK_LABELS[result.fallback_reason] || result.fallback_reason.replace(/_/g, ' ')
  const detail = String(result.fallback_detail || '').trim()
  return detail ? `${label}: ${detail}` : label
}
const AGENT_CATALOG_FALLBACK = {
  solicitation_analyst: {
    label: 'Solicitation Analyst',
    description: 'Reads the solicitation, summarizes what is being bought, and highlights risks, gaps, and next steps.',
  },
  compliance_reviewer: {
    label: 'Compliance Reviewer',
    description: 'Reviews the loaded notice and documents, extracts requirements, and flags missing submission details.',
  },
  market_researcher: {
    label: 'Market Researcher',
    description: 'Looks at vendor leads, USAspending history, and market context to support bid decisions.',
  },
  outreach_coordinator: {
    label: 'Outreach Coordinator',
    description: 'Prepares vendor outreach grounded in the solicitation and the strongest quote targets.',
  },
  proposal_coordinator: {
    label: 'Proposal Coordinator',
    description: 'Turns tasks, quotes, and artifacts into a practical execution plan for submission.',
  },
}

const AGENT_LEGACY_KEY_MAP = {
  opportunity_analyst: 'solicitation_analyst',
  compliance_document: 'compliance_reviewer',
  vendor_research: 'market_researcher',
  email_outreach: 'outreach_coordinator',
  proposal_workspace: 'proposal_coordinator',
}

const getCanonicalAgentKey = (agentKey) => AGENT_LEGACY_KEY_MAP[String(agentKey || '').trim()] || String(agentKey || '').trim()

const getAgentMeta = (agentKey, catalog = {}) => {
  const canonicalKey = getCanonicalAgentKey(agentKey)
  return catalog[canonicalKey] || AGENT_CATALOG_FALLBACK[canonicalKey] || {
    label: canonicalKey.replace(/_/g, ' '),
    description: '',
  }
}

const formatDateTime = (value) => {
  if (!value) return '-'
  return new Date(value).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

const formatCurrency = (value) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 0,
  }).format(numeric)
}

const joinList = (values) => (values && values.length ? values.join(' | ') : '-')
const compactMeta = (parts) => parts.filter((part) => part && part !== '-').join(' | ')
const dedupeVendorPartRows = (rows, { cageField = 'cage', partField = 'part_number', nameField = 'company_name' } = {}) => {
  const grouped = new Map()
  const mergeRows = (existing, row) => {
    const existingScore = Number(existing?.confidence || existing?.score || 0)
    const nextScore = Number(row?.confidence || row?.score || 0)
    const preferred = nextScore > existingScore ? row : existing
    const fallback = preferred === row ? existing : row
    return {
      ...fallback,
      ...preferred,
      _originalIndex: existing?._originalIndex ?? row?._originalIndex ?? 0,
    }
  }
  ;(rows || []).forEach((row, index) => {
    const cage = String(row?.[cageField] || '').trim().toUpperCase()
    const part = String(row?.[partField] || '').trim().toUpperCase()
    const name = String(row?.[nameField] || row?.name || '').trim().toUpperCase()
    const keyBase = cage || name
    if (!keyBase) return
    const exactKey = `${keyBase}__${part}`
    const blankKey = `${keyBase}__`
    const candidate = { ...row, _originalIndex: index }
    if (part && grouped.has(blankKey)) {
      grouped.set(exactKey, mergeRows(grouped.get(blankKey), candidate))
      grouped.delete(blankKey)
      return
    }
    if (!part) {
      const existingConcreteKey = Array.from(grouped.keys()).find((key) => key.startsWith(`${keyBase}__`) && key !== blankKey)
      if (existingConcreteKey) {
        grouped.set(existingConcreteKey, mergeRows(grouped.get(existingConcreteKey), candidate))
        return
      }
    }
    if (grouped.has(exactKey)) {
      grouped.set(exactKey, mergeRows(grouped.get(exactKey), candidate))
      return
    }
    grouped.set(exactKey, candidate)
  })
  return Array.from(grouped.values())
}

const dedupeVendorIdentityRows = (rows = []) => {
  const grouped = new Map()
  const mergeRows = (existing, row) => {
    const existingSources = new Set(existing.source_labels || [])
    const nextSources = new Set(row.source_labels || [])
    return {
      ...existing,
      ...row,
      source_labels: Array.from(new Set([...existingSources, ...nextSources])),
      _rowIndex: existing._rowIndex,
    }
  }
  rows.forEach((row, index) => {
    const cage = String(row?.cage || '').trim().toUpperCase()
    const part = String(row?.part_number || '').trim().toUpperCase()
    const name = String(row?.company_name || row?.name || row?.manufacturer || '').trim()
    const identity = cage || name.toUpperCase()
    if (!identity) return
    const exactKey = `${identity}__${part}`
    const blankKey = `${identity}__`
    const candidate = { ...row, _rowIndex: index }
    if (part && grouped.has(blankKey)) {
      grouped.set(exactKey, mergeRows(grouped.get(blankKey), candidate))
      grouped.delete(blankKey)
      return
    }
    if (!part) {
      const existingConcreteKey = Array.from(grouped.keys()).find((key) => key.startsWith(`${identity}__`) && key !== blankKey)
      if (existingConcreteKey) {
        grouped.set(existingConcreteKey, mergeRows(grouped.get(existingConcreteKey), candidate))
        return
      }
    }
    const existing = grouped.get(exactKey)
    if (!existing) {
      grouped.set(exactKey, candidate)
      return
    }
    grouped.set(exactKey, mergeRows(existing, candidate))
  })
  return Array.from(grouped.values())
}

const mergeSupportingText = (...values) => Array.from(new Set(values.filter(Boolean).map((value) => String(value).trim()).filter(Boolean))).join(' | ')

const quoteStatusWeight = (status) => {
  switch (String(status || '').toUpperCase()) {
    case 'RECEIVED':
      return 40
    case 'REQUESTED':
      return 15
    case 'NO_BID':
      return -25
    case 'INVALID':
      return -40
    default:
      return 0
  }
}

const compareQuoteCandidates = (a, b) => {
  if ((b.recommendation_score || 0) !== (a.recommendation_score || 0)) {
    return (b.recommendation_score || 0) - (a.recommendation_score || 0)
  }
  if ((a.unit_price ?? Number.POSITIVE_INFINITY) !== (b.unit_price ?? Number.POSITIVE_INFINITY)) {
    return (a.unit_price ?? Number.POSITIVE_INFINITY) - (b.unit_price ?? Number.POSITIVE_INFINITY)
  }
  return (a.lead_time_days ?? Number.POSITIVE_INFINITY) - (b.lead_time_days ?? Number.POSITIVE_INFINITY)
}

const downloadBlob = (filename, content, type = 'text/plain;charset=utf-8') => {
  const blob = new Blob([content], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

const formatDateOnly = (value) => {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return String(value)
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

const formatOutcomeLabel = (value) => {
  if (!value) return '-'
  return String(value).replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
}

const stripRecommendationPrefix = (value) => {
  const text = String(value || '').trim()
  if (!text) return ''
  return text.replace(/^(No Bid|Do Not Bid|Needs Review|Pursue Now|Pursue With Gaps|Hold For Compliance|Hold For Capability|Bid)\s*:\s*/i, '').trim()
}

const formatGuidancePosture = (value) => {
  const key = String(value || '').trim().toLowerCase()
  const labels = {
    pursue_now: 'Ready to move',
    pursue_with_gaps: 'Move with gaps',
    hold_for_compliance: 'Needs compliance work',
    hold_for_capability: 'Needs capability review',
    do_not_bid: 'Low-confidence fit',
    research_only: 'Research only',
    needs_review: 'Needs review',
    bid: 'Ready to move',
  }
  return labels[key] || humanizeLabel(value, 'Needs review')
}

const titleCaseWords = (value) => value.replace(/\b\w+/g, (word) => {
  const upper = word.toUpperCase()
  if (['NSN', 'NAICS', 'FSC', 'PSC', 'PDF', 'RFQ', 'DIBBS', 'SAM', 'CAGE', 'POC', 'AI'].includes(upper)) return upper
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
})

const humanizeLabel = (value, fallback = 'Not set') => {
  const raw = String(value || '').trim()
  if (!raw) return fallback
  const normalized = raw.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()
  const exact = {
    no_bid: 'No bid',
    not_bid: 'No bid',
    in_progress: 'In progress',
    not_requested: 'Not requested',
    partial_success: 'Needs attention',
  }
  const key = normalized.toLowerCase().replace(/\s+/g, '_')
  if (exact[key]) return exact[key]
  return titleCaseWords(normalized)
}

const normalizeInlineText = (value) => String(value || '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim()

const formatBriefText = (value, { punctuate = true } = {}) => {
  const raw = String(value || '')
  let normalized = normalizeInlineText(raw)
  if (!normalized) return ''
  const looksCodeLike = /[_-]/.test(raw) || /^[A-Z0-9 ]+$/.test(normalized)
  if (looksCodeLike) {
    const acronyms = new Set(['NSN', 'NAICS', 'FSC', 'PSC', 'PR', 'RFQ', 'DIBBS', 'SAM', 'PDF', 'POC', 'CAGE', 'FOB', 'USASPENDING'])
    normalized = normalized
      .split(' ')
      .map((word) => {
        const upper = word.toUpperCase()
        if (acronyms.has(upper)) return upper === 'USASPENDING' ? 'USAspending' : upper
        return word.toLowerCase()
      })
      .join(' ')
  }
  const leading = normalized.charAt(0).toUpperCase() + normalized.slice(1)
  if (!punctuate || /[.!?:;]$/.test(leading)) return leading
  return `${leading}.`
}

const formatBriefList = (values, options) => Array.from(new Set((values || []).map((item) => formatBriefText(item, options)).filter(Boolean)))
const normalizeAnalysisList = (values) => Array.from(
  new Set(
    (values || [])
      .map((item) => {
        if (!item) return ''
        if (typeof item === 'string') return formatBriefText(item)
        if (typeof item === 'object') {
          return formatBriefText(item.detail || item.message || item.label || item.title || '')
        }
        return formatBriefText(String(item))
      })
      .filter(Boolean)
  )
)

const getDocumentStatusLabel = (file) => {
  const raw = String(file?.processing_status || '').toLowerCase()
  if (file?.review_required) return 'Needs Review'
  if (raw === 'failed') return 'Failed'
  if (raw === 'processing') return 'Processing'
  if (raw === 'completed' || file?.has_parsed_metadata) return 'Completed'
  if (raw === 'downloaded' || file?.file_path) return 'Downloaded'
  if (raw === 'skipped') return 'Completed'
  return 'Pending'
}

const formatCodeValue = (value) => {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const digitsOnly = raw.replace(/\D+/g, '')
  if (digitsOnly.length === 13) {
    return `${digitsOnly.slice(0, 4)}-${digitsOnly.slice(4, 6)}-${digitsOnly.slice(6, 9)}-${digitsOnly.slice(9)}`
  }
  return raw.replace(/\s{2,}/g, ' ')
}

const humanizeAwardeeSignal = (value) => {
  const raw = String(value || '').trim()
  if (!raw) return ''

  const assignmentMatch = raw.match(/^([a-z_]+)=(.+)$/i)
  if (assignmentMatch) {
    const key = assignmentMatch[1].toLowerCase()
    const assignedValue = assignmentMatch[2].trim()
    if (key === 'cage') return `CAGE: ${formatCodeValue(assignedValue)}`
    if (key === 'nsn') return `NSN: ${formatCodeValue(assignedValue)}`
    if (key === 'fsc_context') return `FSC: ${formatCodeValue(assignedValue)}`
    if (key === 'solicitation') return `Solicitation reference: ${formatCodeValue(assignedValue)}`
    return `${formatBriefText(key, { punctuate: false })}: ${formatCodeValue(assignedValue)}`
  }

  const exactMappings = {
    approved_source_seed: 'Matched to an approved source.',
    approved_source_vendor_gate_passed: 'Passed approved-source screening.',
    strict_seedable_product_vendor: 'Strong product-history match for seeding.',
    seedable_product_vendor: 'Product-history match is available.',
    product_like_vendor: 'Award history looks product-related.',
    service_like_vendor: 'Award history looks service-related.',
    exact_nsn_match: 'Exact NSN match found.',
  }
  if (exactMappings[raw]) return exactMappings[raw]

  return formatBriefText(raw)
}

const formatAwardeeSignalList = (values) => Array.from(new Set((values || []).map(humanizeAwardeeSignal).filter(Boolean)))

const formatAwardAmount = (value) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) return 'Amount not reported'
  return formatCurrency(numeric)
}

const formatDetailLine = (label, value) => {
  if (value === null || value === undefined || value === '') return ''
  const safeValue = String(value).trim()
  if (!safeValue || safeValue === '-') return ''
  return `${label}: ${safeValue}`
}

const factValue = (facts, key, fallback = '') => {
  const value = facts?.[key]?.value
  if (value === null || value === undefined || value === '') return fallback
  return value
}

const formatWorkspaceTaskType = (taskType, isSamOpportunity = false) => {
  const raw = String(taskType || '').trim().toUpperCase()
  if (!raw) return 'Task'
  if (isSamOpportunity) {
    const labels = {
      NOTICE_REVIEW: 'Notice Review',
      SCOPE_REVIEW: 'Scope Review',
      PAST_PERFORMANCE: 'Past Performance',
      CO_OUTREACH: 'CO Outreach',
      COMPLIANCE_STEP: 'Compliance Step',
      COMPLIANCE_REVIEW: 'Compliance Review',
      FINAL_REVIEW: 'Final Review',
    }
    if (labels[raw]) return labels[raw]
  }
  return humanizeLabel(raw, 'Task')
}

const BriefDetailsBox = ({ title, items, emptyMessage = 'No details are available yet.' }) => {
  const lines = items.filter(Boolean)
  return (
    <div className="artifact-note-box">
      <div className="row-title">{title}</div>
      <div className="artifact-brief-lines">
        {(lines.length ? lines : [emptyMessage]).map((item, index) => (
          <div key={`${title}-${index}`} className="artifact-brief-line">{item}</div>
        ))}
      </div>
    </div>
  )
}

const StructuredList = ({ title, items, emptyMessage }) => (
  <div className="artifact-section">
    <div className="row-title">{title}</div>
    <div className="artifact-list">
      {(items.length ? items : [emptyMessage]).map((item, index) => (
        <div key={`${title}-${index}`} className="artifact-list-item">{item}</div>
      ))}
    </div>
  </div>
)

export default function Workspace() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [pipelineForm, setPipelineForm] = useState({
    owner: '',
    priority: '',
    probability_of_win: '',
    target_submit_date: '',
    notes: '',
  })
  const [newTaskForm, setNewTaskForm] = useState({
    task_type: 'FOLLOW_UP',
    due_at: '',
    notes: '',
  })
  const [submissionForm, setSubmissionForm] = useState({
    status: 'DRAFT',
    submitted_at: '',
    submitted_unit_price: '',
    submitted_vendor_cage: '',
    submitted_vendor_name: '',
    planned_vendor_quote_id: '',
    planned_vendor_cage: '',
    planned_vendor_name: '',
    awarded_at: '',
    award_amount: '',
    winning_vendor_cage: '',
    winning_vendor_name: '',
    outcome_summary: '',
    notes: '',
  })
  const [checklistDraft, setChecklistDraft] = useState([])
  const [newChecklistItem, setNewChecklistItem] = useState('')
  const [emailDraft, setEmailDraft] = useState({ subject: '', body: '' })
  const [coEmailDraft, setCoEmailDraft] = useState({ subject: '', body: '' })
  const [selectedFileId, setSelectedFileId] = useState(null)
  const [activeIntakeJobId, setActiveIntakeJobId] = useState(null)
  const [quoteFilter, setQuoteFilter] = useState('all')
  const [activeTab, setActiveTab] = useState(0)
  const [secondaryDataReady, setSecondaryDataReady] = useState(false)
  const [isCompactWorkspace, setIsCompactWorkspace] = useState(() => {
    if (typeof window === 'undefined') return false
    return window.matchMedia('(max-width: 720px)').matches
  })

  const tabIndexes = {
    overview: 0,
    vendors: 1,
    documents: 2,
    submissionPackage: 3,
    submission: 4,
  }
  const requestedTab = String(searchParams.get('tab') || '').trim().toLowerCase()

  const needsVendorData = activeTab === tabIndexes.overview || activeTab === tabIndexes.vendors || activeTab === tabIndexes.submissionPackage || activeTab === tabIndexes.submission
  const needsDocumentData = activeTab === tabIndexes.overview || activeTab === tabIndexes.documents || activeTab === tabIndexes.submissionPackage
  const needsNsnData = activeTab === tabIndexes.vendors || activeTab === tabIndexes.submissionPackage

  const workspaceQuery = useQuery({
    queryKey: ['workspace', id],
    queryFn: async () => {
      const res = await api.get(`/api/workspace/summary?opp_id=${id}`)
      return res.data
    },
    enabled: !!id,
    retry: 1,
    staleTime: 120000,
    refetchOnWindowFocus: false,
  })

  useEffect(() => {
    if (!workspaceQuery.isSuccess) {
      setSecondaryDataReady(false)
      return
    }
    const timer = window.setTimeout(() => setSecondaryDataReady(true), 150)
    return () => window.clearTimeout(timer)
  }, [workspaceQuery.isSuccess, id])

  useEffect(() => {
    if (typeof window === 'undefined') return undefined
    const mediaQuery = window.matchMedia('(max-width: 720px)')
    const updateMatch = () => setIsCompactWorkspace(mediaQuery.matches)
    updateMatch()
    mediaQuery.addEventListener('change', updateMatch)
    return () => mediaQuery.removeEventListener('change', updateMatch)
  }, [])

  const pipelineQuery = useQuery({
    queryKey: ['pipeline-by-opp', id],
    queryFn: async () => {
      const res = await api.get(`/api/pipeline/by-opportunity/${id}`)
      return res.data
    },
    enabled: !!id,
    retry: false,
    staleTime: 30000,
    refetchOnWindowFocus: false,
  })
  const agentRunsQuery = useQuery({
    queryKey: ['workspace-agent-runs', id],
    queryFn: async () => {
      const res = await api.get('/api/workspace/agent-runs', { params: { opp_id: id } })
      return res.data
    },
    enabled: !!id && secondaryDataReady && activeTab === tabIndexes.overview,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })

  const filesQuery = useQuery({
    queryKey: ['workspace-files', id],
    queryFn: async () => {
      const res = await api.get('/api/files/list', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id && secondaryDataReady && needsDocumentData,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })
  const fileInsightsQuery = useQuery({
    queryKey: ['workspace-file-insights', selectedFileId],
    queryFn: async () => {
      const res = await api.get(`/api/files/${selectedFileId}/insights`)
      return res.data
    },
    enabled: !!selectedFileId && activeTab === tabIndexes.documents,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })
  const vendorLeadsQuery = useQuery({
    queryKey: ['vendor-leads', id],
    queryFn: async () => {
      const res = await api.get('/api/vendors/leads', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id && secondaryDataReady && needsVendorData,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })
  const vendorQuotesQuery = useQuery({
    queryKey: ['vendor-quotes', id],
    queryFn: async () => {
      const res = await api.get('/api/vendors/quotes', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id && secondaryDataReady && needsVendorData,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })
  const usaspendingResearchQuery = useQuery({
    queryKey: ['workspace-usaspending', id],
    queryFn: async () => {
      const res = await api.get('/api/workspace/vendors/usaspending', { params: { opp_id: id } })
      return res.data
    },
    enabled: false,
    retry: false,
  })
  const nsnIntelligenceQuery = useQuery({
    queryKey: ['workspace-nsn-intelligence', id],
    queryFn: async () => {
      const res = await api.get('/api/workspace/intelligence/nsn', { params: { opp_id: id } })
      return res.data
    },
    enabled: !!id && secondaryDataReady && needsNsnData,
    retry: false,
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })

  const ensurePipelineMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/api/pipeline/by-opportunity/${id}`)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-by-opp', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })

  const updatePipelineMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.patch(`/api/pipeline/${payload.id}`, payload.body)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['pipeline-by-opp', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })

  const downloadPdfsMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/search-jobs', {
        kind: 'workspace_intake',
        opportunity_id: Number(id),
        download_documents: true,
        run_usaspending: true,
      })
      return res.data
    },
    onSuccess: (data) => {
      setActiveIntakeJobId(data.id)
    },
  })
  const parseFileMutation = useMutation({
    mutationFn: async (fileId) => {
      const res = await api.post(`/api/files/parse/${fileId}`)
      return res.data
    },
    onSuccess: (_data, fileId) => {
      setSelectedFileId(fileId)
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-files', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-file-insights', fileId] })
    },
  })

  const generateVendorsMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/vendors', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-by-opp', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-usaspending', id] })
    },
  })

  const intakeJobQuery = useQuery({
    queryKey: ['workspace-intake-job', activeIntakeJobId],
    enabled: Boolean(activeIntakeJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 3000
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${activeIntakeJobId}`)
      return res.data
    },
    refetchOnWindowFocus: false,
  })
  const activeIntakeJob = intakeJobQuery.data
  const isIntakeRunning = activeIntakeJob && !['success', 'failed'].includes(activeIntakeJob.status)
  const intakeDownloadStep = activeIntakeJob?.result?.steps?.find((step) => step?.name === 'download_documents')?.output || null
  const dibbsSourceUnavailable = intakeDownloadStep?.source_unavailable?.source === 'DIBBS'
    ? intakeDownloadStep.source_unavailable
    : null

  const runIntakeMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/search-jobs', {
        kind: 'workspace_intake',
        opportunity_id: Number(id),
        download_documents: true,
        run_usaspending: true,
      })
      return res.data
    },
    onSuccess: (data) => {
      setActiveIntakeJobId(data.id)
    },
  })

  useEffect(() => {
    if (activeIntakeJob?.status !== 'success') return
    queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-by-opp', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-files', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-usaspending', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-nsn-intelligence', id] })
  }, [activeIntakeJob?.status, activeIntakeJob?.completed_at])

  const workspaceParseMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/parse', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['pipeline-by-opp', id] })
    },
  })
  const generateChecklistMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/checklist', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const generateEmailMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/email', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-agent-runs', id] })
    },
  })
  const generateCoEmailMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/co-email', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-agent-runs', id] })
    },
  })
  const generateResearchBriefMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/research-brief', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const runAgentMutation = useMutation({
    mutationFn: async (agentKey) => {
      const res = await api.post('/api/workspace/agents/run', {
        opportunity_id: Number(id),
        agent_key: agentKey,
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const runAgentPhaseMutation = useMutation({
    mutationFn: async (phase) => {
      const res = await api.post('/api/workspace/agents/run-phase', {
        opportunity_id: Number(id),
        phase,
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const seedUsaspendingMutation = useMutation({
    mutationFn: async (seedMode = 'product_only') => {
      const res = await api.post('/api/workspace/vendors/usaspending/seed', {
        opportunity_id: Number(id),
        seed_mode: seedMode,
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const runNsnIntelligenceMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/intelligence/nsn/run', {
        opportunity_id: Number(id),
        seed_awardees: true,
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace-nsn-intelligence', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace-usaspending', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const targetedEmailMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/workspace/generate/email-targeted', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const sendArtifactEmailMutation = useMutation({
    mutationFn: async (artifactId) => {
      const res = await api.post(`/api/workspace/artifacts/${artifactId}/send`)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const outreachLogMutation = useMutation({
    mutationFn: async ({ artifactId, body }) => {
      const res = await api.post(`/api/workspace/artifacts/${artifactId}/outreach-log`, body)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const promoteVendorLeadMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/workspace/vendors/promote', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const seedQuotesMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/vendors/quotes/seed', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const upsertVendorQuoteMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/vendors/quotes/upsert', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const logQuoteFollowUpMutation = useMutation({
    mutationFn: async ({ quoteId, notes }) => {
      const res = await api.post(`/api/vendors/quotes/${quoteId}/follow-up`, {
        opportunity_id: Number(id),
        notes,
      })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })
  const restoreArtifactMutation = useMutation({
    mutationFn: async ({ artifactId, versionIndex }) => {
      const res = await api.post(`/api/workspace/artifacts/${artifactId}/restore`, { version_index: versionIndex })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      setSelectedArtifactCompare(null)
    },
  })
  const createTaskMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/workspace/tasks', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      setNewTaskForm({ task_type: 'FOLLOW_UP', due_at: '', notes: '' })
    },
  })
  const updateTaskMutation = useMutation({
    mutationFn: async ({ taskId, body }) => {
      const res = await api.patch(`/api/workspace/tasks/${taskId}`, body)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const updateArtifactMutation = useMutation({
    mutationFn: async ({ artifactId, body }) => {
      const res = await api.patch(`/api/workspace/artifacts/${artifactId}`, body)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const saveSubmissionMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.post('/api/submissions/upsert', payload)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const generateSubmissionPackageMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/submission-package', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
    },
  })
  const refreshPartFinderMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post(`/api/parts/opportunity/${id}/refresh`)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-leads', id] })
      queryClient.invalidateQueries({ queryKey: ['vendor-quotes', id] })
    },
  })

  const data = workspaceQuery.data
  const opp = data?.opportunity || {}
  const files = filesQuery.data || data?.files || []
  const hasRealDocuments = files.some((file) => String(file?.file_type || '').toUpperCase() !== 'PDF_FALLBACK_SNAPSHOT')
  const visibleFiles = hasRealDocuments
    ? files.filter((file) => String(file?.file_type || '').toUpperCase() !== 'PDF_FALLBACK_SNAPSHOT')
    : files
  const opportunitySource = String(opp.source || '').toUpperCase()
  const isSamOpportunity = opportunitySource === 'SAM'
  const isDibbsOpportunity = opportunitySource === 'DIBBS'
  useEffect(() => {
    if (!requestedTab) return
    const dibbsTabMap = {
      overview: 0,
      'sources-quotes': 1,
      'rfq-package': 2,
      'submission-package': 3,
      submission: 4,
    }
    const samTabMap = {
      overview: 0,
      planning: 1,
      compliance: 2,
      'market-intelligence': 3,
      submission: 4,
    }
    const nextIndex = (isDibbsOpportunity ? dibbsTabMap : samTabMap)[requestedTab]
    if (Number.isInteger(nextIndex) && nextIndex !== activeTab) {
      setActiveTab(nextIndex)
    }
  }, [requestedTab, isDibbsOpportunity])

  useEffect(() => {
    const dibbsKeys = ['overview', 'sources-quotes', 'rfq-package', 'submission-package', 'submission']
    const samKeys = ['overview', 'planning', 'compliance', 'market-intelligence', 'submission']
    const keys = isDibbsOpportunity ? dibbsKeys : samKeys
    const nextKey = keys[activeTab] || 'overview'
    if (searchParams.get('tab') === nextKey) return
    const nextParams = new URLSearchParams(searchParams)
    nextParams.set('tab', nextKey)
    setSearchParams(nextParams, { replace: true })
  }, [activeTab, isDibbsOpportunity, searchParams, setSearchParams])
  const parsedSummary = data?.parsed_summary || {}
  const normalizedFacts = data?.normalized_facts || {}
  const workspaceRecommendation = data?.recommendation || data?.analysis?.recommendation || {}
  const procurementProfile = data?.procurement_profile || {}
  const normalizedPoc = normalizedFacts.poc || {}
  const pipeline = pipelineQuery.data || data?.pipeline_item || null
  const artifacts = data?.artifacts || []
  const tasks = data?.tasks || []
  const submission = data?.submission || null
  const vendorLeads = dedupeVendorPartRows(vendorLeadsQuery.data || [])
  const vendorQuotes = dedupeVendorPartRows(vendorQuotesQuery.data || [])
  const usaspendingVendors = usaspendingResearchQuery.data?.likely_vendors || []
  const usaspendingHistoryMatchLabel = usaspendingResearchQuery.data?.history_match_label || ''
  const usaspendingHistoryMatchQueryLabel = usaspendingResearchQuery.data?.history_match_query_label || ''
  const usaspendingHistoryMatchSource = usaspendingResearchQuery.data?.history_match_source || 'none'
  const researchProfile = usaspendingResearchQuery.data?.research_profile || data?.research_profile || {}
  const publogReference = data?.publog_reference || {}
  const publogManufacturerCandidates = dedupeVendorPartRows(publogReference.manufacturer_candidates || [])
  const checklistArtifact = artifacts.find((artifact) => artifact.artifact_type === 'CHECKLIST') || null
  const complianceMatrixArtifact = artifacts.find((artifact) => artifact.artifact_type === 'COMPLIANCE_MATRIX') || null
  const emailArtifact =
    artifacts.find((artifact) => artifact.artifact_type === 'EMAIL_DRAFT')
    || artifacts.find((artifact) => artifact.artifact_type === 'OUTREACH_PLAN')
    || null
  const coEmailArtifact = artifacts.find((artifact) => artifact.artifact_type === 'CO_EMAIL_DRAFT') || null
  const vendorListArtifact = artifacts.find((artifact) => artifact.artifact_type === 'VENDOR_LIST') || null
  const researchBriefArtifact = artifacts.find((artifact) => artifact.artifact_type === 'RESEARCH_BRIEF') || null
  const opportunityAnalysisArtifact = artifacts.find((artifact) => artifact.artifact_type === 'OPPORTUNITY_ANALYSIS') || null
  const complianceArtifact = artifacts.find((artifact) => artifact.artifact_type === 'COMPLIANCE_BRIEF') || null
  const vendorResearchArtifact = artifacts.find((artifact) => artifact.artifact_type === 'VENDOR_RESEARCH') || null
  const submissionPackageArtifact = artifacts.find((artifact) => artifact.artifact_type === 'SUBMISSION_PACKAGE') || null
  const partFinderArtifact = artifacts.find((artifact) => artifact.artifact_type === 'PART_FINDER') || null
  const partFinder = partFinderArtifact?.content_json?.part_finder || {}
  const partFinderPart = partFinder.part || {}
  const partFinderProviders = dedupeVendorPartRows(partFinder.providers || [], { nameField: 'name' })
  const partFinderAwardees = partFinder.awardees || []
  const partFinderWbparts = partFinder.wbparts || {}
  const partFinderWbpartsCrossReferences = partFinderWbparts.cross_references || []
  const partFinderWbpartsAlternates = partFinderWbparts.part_alternates || []
  const partFinderWbpartsDemandHistory = partFinderWbparts.demand_history || []
  const packagePriceHistory = submissionPackageArtifact?.content_json?.price_history || {}
  const nsnIntelligence =
    nsnIntelligenceQuery.data
    || submissionPackageArtifact?.content_json?.nsn_intelligence
    || researchBriefArtifact?.content_json?.nsn_intelligence
    || {}
  const nsnTarget = nsnIntelligence.target || {}
  const nsnHistory = nsnIntelligence.history || {}
  const nsnPricing = nsnIntelligence.pricing || {}
  const nsnVendorProfiles = nsnIntelligence.vendor_profiles || []
  const nsnSamValidation = nsnIntelligence.sam_contract_awards || {}
  const nsnAwardHistory = nsnIntelligence.award_history || {}
  const nsnAwardConfidence = nsnAwardHistory.confidence_counts || {}
  const storedAwardHistoryRows = nsnAwardHistory.top_awards || []
  const storedAwardees = nsnAwardHistory.top_awardees || []
  const recommendationSupplierEvidence = workspaceRecommendation?.supplier_evidence || {}
  const recommendationSupplierCandidates = recommendationSupplierEvidence?.top_candidates || []
  const sourcingCandidates = (() => {
    const grouped = new Map()

    const ensureCandidate = (identityKey, seed = {}) => {
      const existing = grouped.get(identityKey)
      if (existing) return existing
      const next = {
        identityKey,
        leadId: null,
        company_name: '',
        cage: '',
        part_number: '',
        status: '',
        candidate_quality: '',
        sourceTags: [],
        contact: {},
        provider_item: '',
        why: '',
        hasLead: false,
        ...seed,
      }
      grouped.set(identityKey, next)
      return next
    }

    vendorLeads.forEach((lead) => {
      const cage = String(lead.cage || '').trim().toUpperCase()
      const part = String(lead.part_number || '').trim().toUpperCase()
      const name = String(lead.company_name || '').trim()
      const identityKey = `${cage || name.toUpperCase()}__${part}`
      if (!identityKey || identityKey === '__') return
      const entry = ensureCandidate(identityKey)
      entry.leadId = lead.id
      entry.hasLead = true
      entry.company_name = entry.company_name || lead.company_name || ''
      entry.cage = entry.cage || lead.cage || ''
      entry.part_number = entry.part_number || lead.part_number || ''
      entry.status = lead.status || entry.status
      entry.provider_item = entry.provider_item || lead.provider_item || ''
      entry.why = mergeSupportingText(entry.why, lead.notes)
      entry.contact = {
        website: lead.provider_website || entry.contact.website || '',
        email: lead.provider_email || entry.contact.email || '',
        phone: lead.provider_phone || entry.contact.phone || '',
      }
      entry.sourceTags = Array.from(new Set([...entry.sourceTags, lead.source_label || formatBriefText(lead.source_type || 'Vendor Lead', { punctuate: false })]))
    })

    publogManufacturerCandidates.forEach((candidate) => {
      const cage = String(candidate.cage || '').trim().toUpperCase()
      const part = String(candidate.part_number || '').trim().toUpperCase()
      const name = String(candidate.company_name || candidate.candidate_label || '').trim()
      const identityKey = `${cage || name.toUpperCase()}__${part}`
      if (!identityKey || identityKey === '__') return
      const entry = ensureCandidate(identityKey, {
        company_name: candidate.company_name || candidate.candidate_label || '',
        cage: candidate.cage || '',
        part_number: candidate.part_number || '',
        candidate_quality: candidate.candidate_quality || '',
      })
      entry.company_name = entry.company_name || candidate.company_name || candidate.candidate_label || ''
      entry.cage = entry.cage || candidate.cage || ''
      entry.part_number = entry.part_number || candidate.part_number || ''
      entry.candidate_quality = entry.candidate_quality || candidate.candidate_quality || ''
      entry.why = mergeSupportingText(
        entry.why,
        compactMeta([
          candidate.relationship_type_label || '',
          candidate.reference_type_label || '',
          candidate.source_version ? `Version ${candidate.source_version}` : '',
        ]),
      )
      entry.sourceTags = Array.from(new Set([...entry.sourceTags, 'PUB LOG']))
    })

    return Array.from(grouped.values()).sort((left, right) => {
      if (left.hasLead !== right.hasLead) return left.hasLead ? -1 : 1
      const leftPreferred = left.candidate_quality === 'preferred' ? 1 : 0
      const rightPreferred = right.candidate_quality === 'preferred' ? 1 : 0
      if (leftPreferred !== rightPreferred) return rightPreferred - leftPreferred
      return String(left.company_name || left.cage || '').localeCompare(String(right.company_name || right.cage || ''))
    })
  })()
  const analysisAssessment =
    stripRecommendationPrefix(opportunityAnalysisArtifact?.content_json?.executive_assessment)
    || stripRecommendationPrefix(workspaceRecommendation?.summary)
    || null
  const analysisBidPosture =
    opportunityAnalysisArtifact?.content_json?.bid_posture
    || workspaceRecommendation?.bid_posture
    || null
  const analysisReasons = formatBriefList(opportunityAnalysisArtifact?.content_json?.reasons || workspaceRecommendation?.reasons || [])
  const analysisStrengths = formatBriefList(opportunityAnalysisArtifact?.content_json?.strengths || workspaceRecommendation?.strengths || [])
  const analysisBlockers = formatBriefList(opportunityAnalysisArtifact?.content_json?.blockers || workspaceRecommendation?.blockers || [])
  const analysisNextActions = formatBriefList(
    opportunityAnalysisArtifact?.content_json?.recommended_next_actions
    || workspaceRecommendation?.next_actions
    || []
  )
  const complianceFacts = complianceArtifact?.content_json?.extracted_facts || []
  const complianceMissingInfo = complianceArtifact?.content_json?.missing_information || []
  const complianceReviewFlags = complianceArtifact?.content_json?.review_flags || []
  const complianceVendorAsks = complianceArtifact?.content_json?.vendor_request_items || []
  const emailVendorAsks = emailArtifact?.content_json?.vendor_request_items || complianceVendorAsks
  const complianceFields = complianceArtifact?.content_json?.compliance_fields || {}
  const samDocumentSet = complianceArtifact?.content_json?.document_set || {}
  const samDocumentInventory = samDocumentSet.document_inventory || []
  const samAmendments = samDocumentSet.amendment_tracker || []
  const samMergedFields = samDocumentSet.merged_fields || {}
  const samConflictFlags = samDocumentSet.conflict_flags || []
  const samScopeMap = samDocumentSet.scope_map || {}
  const samEvaluationFactors = complianceArtifact?.content_json?.evaluation_factors || samDocumentSet.evaluation_factors || []
  const samRequiredAttachments = complianceArtifact?.content_json?.required_attachments || samDocumentSet.required_attachments || []
  const samServiceSignals = samDocumentSet.service_signals || {}
  const pastPerformanceMap = data?.past_performance_map || {}
  const pastPerformanceMatches = pastPerformanceMap.matches || []
  const pastPerformanceGaps = pastPerformanceMap.coverage_gaps || []
  const factSolicitation = factValue(normalizedFacts, 'solicitation_number', opp.solicitation_number || '')
  const factNsn = factValue(normalizedFacts, 'nsn', parsedSummary.nsn || researchProfile.nsn || '')
  const factNomenclature = factValue(normalizedFacts, 'nomenclature', parsedSummary.nomenclature || researchProfile.nomenclature || '')
  const factQuantity = factValue(normalizedFacts, 'quantity_display', [complianceFields.quantity, complianceFields.unit_of_issue].filter(Boolean).join(' '))
  const factReturnBy = factValue(normalizedFacts, 'return_by', complianceFields.return_by || opp.due_at || '')
  const factPrNumber = factValue(normalizedFacts, 'pr_number', complianceFields.pr_number || '')
  const factSetAside = factValue(normalizedFacts, 'set_aside', complianceFields.set_aside_hint || opp.set_aside_type || '')
  const factSubmissionOffice = factValue(normalizedPoc, 'submission_office', complianceFields.submission_office_hint || '')
  const factSourceFile = factValue(normalizedFacts, 'source_file', complianceFields.source_file || '')
  const factFsc = factValue(normalizedFacts, 'fsc', opp.fsc_code || opp.fsc || '')
  const factNaics = factValue(normalizedFacts, 'naics', opp.naics_code || opp.naics || '')
  const factDeliveryDays = factValue(normalizedFacts, 'delivery_days', complianceFields.delivery_days || '')
  const factFobTerms = factValue(normalizedFacts, 'fob_terms', complianceFields.fob_terms || '')
  const factPackaging = factValue(normalizedFacts, 'packaging', complianceFields.packaging_standard || '')
  const complianceActionItems = Array.from(
    new Set(
      (
        complianceArtifact?.content_json?.required_actions?.length
          ? complianceArtifact?.content_json?.required_actions
          : complianceArtifact?.content_json?.submission_requirements?.length
            ? complianceArtifact?.content_json?.submission_requirements
            : complianceFields.clauses_or_requirements || []
      ).filter(Boolean)
    )
  )
  const complianceNeedsReview = Array.from(
    new Set(
      [
        ...complianceMissingInfo,
        ...complianceReviewFlags,
        ...((complianceArtifact?.content_json?.missing_documents) || []),
      ].filter(Boolean)
    )
  )
  const outreachPoc = emailArtifact?.content_json?.solicitation_poc || {}
  const coPoc = coEmailArtifact?.content_json?.solicitation_poc || normalizedPoc || {}
  const bestWorkspaceFile = [...files]
    .sort((a, b) => {
      const aScore = (a.has_extracted_text ? 2 : 0) + (a.has_parsed_metadata ? 1 : 0)
      const bScore = (b.has_extracted_text ? 2 : 0) + (b.has_parsed_metadata ? 1 : 0)
      if (bScore !== aScore) return bScore - aScore
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
      return bTime - aTime
    })[0] || null
  const quoteComparison = [...vendorQuotes]
    .map((quote) => {
      const status = String(quote.status || '').toUpperCase()
      const hasPrice = Number.isFinite(Number(quote.unit_price))
      const hasLeadTime = Number.isFinite(Number(quote.lead_time_days))
      const hasEmail = Boolean(quote.email)
      const recommendationScore =
        quoteStatusWeight(status)
        + (hasPrice ? 35 : 0)
        + (hasLeadTime ? 20 : 0)
        + (hasEmail ? 5 : 0)
        - (hasPrice ? Number(quote.unit_price || 0) / 1000 : 0)
        - (hasLeadTime ? Number(quote.lead_time_days || 0) / 2 : 0)
      return {
        ...quote,
        normalized_status: status || 'NOT_REQUESTED',
        hasPrice,
        hasLeadTime,
        hasEmail,
        recommendation_score: Math.round(recommendationScore * 10) / 10,
      }
    })
    .sort(compareQuoteCandidates)
  const quoteFollowUpSummary = vendorQuotes.reduce((acc, quote) => {
    const status = String(quote.status || '').toUpperCase()
    acc.total += 1
    if (quote.follow_up_due) acc.due += 1
    if (status === 'REQUESTED') acc.requested += 1
    else if (status === 'RECEIVED') acc.received += 1
    else if (status === 'NOT_REQUESTED' || !status) acc.notRequested += 1
    return acc
  }, { total: 0, due: 0, requested: 0, received: 0, notRequested: 0 })
  const visibleVendorQuotes = vendorQuotes.filter((quote) => {
    const status = String(quote.status || '').toUpperCase()
    if (quoteFilter === 'due') return Boolean(quote.follow_up_due)
    if (quoteFilter === 'requested') return status === 'REQUESTED'
    if (quoteFilter === 'received') return status === 'RECEIVED'
    if (quoteFilter === 'not_requested') return status === 'NOT_REQUESTED' || !status
    return true
  })
  const recommendedQuote = quoteComparison.find((quote) => quote.normalized_status === 'RECEIVED' && quote.hasPrice) || quoteComparison[0] || null
  const selectedQuote = quoteComparison.find((quote) => String(quote.id) === String(submissionForm.planned_vendor_quote_id || '')) || null
  const packageVendor = selectedQuote || recommendedQuote || null
  const packageDocuments = [...visibleFiles]
    .sort((a, b) => {
      const aSnapshotPenalty = String(a.file_type || '').toUpperCase() === 'PDF_FALLBACK_SNAPSHOT' ? 1 : 0
      const bSnapshotPenalty = String(b.file_type || '').toUpperCase() === 'PDF_FALLBACK_SNAPSHOT' ? 1 : 0
      if (aSnapshotPenalty !== bSnapshotPenalty) return aSnapshotPenalty - bSnapshotPenalty
      const aScore = (a.has_extracted_text ? 2 : 0) + (a.has_parsed_metadata ? 1 : 0)
      const bScore = (b.has_extracted_text ? 2 : 0) + (b.has_parsed_metadata ? 1 : 0)
      if (bScore !== aScore) return bScore - aScore
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0
      return bTime - aTime
    })
  const packageQuantity = factQuantity || '-'
  const packageSubmissionFacts = [
    { label: 'Solicitation', value: factSolicitation || '-' },
    { label: 'NSN', value: factNsn || '-' },
    { label: 'Quantity', value: packageQuantity },
    { label: 'Return By', value: formatDateOnly(factReturnBy) },
    { label: 'PR Number', value: factPrNumber || '-' },
    { label: 'Set-Aside', value: factSetAside ? setAsideBadgeLabel(factSetAside) : '-' },
    { label: 'Submission Office', value: factSubmissionOffice || '-' },
    { label: 'Source File', value: factSourceFile || emailArtifact?.content_json?.document_context?.source_file || bestWorkspaceFile?.filename || '-' },
  ]
  const packageHighlights = [
    analysisAssessment || null,
    selectedQuote ? `Planned submission vendor selected: ${selectedQuote.company_name || selectedQuote.cage || 'Vendor'}.` : null,
    !selectedQuote && recommendedQuote ? `Recommended vendor candidate: ${recommendedQuote.company_name || recommendedQuote.cage || 'Vendor'}.` : null,
    packagePriceHistory.average_unit_price ? `Historical average unit price: ${formatCurrency(packagePriceHistory.average_unit_price)}.` : null,
  ].filter(Boolean)
  const readinessBlockers = Array.from(new Set([
    ...analysisBlockers,
    !factNsn && !factNomenclature ? 'Opportunity has not been fully parsed yet.' : null,
    files.length === 0 ? 'No solicitation documents have been downloaded yet.' : null,
    !complianceArtifact ? 'Compliance brief has not been generated yet.' : null,
    complianceNeedsReview.length > 0 ? `Missing information still needs confirmation (${complianceNeedsReview.length}).` : null,
    vendorQuotes.length === 0 ? 'No vendor quote tracker records exist yet.' : null,
    vendorQuotes.length > 0 && !quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED') ? 'No vendor quote has been marked as received yet.' : null,
    vendorQuotes.length > 0 && !quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED' && quote.hasPrice) ? 'No received quote includes pricing yet.' : null,
    !submission?.status || submission.status === 'DRAFT' ? 'Submission workflow is still in draft state.' : null,
  ].filter(Boolean)))
  const readinessStrengths = Array.from(new Set([
    ...analysisStrengths,
    factNsn || factNomenclature ? 'Parsed solicitation signals are available.' : null,
    files.length > 0 ? `${files.length} document${files.length === 1 ? '' : 's'} downloaded.` : null,
    complianceArtifact ? 'Compliance brief is available.' : null,
    quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED') ? 'At least one vendor quote has been received.' : null,
    recommendedQuote?.hasPrice ? `Recommended vendor candidate identified: ${recommendedQuote.company_name || recommendedQuote.cage}.` : null,
    submission?.status && submission.status !== 'DRAFT' ? `Submission status is ${humanizeLabel(submission.status, 'Draft')}.` : null,
  ].filter(Boolean)))

  const contractAboutText = [
    `This opportunity is for ${factQuantity ? `${factQuantity} of ` : ''}${factNomenclature || opp.display_title || opp.title || 'the requested item'}.`,
    factNsn ? `The NSN is ${factNsn}.` : '',
    factSolicitation ? `The solicitation reference is ${factSolicitation}.` : '',
    factReturnBy ? `Responses are due ${formatDateOnly(factReturnBy)}.` : '',
  ].filter(Boolean).join(' ')
  const briefingFacts = [
    formatDetailLine('Agency', opp.agency || '-'),
    formatDetailLine('Solicitation', factSolicitation || '-'),
    formatDetailLine('NSN', factNsn || '-'),
    formatDetailLine('Quantity', factQuantity || '-'),
    formatDetailLine('Return By', formatDateOnly(factReturnBy)),
    formatDetailLine('Set-Aside', factSetAside ? setAsideBadgeLabel(factSetAside) : ''),
  ]
  const outreachSourceSummary = compactMeta([
    emailArtifact?.content_json?.document_context?.source_file ? `Source: ${emailArtifact.content_json.document_context.source_file}` : '',
    outreachPoc.email ? `POC: ${outreachPoc.email}` : outreachPoc.contact_name ? `POC: ${outreachPoc.contact_name}` : '',
    outreachPoc.submission_office ? `Office: ${outreachPoc.submission_office}` : '',
  ])
  const currentStateItems = [
    formatDetailLine('Documents', files.length > 0 ? 'Ready' : 'Missing'),
    formatDetailLine('Supplier Coverage', vendorLeads.length > 0 ? `${vendorLeads.length} vendor lead${vendorLeads.length === 1 ? '' : 's'}` : 'Need suppliers'),
    formatDetailLine('Quotes', quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED') ? 'Quotes received' : (vendorQuotes.length > 0 ? 'Tracking started' : 'No quotes yet')),
    formatDetailLine('Submission Package', submissionPackageArtifact ? 'Started' : 'Not started'),
  ].filter(Boolean)
  const topBlockerText = readinessBlockers[0] || 'No blocker is currently flagged.'
  const nextActionText = workspaceRecommendation?.next_step || analysisNextActions[0] || 'Review the workspace and move the next task forward.'
  const commandVendorPreview = (() => {
    const rows = []
    vendorLeads.forEach((lead) => {
      rows.push({
        company_name: lead.company_name || '',
        cage: lead.cage || '',
        part_number: lead.part_number || '',
        score: Number(lead.confidence || 0) + 14,
        source_labels: ['Lead'],
      })
    })
    vendorQuotes.forEach((quote) => {
      rows.push({
        company_name: quote.company_name || '',
        cage: quote.cage || '',
        part_number: quote.part_number || '',
        score: quoteStatusWeight(quote.status) + (Number(quote.unit_price) ? 18 : 8),
        source_labels: ['Quote'],
      })
    })
    partFinderProviders.forEach((provider) => {
      rows.push({
        company_name: provider.name || provider.company_name || '',
        cage: provider.cage || '',
        part_number: provider.part_number || partFinderPart.part_number || '',
        score: Number(provider.score || provider.confidence || 0) + 10,
        source_labels: ['Part Finder'],
      })
    })
    publogManufacturerCandidates.forEach((candidate) => {
      rows.push({
        company_name: candidate.company_name || '',
        cage: candidate.cage || '',
        part_number: candidate.part_number || '',
        score: Number(candidate.confidence || 0) + 12,
        source_labels: ['PUB LOG'],
      })
    })
    partFinderWbpartsCrossReferences.forEach((candidate) => {
      rows.push({
        company_name: candidate.manufacturer || '',
        cage: candidate.cage || '',
        part_number: candidate.part_number || '',
        score: 9,
        source_labels: ['WBParts'],
      })
    })
    return dedupeVendorIdentityRows(rows)
      .sort((a, b) => (b.score || 0) - (a.score || 0) || String(a.company_name || '').localeCompare(String(b.company_name || '')))
      .slice(0, 6)
  })()
  const commandVendorLines = commandVendorPreview.map((vendor) => compactMeta([
    vendor.company_name || 'Vendor candidate',
    vendor.cage ? `CAGE ${vendor.cage}` : '',
    vendor.part_number ? `Part ${vendor.part_number}` : '',
    (vendor.source_labels || []).join(' + '),
  ]))

  const patchVendorQuoteDraft = (quoteId, field, value) => {
    queryClient.setQueryData(['vendor-quotes', id], (current = []) =>
      current.map((item) => (item.id === quoteId ? { ...item, [field]: value } : item))
    )
  }

  const useQuoteForSubmission = (quote) => {
    const nextForm = {
      ...submissionForm,
      planned_vendor_quote_id: String(quote.id),
      planned_vendor_cage: quote.cage || '',
      planned_vendor_name: quote.company_name || '',
      submitted_vendor_cage: quote.cage || '',
      submitted_vendor_name: quote.company_name || '',
      submitted_unit_price:
        quote.unit_price === null || quote.unit_price === undefined || quote.unit_price === ''
          ? submissionForm.submitted_unit_price
          : String(quote.unit_price),
      notes: submissionForm.notes || `Planned submission vendor: ${quote.company_name || quote.cage || 'Vendor'}`,
    }
    setSubmissionForm(nextForm)
    saveSubmissionMutation.mutate({
      opportunity_id: Number(id),
      status: nextForm.status,
      submitted_at: nextForm.submitted_at || null,
      submitted_unit_price: nextForm.submitted_unit_price === '' ? null : Number(nextForm.submitted_unit_price),
      submitted_vendor_cage: nextForm.submitted_vendor_cage || null,
      submitted_vendor_name: nextForm.submitted_vendor_name || null,
      planned_vendor_quote_id: nextForm.planned_vendor_quote_id ? Number(nextForm.planned_vendor_quote_id) : null,
      planned_vendor_cage: nextForm.planned_vendor_cage || null,
      planned_vendor_name: nextForm.planned_vendor_name || null,
      awarded_at: nextForm.awarded_at || null,
      award_amount: nextForm.award_amount === '' ? null : Number(nextForm.award_amount),
      winning_vendor_cage: nextForm.winning_vendor_cage || null,
      winning_vendor_name: nextForm.winning_vendor_name || null,
      outcome_summary: nextForm.outcome_summary || null,
      notes: nextForm.notes || null,
    })
  }

  const exportQuoteComparisonCsv = () => {
    const rows = [
      ['recommended', 'company_name', 'cage', 'part_number', 'status', 'unit_price', 'lead_time_days', 'score', 'email', 'notes'],
      ...quoteComparison.map((quote) => [
        recommendedQuote?.id === quote.id ? 'yes' : 'no',
        quote.company_name || '',
        quote.cage || '',
        quote.part_number || '',
        quote.normalized_status || '',
        quote.unit_price ?? '',
        quote.lead_time_days ?? '',
        quote.recommendation_score ?? '',
        quote.email || '',
        (quote.notes || '').replace(/\r?\n/g, ' ').trim(),
      ]),
    ]
    const csv = rows.map((row) => row.map((cell) => `"${String(cell ?? '').replace(/"/g, '""')}"`).join(',')).join('\n')
    downloadBlob(`quote_comparison_${id}.csv`, csv, 'text/csv;charset=utf-8')
  }

  const printBidSummary = () => {
    const printable = window.open('', '_blank', 'noopener,noreferrer,width=980,height=760')
    if (!printable) return
    const quoteRows = quoteComparison.map((quote) => `
      <tr>
        <td>${recommendedQuote?.id === quote.id ? 'Recommended' : ''}</td>
        <td>${quote.company_name || '-'}</td>
        <td>${quote.cage || '-'}</td>
        <td>${quote.normalized_status || '-'}</td>
        <td>${formatCurrency(quote.unit_price)}</td>
        <td>${quote.lead_time_days ? `${quote.lead_time_days} days` : '-'}</td>
      </tr>
    `).join('')
    printable.document.write(`
      <html>
        <head>
          <title>Bid Summary ${opp.solicitation_number || id}</title>
          <style>
            body { font-family: Arial, sans-serif; padding: 24px; color: #0f172a; }
            h1, h2 { margin-bottom: 8px; }
            .meta { margin-bottom: 18px; color: #475569; }
            .section { margin-top: 24px; }
            table { width: 100%; border-collapse: collapse; margin-top: 12px; }
            th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; font-size: 13px; }
            th { background: #f8fafc; }
            ul { padding-left: 20px; }
          </style>
        </head>
        <body>
          <h1>${opp.display_title || opp.title || 'Opportunity'}</h1>
          <div class="meta">
            Solicitation: ${opp.solicitation_number || '-'}<br />
            Agency: ${opp.agency || '-'}<br />
            Due: ${formatDateTime(opp.due_at)}<br />
            Recommended Vendor: ${recommendedQuote ? `${recommendedQuote.company_name || recommendedQuote.cage || 'Vendor'} (${formatCurrency(recommendedQuote.unit_price)})` : 'None selected'}
          </div>
          <div class="section">
            <h2>Execution Readiness</h2>
            <ul>${readinessStrengths.map((item) => `<li>${item}</li>`).join('')}</ul>
            <ul>${readinessBlockers.map((item) => `<li>${item}</li>`).join('')}</ul>
          </div>
          <div class="section">
            <h2>Quote Comparison</h2>
            <table>
              <thead>
                <tr><th>Recommended</th><th>Vendor</th><th>CAGE</th><th>Status</th><th>Unit Price</th><th>Lead Time</th></tr>
              </thead>
              <tbody>${quoteRows || '<tr><td colspan="6">No quote data available.</td></tr>'}</tbody>
            </table>
          </div>
        </body>
      </html>
    `)
    printable.document.close()
    printable.focus()
    printable.print()
  }

  const printSubmissionPackage = () => {
    const quoteRows = quoteComparison
      .map(
        (quote) => `
          <tr>
            <td>${selectedQuote?.id === quote.id ? 'Planned' : recommendedQuote?.id === quote.id ? 'Recommended' : ''}</td>
            <td>${quote.company_name || '-'}</td>
            <td>${quote.cage || '-'}</td>
            <td>${quote.normalized_status || '-'}</td>
            <td>${formatCurrency(quote.unit_price)}</td>
            <td>${quote.lead_time_days ? `${quote.lead_time_days} days` : '-'}</td>
            <td>${quote.email || '-'}</td>
          </tr>
        `
      )
      .join('')
    const factRows = packageSubmissionFacts
      .map((item) => `<div><strong>${item.label}:</strong> ${item.value || '-'}</div>`)
      .join('')
    const askRows = (emailVendorAsks.length ? emailVendorAsks : ['No vendor-specific ask list generated yet.'])
      .map((item) => `<li>${item}</li>`)
      .join('')
    const documentRows = (packageDocuments.length ? packageDocuments : [{ filename: 'No documents downloaded yet.', file_type: '-' }])
      .map((file) => `<li>${file.filename}${file.file_type ? ` | ${file.file_type}` : ''}</li>`)
      .join('')
    const printable = window.open('', '_blank', 'noopener,noreferrer,width=1100,height=850')
    if (!printable) return
    printable.document.write(`
      <html>
        <head>
          <title>Submission Package - ${opp.solicitation_number || opp.id}</title>
          <style>
            body { font-family: Arial, sans-serif; color: #0f172a; margin: 24px; line-height: 1.45; }
            h1, h2 { margin-bottom: 10px; }
            .section { margin-top: 20px; padding-top: 12px; border-top: 1px solid #cbd5e1; }
            .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 18px; }
            .hero { display: grid; grid-template-columns: 1.3fr 1fr; gap: 20px; align-items: start; }
            .note { padding: 12px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top; }
            ul { margin: 8px 0 0 18px; }
          </style>
        </head>
        <body>
          <h1>Final Submission Package</h1>
          <div>${opp.display_title || opp.title || 'Opportunity Workspace'}</div>
          <div>${opp.agency || '-'} | ${opp.source || '-'} | Due ${formatDateOnly(factReturnBy)}</div>
          <div class="hero section">
            <div class="note">
              <h2>Submission Snapshot</h2>
              <div class="grid">${factRows}</div>
            </div>
            <div class="note">
              <h2>Vendor Plan</h2>
              <div><strong>Planned Vendor:</strong> ${submissionForm.planned_vendor_name || submissionForm.planned_vendor_cage || 'Not selected'}</div>
              <div><strong>Recommended Vendor:</strong> ${recommendedQuote ? `${recommendedQuote.company_name || recommendedQuote.cage || 'Vendor'}${recommendedQuote.unit_price ? ` | ${formatCurrency(recommendedQuote.unit_price)}` : ''}` : 'Not available'}</div>
              <div><strong>Submission Status:</strong> ${submissionForm.status || 'DRAFT'}</div>
              <div><strong>Submitted Unit Price:</strong> ${formatCurrency(submissionForm.submitted_unit_price)}</div>
            </div>
          </div>
          <div class="section">
            <h2>Executive Highlights</h2>
            <ul>${(packageHighlights.length ? packageHighlights : ['No executive summary generated yet.']).map((item) => `<li>${item}</li>`).join('')}</ul>
          </div>
          <div class="section">
            <h2>Execution Readiness</h2>
            <div class="hero">
              <div>
                <strong>Strengths</strong>
                <ul>${(readinessStrengths.length ? readinessStrengths : ['No strengths captured yet.']).map((item) => `<li>${item}</li>`).join('')}</ul>
              </div>
              <div>
                <strong>Blockers</strong>
                <ul>${(readinessBlockers.length ? readinessBlockers : ['No blockers currently flagged.']).map((item) => `<li>${item}</li>`).join('')}</ul>
              </div>
            </div>
          </div>
          <div class="section">
            <h2>Quote Comparison</h2>
            <table>
              <thead><tr><th>Role</th><th>Vendor</th><th>CAGE</th><th>Status</th><th>Unit Price</th><th>Lead Time</th><th>Email</th></tr></thead>
              <tbody>${quoteRows || '<tr><td colspan="7">No quote data available.</td></tr>'}</tbody>
            </table>
          </div>
          <div class="section">
            <h2>Vendor Outreach Requirements</h2>
            <ul>${askRows}</ul>
          </div>
          <div class="section">
            <h2>Documents In Scope</h2>
            <ul>${documentRows}</ul>
          </div>
          <div class="section">
            <h2>Submission Notes</h2>
            <div>${submissionForm.notes || 'No submission notes recorded yet.'}</div>
          </div>
          <div class="section">
            <h2>Outcome Tracking</h2>
            <div><strong>Status:</strong> ${submissionForm.status || 'DRAFT'}</div>
            <div><strong>Awarded At:</strong> ${formatDateTime(submissionForm.awarded_at)}</div>
            <div><strong>Award Amount:</strong> ${formatCurrency(submissionForm.award_amount)}</div>
            <div><strong>Winning Vendor:</strong> ${submissionForm.winning_vendor_name || submissionForm.winning_vendor_cage || 'Not recorded yet'}</div>
            <div><strong>Outcome Summary:</strong> ${submissionForm.outcome_summary || 'No outcome summary recorded yet.'}</div>
          </div>
        </body>
      </html>
    `)
    printable.document.close()
    printable.focus()
    printable.print()
  }

  useEffect(() => {
    setPipelineForm({
      owner: pipeline?.owner || '',
      priority: pipeline?.priority || '',
      probability_of_win:
        pipeline?.probability_of_win === null || pipeline?.probability_of_win === undefined
          ? ''
          : String(pipeline.probability_of_win),
      target_submit_date: pipeline?.target_submit_date
        ? new Date(pipeline.target_submit_date).toISOString().slice(0, 16)
        : '',
      notes: pipeline?.notes || '',
    })
  }, [pipeline?.id, pipeline?.owner, pipeline?.priority, pipeline?.probability_of_win, pipeline?.target_submit_date, pipeline?.notes])

  useEffect(() => {
    const checklist = checklistArtifact?.content_json?.checklist || []
    setChecklistDraft(
      checklist.map((item, index) => ({
        id: item.id || `item-${index + 1}`,
        text: item.text || item.item || '',
        done: Boolean(item.done),
      }))
    )
  }, [checklistArtifact?.id, checklistArtifact?.content_json])

  useEffect(() => {
    setEmailDraft({
      subject: emailArtifact?.content_json?.subject || '',
      body: emailArtifact?.content_json?.body || '',
    })
  }, [emailArtifact?.id, emailArtifact?.content_json])

  useEffect(() => {
    setCoEmailDraft({
      subject: coEmailArtifact?.content_json?.subject || '',
      body: coEmailArtifact?.content_json?.body || '',
    })
  }, [coEmailArtifact?.id, coEmailArtifact?.content_json])

  useEffect(() => {
    setSubmissionForm({
      status: submission?.status || 'DRAFT',
      submitted_at: submission?.submitted_at ? new Date(submission.submitted_at).toISOString().slice(0, 16) : '',
      submitted_unit_price:
        submission?.submitted_unit_price === null || submission?.submitted_unit_price === undefined
          ? ''
          : String(submission.submitted_unit_price),
      submitted_vendor_cage: submission?.submitted_vendor_cage || '',
      submitted_vendor_name: submission?.submitted_vendor_name || '',
      planned_vendor_quote_id: submission?.planned_vendor_quote_id ? String(submission.planned_vendor_quote_id) : '',
      planned_vendor_cage: submission?.planned_vendor_cage || '',
      planned_vendor_name: submission?.planned_vendor_name || '',
      awarded_at: submission?.awarded_at ? new Date(submission.awarded_at).toISOString().slice(0, 16) : '',
      award_amount:
        submission?.award_amount === null || submission?.award_amount === undefined
          ? ''
          : String(submission.award_amount),
      winning_vendor_cage: submission?.winning_vendor_cage || '',
      winning_vendor_name: submission?.winning_vendor_name || '',
      outcome_summary: submission?.outcome_summary || '',
      notes: submission?.notes || '',
    })
  }, [submission?.id, submission?.status, submission?.submitted_at, submission?.submitted_unit_price, submission?.submitted_vendor_cage, submission?.submitted_vendor_name, submission?.planned_vendor_quote_id, submission?.planned_vendor_cage, submission?.planned_vendor_name, submission?.awarded_at, submission?.award_amount, submission?.winning_vendor_cage, submission?.winning_vendor_name, submission?.outcome_summary, submission?.notes])

  useEffect(() => {
    if (!visibleFiles || visibleFiles.length === 0) {
      if (selectedFileId !== null) {
        setSelectedFileId(null)
      }
      return
    }
    const hasSelectedFile = visibleFiles.some((file) => file.id === selectedFileId)
    if (!hasSelectedFile) {
      setSelectedFileId(visibleFiles[0].id)
    }
  }, [visibleFiles, selectedFileId])

  useEffect(() => {
    if (!id || !isDibbsOpportunity) return
    if (workspaceQuery.isLoading) return
    if (filesQuery.isLoading) return
    if (activeIntakeJobId || isIntakeRunning) return
    if (visibleFiles.length > 0) return
    if (runIntakeMutation.isPending) return
    runIntakeMutation.mutate()
  }, [
    id,
    isDibbsOpportunity,
    workspaceQuery.isLoading,
    filesQuery.isLoading,
    activeIntakeJobId,
    isIntakeRunning,
    visibleFiles.length,
    runIntakeMutation.isPending,
  ])

  if (workspaceQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading workspace..." />
        </Card>
      </div>
    )
  }

  if (workspaceQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Workspace not available"
          subtitle={`Opportunity ${id} could not be loaded.`}
          action={<Button onClick={() => navigate('/opportunities')}>Go to opportunities</Button>}
        />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="page">
        <EmptyState title="Workspace not found" subtitle={`No workspace data was returned for opportunity ${id}.`} />
      </div>
    )
  }

  const analysis = data.analysis || {}
  const solicitationMemory = analysis.solicitation_memory || data.solicitation_memory || {}
  const agentFindings = data.agent_findings || {}
  const workspaceFreshness = data.workspace_freshness || {}
  const vendors = data.vendor_matches || []
  const recentActivity = data.recent_activity || []
  const agentRuns = agentRunsQuery.data?.items || data.agent_runs || []
  const agentPhases = data.agent_phases || {}
  const agentCatalog = data.agent_catalog || {}
  const lastAgentRunResult = runAgentMutation.data || null
  const lastAgentPhaseResult = runAgentPhaseMutation.data || null
  const agentRunError = runAgentMutation.error?.response?.data?.detail || runAgentMutation.error?.message || ''
  const agentPhaseError = runAgentPhaseMutation.error?.response?.data?.detail || runAgentPhaseMutation.error?.message || ''
  const selectedFile = files.find((file) => file.id === selectedFileId) || null
  const fileInsights = fileInsightsQuery.data || null
  const solicitationStatus = opp.solicitation_status || 'OPEN'
  const isClosedSolicitation = solicitationStatus === 'CLOSED'
  const isArchivedOpportunity = opp.opportunity_lifecycle === 'ARCHIVED'
  const documentFields = opp.document_fields || {}
  const documentSummary = opp.document_summary || {}
  const preparedSummaryText =
    formatBriefText(analysis.ai_summary || opp.prepared_summary || '', { punctuate: false })
  const preparedRequirements = normalizeAnalysisList(analysis.requirements || opp.prepared_requirements || parsedSummary.sam_intelligence?.requirements || [])
  const preparedRiskFlags = normalizeAnalysisList(analysis.risk_flags || opp.prepared_risk_flags || parsedSummary.sam_intelligence?.risk_flags || [])
  const solicitationMemoryNotes = normalizeAnalysisList(solicitationMemory.pattern_notes || [])
  const solicitationMemoryExamples = solicitationMemory.examples || []
  const solicitationMemoryThemes = normalizeAnalysisList(solicitationMemory.common_rationale || [])
  const capabilityMatch = analysis.capability_match || data.capability_match || {}
  const capabilitySignals = normalizeAnalysisList(capabilityMatch.signals || [])
  const capabilityGaps = normalizeAnalysisList(capabilityMatch.gaps || [])
  const capabilitySummary =
    formatBriefText(capabilityMatch.summary || '', { punctuate: false }) || 'Capability alignment has not been reviewed yet.'
  const summaryOverviewText =
    preparedSummaryText
    || formatBriefText(opp.summary || documentSummary.summary_text || '', { punctuate: false })
    || 'No contract overview is available yet.'
  const commandOverviewItems = [
    formatDetailLine('Due', formatDateTime(factReturnBy)),
    formatDetailLine('NSN / Part Path', compactMeta([factNsn, partFinderPart.part_number ? `Part ${partFinderPart.part_number}` : ''])),
    formatDetailLine('Likely Vendors', commandVendorPreview.length ? `${commandVendorPreview.length} vendor candidate${commandVendorPreview.length === 1 ? '' : 's'}` : 'No likely vendors yet'),
  ].filter(Boolean)
  const overviewTitle = isSamOpportunity ? 'Contract Overview' : 'Part Requirement Overview'
  const progressTitle = isSamOpportunity ? 'Opportunity Progress' : 'RFQ Progress'
  const progressSubtitle = isSamOpportunity
    ? 'Use this to track where this opportunity stands in your workflow.'
    : 'Use this to track sourcing, quote, and submission progress for this RFQ.'
  const readinessCardTitle = 'Current State'
  const workspaceProgressCardTitle = isSamOpportunity ? 'Proposal Plan' : 'Opportunity Progress'
  const workspaceTasksCardTitle = isSamOpportunity ? 'Proposal Tasks' : 'Workspace Tasks'
  const checklistArtifactTitle = isSamOpportunity ? 'Proposal Checklist' : 'Checklist Artifact'
  const checklistArtifactEmptySubtitle = isSamOpportunity
    ? 'Generate a proposal checklist artifact to track scope review, compliance work, outreach, and submission prep.'
    : 'Generate a checklist artifact to track requirements and bid readiness.'
  const documentsCardTitle = isSamOpportunity ? 'Documents' : 'RFQ Package'
  const documentsButtonLabel = isSamOpportunity ? 'Download Documents' : 'Download RFQ Package'
  const documentsLoadingLabel = isSamOpportunity ? 'Loading documents...' : 'Loading RFQ package...'
  const documentsEmptyTitle = isSamOpportunity ? 'No documents yet' : 'No RFQ package yet'
  const documentsEmptySubtitle = isSamOpportunity
    ? (data.ui_hints?.empty_artifacts_message || 'Use Download Documents to fetch files for this opportunity.')
    : 'Download the RFQ package to review the solicitation documents, clauses, and source attachments.'
  const documentsInsightsSubtitle = isSamOpportunity
    ? 'Document processing is used by the workspace agents and compliance brief.'
    : 'Package processing is used to extract RFQ facts, sourcing clues, and submission instructions.'
  const packageReviewCardTitle = isSamOpportunity ? 'Solicitation Brief' : 'RFQ Package Review'
  const packageReviewEmptyTitle = isSamOpportunity ? 'No solicitation brief yet' : 'No RFQ package review yet'
  const packageReviewEmptySubtitle = isSamOpportunity
    ? 'Download documents and let the processing pipeline organize the scope, submission requirements, missing information, and performance details.'
    : 'Download the RFQ package and let the processing pipeline organize item details, sourcing requirements, and quote instructions.'
  const packageFactsTitle = isSamOpportunity ? 'Confirmed Facts' : 'Confirmed RFQ Facts'

  const packageBasisTitle = isSamOpportunity ? 'Document Basis' : 'Package Basis'
  const packageBasisText = isSamOpportunity
    ? `${factSourceFile || 'Primary source document unavailable'} was used to build this solicitation brief`
    : `${factSourceFile || 'Primary source document unavailable'} was used to build this RFQ package review`
  const summaryKeyFacts = [
    { label: 'Solicitation', value: factSolicitation },
    { label: 'Due', value: formatDateTime(factReturnBy) !== '-' ? formatDateTime(factReturnBy) : '' },
    { label: 'Quantity', value: factQuantity },
    { label: 'Set-Aside', value: factSetAside ? setAsideBadgeLabel(factSetAside) : '' },
    { label: 'Approved Sources', value: String(parsedSummary.approved_source_count || researchProfile.approved_source_count || '') },
    { label: 'Source File', value: factSourceFile || parsedSummary.document_source_file || opp.document_source_file || '' },
  ].filter((item) => item.value && item.value !== '-')
  const summaryIdentifiers = [
    { label: 'NSN', value: factNsn },
    { label: 'Nomenclature', value: factNomenclature },
    { label: 'NAICS', value: factNaics },
    { label: 'FSC', value: factFsc },
  ].filter((item) => item.value && item.value !== '-')
  const procurementProfileItems = [
    formatDetailLine('Buyer Family', procurementProfile.buyer_family || ''),
    formatDetailLine('Buyer', procurementProfile.buyer_name || procurementProfile.agency || ''),
    formatDetailLine('Scope', procurementProfile.procurement_scope ? humanizeLabel(procurementProfile.procurement_scope, '') : ''),
    formatDetailLine(
      'Classification',
      procurementProfile.classification_scheme && procurementProfile.classification_value
        ? `${procurementProfile.classification_scheme} ${procurementProfile.classification_value}`
        : ''
    ),
    formatDetailLine('Submission Channel', procurementProfile.submission_channel || ''),
    formatDetailLine('Sourcing Model', procurementProfile.sourcing_model ? humanizeLabel(procurementProfile.sourcing_model, '') : ''),
  ].filter(Boolean)
  const solicitationAnalystFinding = agentFindings.solicitation_analyst || {}
  const complianceReviewerFinding = agentFindings.compliance_reviewer || {}
  const marketResearcherFinding = agentFindings.market_researcher || {}
  const capabilityMatcherFinding = agentFindings.capability_matcher || {}
  const outreachCoordinatorFinding = agentFindings.outreach_coordinator || {}
  const proposalCoordinatorFinding = agentFindings.proposal_coordinator || {}
  const solicitationHistorySignals = normalizeAnalysisList(solicitationAnalystFinding.history_signals || [])
  const solicitationOutcomePatterns = (solicitationAnalystFinding.outcome_patterns || [])
    .map((item) => item?.label && item?.count ? `${item.label}: ${item.count}` : '')
    .filter(Boolean)
  const solicitationResponsePatterns = (solicitationAnalystFinding.response_patterns || [])
    .map((item) => item?.label && item?.count ? `${item.label}: ${item.count}` : '')
    .filter(Boolean)
  const complianceMatrixLines = (complianceReviewerFinding.requirement_matrix || [])
    .slice(0, 6)
    .map((item) => compactMeta([
      item.category || '',
      item.status ? humanizeLabel(item.status) : '',
      item.requirement || '',
    ]))
    .filter(Boolean)
  const marketFindingLines = normalizeAnalysisList(marketResearcherFinding.market_findings || [])
  const marketTargetLines = normalizeAnalysisList(marketResearcherFinding.recommended_targets || [])
  const capabilitySignalLines = normalizeAnalysisList([
    ...(capabilityMatcherFinding.signals || []),
    ...(capabilityMatcherFinding.gaps || []).slice(0, 3).map((item) => `Gap: ${item}`),
  ])
  const outreachFindingLines = normalizeAnalysisList([
    outreachCoordinatorFinding.target_vendor_name
      ? `Target vendor: ${outreachCoordinatorFinding.target_vendor_name}${outreachCoordinatorFinding.target_vendor_cage ? ` | ${outreachCoordinatorFinding.target_vendor_cage}` : ''}`
      : '',
    ...(outreachCoordinatorFinding.follow_up_plan || []),
  ])
  const proposalFindingLines = normalizeAnalysisList([
    proposalCoordinatorFinding.open_task_count !== undefined && proposalCoordinatorFinding.open_task_count !== null
      ? `Open tasks: ${proposalCoordinatorFinding.open_task_count}`
      : '',
    ...(proposalCoordinatorFinding.recommended_sequence || []),
  ])
  const workspaceFreshnessLines = normalizeAnalysisList([
    ...(workspaceFreshness.reasons || []),
    ...((workspaceFreshness.active_jobs || []).map((job) => {
      const kind = humanizeLabel(job.kind || '', '')
      const lane = humanizeLabel(job.worker_lane || '', '')
      const status = humanizeLabel(job.status || '', '')
      return [kind, lane ? `${lane} lane` : '', status].filter(Boolean).join(' | ')
    })),
  ])
  const samOperatorItems = isSamOpportunity ? [
    formatDetailLine('Decision', humanizeLabel(workspaceRecommendation?.recommendation, 'Needs Review')),
    formatDetailLine('Next Step', workspaceRecommendation?.next_step || ''),
    formatDetailLine('Response Type', procurementProfile.response_type ? humanizeLabel(procurementProfile.response_type, '') : ''),
    formatDetailLine('Evaluation Basis', procurementProfile.evaluation_basis ? humanizeLabel(procurementProfile.evaluation_basis, '') : ''),
    formatDetailLine('Proposal Burden', procurementProfile.proposal_burden ? humanizeLabel(procurementProfile.proposal_burden, '') : ''),
    formatDetailLine('Attachments', procurementProfile.required_attachment_count ? String(procurementProfile.required_attachment_count) : ''),
    formatDetailLine('Amendments', procurementProfile.amendment_count ? String(procurementProfile.amendment_count) : ''),
    formatDetailLine('Place of Performance', procurementProfile.place_of_performance || ''),
    formatDetailLine('Period of Performance', procurementProfile.period_of_performance || ''),
  ].filter(Boolean) : []
  const solicitationMemoryItems = [
    formatDetailLine('Local Match Count', solicitationMemory.match_count ? String(solicitationMemory.match_count) : ''),
    formatDetailLine('History Summary', solicitationMemory.summary || ''),
    formatDetailLine('Vendor Response Pattern', solicitationMemory.strongest_response_pattern ? formatOutcomeLabel(solicitationMemory.strongest_response_pattern) : ''),
  ].filter(Boolean)
  const workspaceGuidanceItems = [
    formatDetailLine('Current Posture', formatGuidancePosture(analysisBidPosture)),
    formatDetailLine('Next Step', workspaceRecommendation?.next_step || (analysisNextActions[0] || 'Review the workspace and move the next task forward.')),
    formatDetailLine('Supplier Evidence', recommendationSupplierEvidence?.summary || ''),
  ].filter(Boolean)
  const similarHistoryItems = solicitationMemoryExamples.map((item) => {
    const bits = [
      item.agency || '',
      item.naics_code ? `NAICS ${item.naics_code}` : '',
      item.fsc_code ? `FSC ${item.fsc_code}` : '',
      item.outcome ? `History ${formatOutcomeLabel(item.outcome)}` : '',
      item.vendor_response_quality ? `Vendor response ${formatOutcomeLabel(item.vendor_response_quality)}` : '',
    ].filter(Boolean)
    const reasons = [...(item.match_reasons || []), ...(item.decision_rationale || []).slice(0, 2)].filter(Boolean).join(' | ')
    return `${item.title || 'Past opportunity'}${bits.length ? ` - ${bits.join(' | ')}` : ''}${reasons ? ` - ${reasons}` : ''}`
  })
  const mergedSolicitationMemoryItems = [
    ...solicitationMemoryItems,
    ...solicitationMemoryNotes.slice(0, 2),
    ...solicitationMemoryThemes.slice(0, 2),
    ...similarHistoryItems.slice(0, 2),
  ].filter(Boolean)
  const checklistCompletedCount = checklistDraft.filter((item) => item.done).length
  const checklistTotalCount = checklistDraft.length
  const checklistProgress = checklistTotalCount > 0 ? Math.round((checklistCompletedCount / checklistTotalCount) * 100) : 0
  const visibleWorkspaceTasks = isSamOpportunity
    ? tasks.filter((task) => String(task.task_type || '').trim().toUpperCase() !== 'PROPOSAL_STEP')
    : tasks

  const readinessChecks = [
    { label: 'Opportunity parsed', done: Boolean(factNsn || factNomenclature || parsedSummary.approved_source_count) },
    { label: 'Vendor research started', done: vendors.length > 0 || (parsedSummary.approved_source_count || 0) > 0 },
    { label: 'Documents downloaded', done: files.length > 0 },
    { label: 'Email draft generated', done: Boolean(emailArtifact) },
    { label: 'Quote tracker seeded', done: vendorQuotes.length > 0 },
    { label: 'Received quote logged', done: quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED') },
    { label: 'Workspace progress updated', done: Boolean(pipeline?.decision_status && pipeline.decision_status !== 'NEW') },
    { label: 'Submission tracked', done: Boolean(submission?.status && submission.status !== 'DRAFT') },
  ]
  const readinessReadyCount = readinessChecks.filter((item) => item.done).length
  const readinessPendingCount = readinessChecks.length - readinessReadyCount

  const updateDecisionStatus = async (decisionStatus) => {
    if (isClosedSolicitation) return
    let current = pipeline
    if (!current?.id) {
      current = await ensurePipelineMutation.mutateAsync()
    }
    await updatePipelineMutation.mutateAsync({
      id: current.id,
      body: { decision_status: decisionStatus },
    })
  }

  const savePipelineDetails = async () => {
    if (isClosedSolicitation) return
    let current = pipeline
    if (!current?.id) {
      current = await ensurePipelineMutation.mutateAsync()
    }
    await updatePipelineMutation.mutateAsync({
      id: current.id,
      body: {
        owner: pipelineForm.owner || null,
        priority: pipelineForm.priority || null,
        probability_of_win: pipelineForm.probability_of_win === '' ? null : Number(pipelineForm.probability_of_win),
        target_submit_date: pipelineForm.target_submit_date || null,
        notes: pipelineForm.notes || null,
      },
    })
  }

  const overviewContent = (
    <div className="workspace-overview">
        <Card>
          <div className="summary-lead-grid">
            <div className="workspace-action-column">
              <div className="row-title">{factSolicitation || 'Solicitation unavailable'}</div>
            <div className="panel-subtitle">
              {opp.agency || 'Agency unavailable'} | {opp.source || 'Source unavailable'}
            </div>
          </div>
          <div className="badge-stack company-badge-stack">
            {opp.set_aside_type ? <Badge label={setAsideBadgeLabel(opp.set_aside_type)} variant={setAsideBadgeVariant(opp.set_aside_type)} /> : null}
            <StatusPill status={solicitationStatus} />
            <StatusPill status={pipeline?.decision_status || analysis.decision_status || 'NEW'} />
            <Button variant="secondary" loading={runIntakeMutation.isPending || isIntakeRunning} onClick={() => runIntakeMutation.mutate()}>
              Prepare Workspace
            </Button>
          </div>
        </div>

        {activeIntakeJob ? (
          <div className="search-progress-box">
            <div className="search-progress-header">
              <div>
                <div className="row-title">
                  {activeIntakeJob.status === 'success'
                    ? 'Workspace preparation complete'
                    : activeIntakeJob.status === 'failed'
                      ? 'Workspace preparation failed'
                      : 'Preparing workspace'}
                </div>
                <div className="row-subtitle">
                  {activeIntakeJob.status === 'failed'
                    ? activeIntakeJob.error || 'Pipeline failed.'
                    : activeIntakeJob.progress?.current_label || 'Starting pipeline'}
                </div>
              </div>
              <strong>{activeIntakeJob.progress?.percent || 0}%</strong>
            </div>
            <div className="search-progress-track">
              <div className="search-progress-fill" style={{ width: `${activeIntakeJob.progress?.percent || 0}%` }} />
            </div>
            <div className="row-subtitle">
              {(activeIntakeJob.progress?.completed_steps || 0)} of {(activeIntakeJob.progress?.total_steps || 0)} step{(activeIntakeJob.progress?.total_steps || 0) === 1 ? '' : 's'} complete.
            </div>
            {dibbsSourceUnavailable ? (
              <div className="workspace-mode-banner" style={{ marginTop: 12 }}>
                <div className="row-title">DIBBS temporarily unavailable</div>
                <div className="panel-subtitle">
                  {dibbsSourceUnavailable.message || 'DIBBS appears to be under maintenance. Retry the official PDF download later.'}
                </div>
              </div>
            ) : null}
          </div>
        ) : null}

          {isClosedSolicitation ? (
            <div className="workspace-mode-banner">
              <div className="row-title">{isArchivedOpportunity ? 'Archived solicitation - archive view' : 'Closed solicitation - research only'}</div>
              <div className="panel-subtitle">
                {isArchivedOpportunity
                  ? 'This archive keeps the source link, documents, and extracted intelligence without active queue work.'
                  : (data.ui_hints?.closed_message || 'This workspace remains available for research, artifacts, and vendor intelligence.')}
              </div>
            </div>
          ) : null}

          <div className="summary-brief-layout">
            <div className="artifact-note-box summary-overview-box">
              <div className="row-title">{overviewTitle}</div>
              <div className="structured-copy">{summaryOverviewText}</div>
            </div>

            <div className="summary-inline-sections">
              <div className="summary-inline-section">
                <div className="row-title">Key Facts</div>
                <div className="summary-inline-list">
                  {summaryKeyFacts.map((item) => (
                    <div key={`summary-fact-${item.label}`} className="summary-inline-item">
                      <span className="summary-inline-label">{item.label}</span>
                      <span className="summary-inline-value">{item.value}</span>
                    </div>
                  ))}
                </div>
              </div>

              {summaryIdentifiers.length ? (
                <div className="summary-inline-section">
                  <div className="row-title">Identifiers</div>
                  <div className="summary-inline-list">
                    {summaryIdentifiers.map((item) => (
                      <div key={`summary-identifier-${item.label}`} className="summary-inline-item">
                        <span className="summary-inline-label">{item.label}</span>
                        <span className="summary-inline-value">{item.value}</span>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          {isSamOpportunity && (preparedRequirements.length || preparedRiskFlags.length) ? (
            <div className="workspace-summary-grid">
              <Card title="Requirements To Track">
                <div className="artifact-list">
                  {(preparedRequirements.length ? preparedRequirements : ['No clear submission requirements were extracted yet.']).map((item, index) => (
                    <div key={`prepared-requirement-${index}`} className="artifact-list-item">{item}</div>
                  ))}
                </div>
              </Card>
              <Card title="Risks To Watch">
                <div className="artifact-list">
                  {(preparedRiskFlags.length ? preparedRiskFlags : ['No immediate risks were flagged from the current notice data.']).map((item, index) => (
                    <div key={`prepared-risk-${index}`} className="artifact-list-item">{item}</div>
                  ))}
                </div>
              </Card>
            </div>
          ) : null}

          {isSamOpportunity ? (
            <div className="workspace-summary-grid">
              <Card title="Capability Match">
                <div className="workspace-action-column">
                  <div className="artifact-note-box">
                    <div className="row-title">Profile Alignment</div>
                    <div className="structured-copy">{capabilitySummary}</div>
                  </div>
                  <div className="bid-readiness-grid">
                    <div>
                      <div className="row-title">What Lines Up</div>
                      <div className="artifact-list">
                        {(capabilitySignals.length ? capabilitySignals : ['No clear capability signals have been identified yet.']).map((item, index) => (
                          <div key={`capability-signal-${index}`} className="artifact-list-item">{item}</div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="row-title">What Needs Review</div>
                      <div className="artifact-list">
                        {(capabilityGaps.length ? capabilityGaps : ['No obvious capability gaps are flagged right now.']).map((item, index) => (
                          <div key={`capability-gap-${index}`} className="artifact-list-item">{item}</div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </Card>
              <Card title="Contact Contracting Officer">
                {!coEmailArtifact ? (
                  <EmptyState
                    title="No CO draft yet"
                    subtitle="Generate a draft email to introduce your company or ask for clarification."
                    action={<Button loading={generateCoEmailMutation.isPending} onClick={() => generateCoEmailMutation.mutate()}>Generate CO Draft</Button>}
                  />
                ) : (
                  <div className="workspace-action-column">
                    <BriefDetailsBox
                      title="Point of Contact"
                      items={[
                        formatDetailLine('Name', coPoc?.contact_name || coEmailArtifact.content_json?.contact_name || '-'),
                        formatDetailLine('Email', coPoc?.email || coEmailArtifact.content_json?.to || '-'),
                        formatDetailLine('Phone', coPoc?.phone || coEmailArtifact.content_json?.contact_phone || '-'),
                        formatDetailLine('Office', coPoc?.submission_office || coEmailArtifact.content_json?.submission_office || '-'),
                      ]}
                      emptyMessage="No contracting officer details were extracted yet."
                    />
                    <Input
                      label="Subject"
                      value={coEmailDraft.subject}
                      onChange={(event) => setCoEmailDraft((current) => ({ ...current, subject: event.target.value }))}
                    />
                    <div className="company-form-stack">
                      <label className="textarea-label">Body</label>
                      <textarea
                        className="textarea-field textarea-tall"
                        value={coEmailDraft.body}
                        onChange={(event) => setCoEmailDraft((current) => ({ ...current, body: event.target.value }))}
                      />
                    </div>
                    <div className="company-form-actions">
                      <Button
                        loading={updateArtifactMutation.isPending}
                        onClick={() => updateArtifactMutation.mutateAsync({
                          artifactId: coEmailArtifact.id,
                          body: {
                            content_json: {
                              ...coEmailArtifact.content_json,
                              subject: coEmailDraft.subject,
                              body: coEmailDraft.body,
                            },
                          },
                        })}
                      >
                        Save CO Draft
                      </Button>
                      <Button variant="secondary" loading={generateCoEmailMutation.isPending} onClick={() => generateCoEmailMutation.mutate()}>
                        Regenerate
                      </Button>
                    </div>
                  </div>
                )}
              </Card>
            </div>
          ) : null}

          <div className="summary-decision-row">
            <div className="row-title">{progressTitle}</div>
            <div className="decision-chip-row">
              {PROGRESS_OPTIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={`set-aside-chip ${(pipeline?.decision_status || analysis.decision_status || 'NEW') === option.value ? 'selected' : ''}`}
                  disabled={isClosedSolicitation}
                  onClick={() => updateDecisionStatus(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <div className="panel-subtitle">
              {isClosedSolicitation
                ? 'Progress changes are disabled because this solicitation is closed.'
                : progressSubtitle}
            </div>
          </div>
      </Card>

          {!isSamOpportunity ? (
            <div className="workspace-summary-grid">
              <Card title="Part Finder">
              <div className="workspace-action-column">
                <div className="results-toolbar">
                  <div>
                    <div className="row-title">
                      {partFinderPart.item_name || factNomenclature || 'Part intelligence not saved yet'}
                    </div>
                    <div className="panel-subtitle">
                      {partFinderArtifact
                        ? `Last refreshed ${formatDateTime(partFinderArtifact.created_at)}`
                        : 'Run Part Finder to identify the part, sourcing clues, providers, and awardees.'}
                    </div>
                  </div>
                  <Button
                    variant="secondary"
                    loading={refreshPartFinderMutation.isPending}
                    onClick={() => refreshPartFinderMutation.mutate()}
                  >
                    Refresh Part Finder
                  </Button>
                </div>

                <div className="summary-inline-list">
                  {[
                    ['NSN', partFinderPart.nsn || factNsn || '-'],
                    ['Quantity', partFinderPart.quantity_display || factQuantity || '-'],
                    ['FSC', partFinderPart.fsc || factFsc || '-'],
                    ['NIIN', partFinderPart.niin || '-'],
                    ['References', partFinderPart.reference_count ?? '-'],
                    ['WBParts', partFinderWbparts.status === 'ok'
                      ? `${partFinderWbparts.summary?.cross_reference_count || 0} cross refs | ${partFinderWbparts.summary?.alternate_count || 0} alternates`
                      : (partFinderWbparts.status ? humanizeLabel(partFinderWbparts.status) : '-')],
                    ['WBParts Cache', partFinderWbparts.cache_hit ? 'cached' : (partFinderWbparts.fetched_at ? 'fresh' : '-')],
                    ['Confidence', partFinder.confidence?.identity ? `Identity ${partFinder.confidence.identity} | Supplier ${partFinder.confidence.supplier}` : '-'],
                  ].map(([label, value]) => (
                    <div key={`part-finder-${label}`} className="summary-inline-item">
                      <span className="summary-inline-label">{label}</span>
                      <span className="summary-inline-value">{value}</span>
                    </div>
                  ))}
                </div>

                <BriefDetailsBox
                  title="Part Numbers"
                  items={(partFinderPart.part_numbers || []).slice(0, 8).map((item) => item)}
                  emptyMessage="No part/reference numbers found yet."
                />

                <BriefDetailsBox
                  title="WBParts Alternates"
                  items={partFinderWbpartsAlternates.slice(0, 10)}
                  emptyMessage="No WBParts alternates are cached yet."
                />

                <div className="bid-readiness-grid">
                  <div>
                    <div className="row-title">Provider Candidates</div>
                    <div className="artifact-list">
                      {(partFinderProviders.length ? partFinderProviders.slice(0, 5) : []).map((provider, index) => (
                        <div key={`part-provider-${provider.provider_id || provider.cage || index}`} className="artifact-list-item">
                          {provider.name || provider.cage || 'Provider'}
                          {provider.cage ? ` | CAGE ${provider.cage}` : ''}
                          {provider.roles?.length ? ` | ${provider.roles.slice(0, 2).join(', ')}` : ''}
                        </div>
                      ))}
                      {!partFinderProviders.length ? <div className="artifact-list-item">No provider candidates found yet.</div> : null}
                    </div>
                  </div>
                  <div>
                    <div className="row-title">WBParts Cross References</div>
                    <div className="artifact-list">
                      {(partFinderWbpartsCrossReferences.length ? partFinderWbpartsCrossReferences.slice(0, 5) : []).map((row, index) => (
                        <div key={`part-wbparts-${row.cage || row.part_number || index}`} className="artifact-list-item">
                          {row.part_number || 'Part unknown'}
                          {row.cage ? ` | CAGE ${row.cage}` : ''}
                          {row.manufacturer ? ` | ${row.manufacturer}` : ''}
                        </div>
                      ))}
                      {!partFinderWbpartsCrossReferences.length ? <div className="artifact-list-item">No WBParts cross references are cached yet.</div> : null}
                    </div>
                  </div>
                  <div>
                    <div className="row-title">WBParts Demand History</div>
                    <div className="artifact-list">
                      {(partFinderWbpartsDemandHistory.length ? partFinderWbpartsDemandHistory.slice(0, 5) : []).map((row, index) => (
                        <div key={`part-wbparts-demand-${row.part_number || row.request_date || index}`} className="artifact-list-item">
                          {row.part_number || 'Part unknown'}
                          {row.request_date ? ` | ${row.request_date}` : ''}
                          {row.quantity ? ` | Qty ${row.quantity}` : ''}
                          {row.origin ? ` | ${row.origin}` : ''}
                        </div>
                      ))}
                      {!partFinderWbpartsDemandHistory.length ? <div className="artifact-list-item">No WBParts demand history is cached yet.</div> : null}
                    </div>
                  </div>
                </div>
              </div>
              </Card>

              <Card title="Command Brief">
                <div className="workspace-action-column">
                  <div className="workspace-command-grid">
                    {commandOverviewItems.map((item, index) => {
                      const [label, ...rest] = item.split(': ')
                      return (
                        <div key={`command-overview-${index}`} className="workspace-command-tile">
                          <div className="summary-inline-label">{label}</div>
                          <div className="summary-inline-value">{rest.join(': ') || '-'}</div>
                        </div>
                      )
                    })}
                  </div>

                  <div className="artifact-note-box workspace-command-summary-box">
                    <div className="row-title">Submission State</div>
                    <div className="structured-copy">
                      {humanizeLabel(submission?.status, 'Draft')}
                    </div>
                    <div className="panel-subtitle">
                      {analysisAssessment || contractAboutText}
                    </div>
                  </div>

                  <div className="bid-readiness-grid">
                    <BriefDetailsBox title="Current State" items={currentStateItems} emptyMessage="Current state will fill in as the workspace grows." />
                    <BriefDetailsBox title="Likely Vendors" items={commandVendorLines} emptyMessage="No likely vendors are surfaced yet." />
                  </div>

                  <div className="bid-readiness-grid">
                    <div>
                      <div className="row-title">Top Blocker</div>
                      <div className="artifact-list">
                        <div className="artifact-list-item">{topBlockerText}</div>
                      </div>
                    </div>
                    <div>
                      <div className="row-title">Next Action</div>
                      <div className="artifact-list">
                        <div className="artifact-list-item">{nextActionText}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </Card>

              <Card title="Workspace Guidance">
              <div className="workspace-action-column">
                <div className="company-form-actions">
                  <Button variant="secondary" loading={generateResearchBriefMutation.isPending} onClick={() => generateResearchBriefMutation.mutate()}>
                    Refresh Brief
                  </Button>
                  <Button variant="secondary" loading={runAgentPhaseMutation.isPending} onClick={() => runAgentPhaseMutation.mutate('phase_1')}>
                    Run Phase 1 Agents
                  </Button>
                </div>
                <div className="artifact-note-box">
                  <div className="row-title">Current Posture</div>
                  <div className="artifact-brief-lines">
                    {(workspaceGuidanceItems.length ? workspaceGuidanceItems : ['Guidance will sharpen as documents, suppliers, and pricing signals fill in.']).map((item, index) => (
                      <div key={`workspace-guidance-${index}`} className="artifact-brief-line">{item}</div>
                    ))}
                  </div>
                </div>
                {workspaceFreshnessLines.length > 0 ? (
                  <StructuredList
                    title="Workspace Freshness"
                    items={workspaceFreshnessLines}
                    emptyMessage={workspaceFreshness.summary || 'Workspace is current.'}
                  />
                ) : null}
                {isSamOpportunity ? (
                  <BriefDetailsBox
                    title="SAM Operator Block"
                    items={samOperatorItems}
                    emptyMessage="Proposal-specific decision signals will appear as the document set and workspace fill in."
                  />
                ) : null}
                <BriefDetailsBox
                  title="Solicitation Memory"
                  items={mergedSolicitationMemoryItems}
                  emptyMessage="The system will start building pattern memory after more opportunities have been reviewed here."
                />
                {false ? (
                <StructuredList
                  title="Similar History"
                  items={solicitationMemoryExamples.map((item) => {
                    const bits = [
                      item.agency || '',
                      item.naics_code ? `NAICS ${item.naics_code}` : '',
                      item.fsc_code ? `FSC ${item.fsc_code}` : '',
                      item.outcome ? `History ${formatOutcomeLabel(item.outcome)}` : '',
                      item.vendor_response_quality ? `Vendor response ${formatOutcomeLabel(item.vendor_response_quality)}` : '',
                    ].filter(Boolean)
                    const reasons = [...(item.match_reasons || []), ...(item.decision_rationale || []).slice(0, 2)].filter(Boolean).join(' | ')
                    return `${item.title || 'Past opportunity'}${bits.length ? ` — ${bits.join(' | ')}` : ''}${reasons ? ` — ${reasons}` : ''}`
                  })}
                  emptyMessage="No similar local opportunities have been captured yet."
                />
                ) : null}
                {recommendationSupplierCandidates.length > 0 ? (
                  <StructuredList
                    title="Why These Vendors"
                    items={recommendationSupplierCandidates.slice(0, 3)}
                    emptyMessage="No PUB LOG and SAM-backed supplier evidence is ready yet."
                  />
                ) : null}
                <BriefDetailsBox
                  title="Procurement Profile"
                  items={procurementProfileItems}
                  emptyMessage="The workspace will build a procurement profile as source facts become clearer."
                />
              </div>
              </Card>
            </div>
          ) : null}
    </div>
  )

  const samMarketIntelligenceContent = (
    <div className="workspace-scoring-panel">
      <Card title="Past Performance Map">
        <div className="workspace-action-column">
          <div className="artifact-note-box">
            <div className="row-title">Relevance Summary</div>
            <div className="structured-copy">{pastPerformanceMap.summary || 'No past performance map is available yet.'}</div>
          </div>
          {pastPerformanceMatches.length === 0 ? (
            <EmptyState
              title="No strong past performance match yet"
              subtitle="Add company past performance records so this workspace can map relevant service projects to the solicitation."
            />
          ) : (
            <div className="workspace-summary-grid sam-brief-grid">
              {pastPerformanceMatches.map((item, index) => (
                <Card key={`past-performance-${item.id || index}`} className="vendor-card">
                  <div className="vendor-header">
                    <div className="vendor-id">{item.project_title || 'Past performance record'}</div>
                    <StatusPill status={`Score ${item.score || 0}`} />
                  </div>
                  <div className="panel-subtitle">
                    {[
                      item.client_name || '',
                      item.naics_code ? `NAICS ${item.naics_code}` : '',
                      item.project_value ? formatCurrency(item.project_value) : '',
                    ].filter(Boolean).join(' | ')}
                  </div>
                  <div className="structured-copy">
                    {formatBriefText(item.description || 'No description saved for this past performance record.', { punctuate: false })}
                  </div>
                  <div className="sam-chip-list">
                    {(item.reasons || []).map((reason, reasonIndex) => (
                      <div key={`past-performance-reason-${index}-${reasonIndex}`} className="sam-chip">{reason}</div>
                    ))}
                  </div>
                </Card>
              ))}
            </div>
          )}
          {pastPerformanceGaps.length > 0 ? (
            <div className="artifact-section">
              <div className="row-title">Coverage Gaps</div>
              <div className="artifact-list">
                {pastPerformanceGaps.map((item, index) => (
                  <div key={`past-performance-gap-${index}`} className="artifact-list-item">{item}</div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </Card>

      <Card title="Market Intelligence">
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button
              variant="secondary"
              loading={usaspendingResearchQuery.isFetching}
              onClick={() => usaspendingResearchQuery.refetch()}
            >
              Refresh USAspending Research
            </Button>
          </div>
          {usaspendingVendors.length > 0 ? (
            <div className="panel-subtitle">
              Showing {Math.min(usaspendingVendors.length, 8)} likely prior awardee{Math.min(usaspendingVendors.length, 8) === 1 ? '' : 's'} from USAspending history.
            </div>
          ) : null}
          {usaspendingHistoryMatchLabel ? (
            <div className={`settings-summary-box ${usaspendingHistoryMatchSource === 'fallback' ? 'research-warning-box' : ''}`}>
              <div className="row-title">History Match Quality</div>
              <div className="row-subtitle">{usaspendingHistoryMatchLabel}</div>
              <div className="row-subtitle">{usaspendingHistoryMatchQueryLabel || 'No successful query path yet.'}</div>
            </div>
          ) : null}
        </div>

        {storedAwardHistoryRows.length > 0 ? (
          <div className="vendor-grid">
            {(storedAwardees.length ? storedAwardees : storedAwardHistoryRows).slice(0, 8).map((awardee, index) => {
              const relatedAwards = storedAwardHistoryRows.filter((award) =>
                (awardee.recipient_name && award.recipient_name === awardee.recipient_name)
                || (awardee.recipient_cage && award.recipient_cage === awardee.recipient_cage)
              )
              const firstAward = relatedAwards[0] || awardee
              return (
                <Card key={`${awardee.recipient_name || awardee.recipient_cage || index}-sam-awardee`} className="vendor-card">
                  <div className="vendor-header">
                    <div className="vendor-id">{awardee.recipient_name || firstAward.recipient_name || 'Awardee unavailable'}</div>
                    <StatusPill status={awardee.best_confidence || firstAward.match_confidence || 'Award History'} />
                  </div>
                  <div className="panel-subtitle">
                    {compactMeta([
                      awardee.recipient_cage || firstAward.recipient_cage ? `CAGE ${awardee.recipient_cage || firstAward.recipient_cage}` : '',
                      awardee.award_count ? `Awards ${awardee.award_count}` : '',
                      Number(awardee.total_award_amount) ? `Total ${formatCurrency(awardee.total_award_amount)}` : '',
                      awardee.latest_award_date ? `Latest ${formatDateOnly(awardee.latest_award_date)}` : '',
                      (awardee.sources || []).join(' + '),
                    ]) || 'Stored award evidence is available.'}
                  </div>
                  <BriefDetailsBox
                    title="Why This Awardee Matters"
                    items={[
                      formatDetailLine('Evidence', `${awardee.best_confidence || firstAward.match_confidence || 'Stored'} match`),
                      formatDetailLine('Match Score', awardee.best_score || firstAward.match_score || ''),
                      formatDetailLine('PSC / FSC', firstAward.psc_code || ''),
                    ]}
                    emptyMessage="No matching rationale is available yet."
                  />
                  {relatedAwards.slice(0, 2).map((award, awardIndex) => (
                    <div key={`${award.award_id || awardIndex}-sam-award`} className="vendor-award-snippet">
                      <div className="row-title">{award.award_id || award.piid || 'Award record unavailable'}</div>
                      <div className="row-subtitle">
                        {compactMeta([
                          award.source_system || '',
                          formatDateOnly(award.award_date),
                          formatAwardAmount(award.award_amount),
                        ])}
                      </div>
                      <div className="structured-copy">{formatBriefText(award.description || 'No description available', { punctuate: false })}</div>
                    </div>
                  ))}
                </Card>
              )
            })}
          </div>
        ) : usaspendingResearchQuery.isLoading ? (
          <LoadingState label="Loading market intelligence..." />
        ) : usaspendingResearchQuery.error ? (
          <EmptyState title="USAspending research unavailable" subtitle="Market intelligence could not be loaded for this opportunity." />
        ) : usaspendingVendors.length === 0 ? (
          <EmptyState title="No award history yet" subtitle="Run USAspending research to pull likely prior awardees and contract history." />
        ) : (
          <div className="vendor-grid">
            {usaspendingVendors.slice(0, 8).map((vendor, index) => (
              <Card key={`${vendor.vendor}-${index}`} className="vendor-card">
                <div className="vendor-header">
                  <div className="vendor-id">{vendor.vendor}</div>
                  <StatusPill status="Past Awardee" />
                </div>
                <div className="panel-subtitle">
                  {compactMeta([
                    `Award Count ${vendor.award_count || 0}`,
                    Number(vendor.total_award_amount) ? `Total Awards ${formatCurrency(vendor.total_award_amount)}` : '',
                    vendor.last_award_date ? `Last Award ${formatDateOnly(vendor.last_award_date)}` : '',
                  ]) || 'Past-award details are still limited.'}
                </div>
                <BriefDetailsBox
                  title="Why This Awardee Matters"
                  items={formatAwardeeSignalList([...(vendor.why_matched || []), ...(vendor.match_reasons || [])])}
                  emptyMessage="No matching rationale is available yet."
                />
                {(vendor.sample_awards || []).slice(0, 2).map((award, awardIndex) => (
                  <div key={`${vendor.vendor}-sam-award-${awardIndex}`} className="vendor-award-snippet">
                    <div className="row-title">{award.award_id || 'Award record unavailable'}</div>
                    <div className="row-subtitle">
                      {compactMeta([
                        formatDateOnly(award.start_date),
                        formatAwardAmount(award.award_amount),
                        formatBriefText(award.awarding_agency || '', { punctuate: false }) || 'Agency unavailable',
                      ])}
                    </div>
                    <div className="structured-copy">{formatBriefText(award.description || 'No description available', { punctuate: false })}</div>
                  </div>
                ))}
              </Card>
            ))}
          </div>
        )}
      </Card>
    </div>
  )

  const vendorsContent = (
    <div className="workspace-vendors">
      <Card title="Sourcing Candidates">
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button loading={generateVendorsMutation.isPending} onClick={() => generateVendorsMutation.mutate()}>
              Generate Vendor Shortlist
            </Button>
          </div>
          {sourcingCandidates.length > 0 ? (
            <div className="panel-subtitle">
              Showing {sourcingCandidates.length} sourcing candidate{sourcingCandidates.length === 1 ? '' : 's'} with lead-backed entries first.
            </div>
          ) : null}
          {vendorLeadsQuery.isLoading ? (
          <LoadingState label="Loading sourcing candidates..." />
        ) : sourcingCandidates.length === 0 ? (
          <EmptyState title="No sourcing candidates yet" subtitle="Generate vendor research or seed award history to start sourcing outreach." />
        ) : (
          <div className="vendor-grid">
            {sourcingCandidates.map((candidate, index) => (
              <Card key={`${candidate.identityKey}-${candidate.leadId || index}`} className="vendor-card">
                <div className="vendor-header">
                  <div className="vendor-id">{candidate.company_name || candidate.cage || `Candidate ${index + 1}`}</div>
                  {candidate.hasLead ? (
                    <StatusPill status={candidate.status || 'NEW'} />
                  ) : (
                    <Badge
                      label={humanizeLabel(candidate.candidate_quality || 'supporting', 'Supporting')}
                      variant={candidate.candidate_quality === 'preferred' ? 'success' : 'info'}
                    />
                  )}
                </div>
                <div className="panel-subtitle">
                  {compactMeta([
                    candidate.cage ? `CAGE ${candidate.cage}` : '',
                    candidate.part_number ? `Part ${candidate.part_number}` : '',
                    candidate.sourceTags.join(' + '),
                  ]) || 'Sourcing details are still being organized.'}
                </div>
                {candidate.contact.website || candidate.contact.email || candidate.contact.phone ? (
                  <div className="vendor-contact-strip">
                    {candidate.contact.website ? (
                      <a href={candidate.contact.website} target="_blank" rel="noreferrer">
                        Website
                      </a>
                    ) : null}
                    {candidate.contact.email ? <span>{candidate.contact.email}</span> : null}
                    {candidate.contact.phone ? <span>{candidate.contact.phone}</span> : null}
                  </div>
                ) : null}
                {candidate.provider_item ? (
                  <div className="panel-subtitle">
                    Item: {formatBriefText(candidate.provider_item, { punctuate: false })}
                  </div>
                ) : null}
                {candidate.why ? (
                  <div className="artifact-note-box">
                    <div className="row-title">Why This Candidate Matters</div>
                    <div className="structured-copy">{formatBriefText(candidate.why, { punctuate: false })}</div>
                  </div>
                ) : null}
                {candidate.hasLead ? (
                  <div className="table-action-stack">
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={targetedEmailMutation.isPending}
                      onClick={() =>
                        targetedEmailMutation.mutate({
                          opportunity_id: Number(id),
                          vendor_lead_id: candidate.leadId,
                        })
                      }
                    >
                      Draft Outreach
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={promoteVendorLeadMutation.isPending}
                      onClick={() =>
                        promoteVendorLeadMutation.mutate({
                          opportunity_id: Number(id),
                          vendor_lead_id: candidate.leadId,
                        })
                      }
                    >
                      Promote to Quote Task
                    </Button>
                  </div>
                ) : null}
              </Card>
            ))}
          </div>
        )}
        </div>
      </Card>

        <Card title="Outreach & Quotes">
          <div className="workspace-action-column">
            <div className="results-toolbar">
              <div className="panel-subtitle">
                Keep sourcing candidates, outreach drafts, and quote follow-ups in one working lane.
              </div>
              <div className="company-form-actions">
                <Button loading={generateEmailMutation.isPending} onClick={() => generateEmailMutation.mutate()}>
                  {emailArtifact ? 'Refresh Outreach Draft' : 'Generate Outreach Draft'}
                </Button>
                <Button variant="secondary" loading={seedQuotesMutation.isPending} onClick={() => seedQuotesMutation.mutate()}>
                  {vendorQuotes.length > 0 ? 'Refresh From Leads' : 'Seed Quote Tracker'}
                </Button>
              </div>
            </div>

            {!emailArtifact ? (
              <EmptyState
                title="No outreach draft yet"
                subtitle="Generate a quote-request draft grounded in the solicitation and current sourcing candidates."
              />
            ) : (
              <div className="artifact-embedded-panel">
                <div className="row-title">Outreach Draft</div>
                {outreachSourceSummary ? (
                  <div className="panel-subtitle">{outreachSourceSummary}</div>
                ) : null}
                {emailVendorAsks.length ? (
                  <div className="artifact-note-box">
                    <div className="row-title">Vendor Ask List</div>
                    <div className="panel-subtitle">{emailVendorAsks.slice(0, 4).join(' | ')}</div>
                  </div>
                ) : null}
                <Input
                  label="Subject"
                  value={emailDraft.subject}
                  onChange={(event) => setEmailDraft((current) => ({ ...current, subject: event.target.value }))}
                />
                <div className="company-form-stack">
                  <label className="textarea-label">Body</label>
                  <textarea
                    className="textarea-field textarea-tall"
                    value={emailDraft.body}
                    onChange={(event) => setEmailDraft((current) => ({ ...current, body: event.target.value }))}
                  />
                </div>
                <div className="company-form-actions">
                  <Button
                    loading={updateArtifactMutation.isPending}
                    onClick={async () => {
                      await updateArtifactMutation.mutateAsync({
                        artifactId: emailArtifact.id,
                        body: {
                          content_json: {
                            ...emailArtifact.content_json,
                            subject: emailDraft.subject,
                            body: emailDraft.body,
                          },
                        },
                      })
                      await outreachLogMutation.mutateAsync({
                        artifactId: emailArtifact.id,
                        body: {
                          action: 'draft_saved',
                          recipient: emailArtifact.content_json?.target_vendor_email || emailArtifact.content_json?.to,
                          vendor_name: emailArtifact.content_json?.target_vendor_name || emailArtifact.content_json?.company_name,
                        },
                      })
                    }}
                  >
                    Save Draft
                  </Button>
                </div>
              </div>
            )}

            {vendorQuotesQuery.isLoading ? (
              <LoadingState label="Loading vendor quotes..." />
            ) : vendorQuotes.length === 0 ? (
              <EmptyState
                title="No quote records yet"
                subtitle="Seed quote records from the current sourcing candidates, then log responses here as vendors reply."
              />
            ) : (
              <>
                <div className="results-toolbar">
                  <div className="panel-subtitle">Tracking {vendorQuotes.length} vendor quote {vendorQuotes.length === 1 ? 'record' : 'records'}</div>
                  <div className="company-form-actions">
                    <Button variant="secondary" onClick={exportQuoteComparisonCsv}>
                      Export Quote Comparison
                    </Button>
                    <Button variant="secondary" onClick={printBidSummary}>
                      Print Bid Summary
                    </Button>
                  </div>
                </div>
                <div className="quote-follow-up-summary">
                  <button type="button" className={`quote-filter-chip ${quoteFilter === 'all' ? 'quote-filter-active' : ''}`} onClick={() => setQuoteFilter('all')}>
                    All {quoteFollowUpSummary.total}
                  </button>
                  <button type="button" className={`quote-filter-chip ${quoteFilter === 'due' ? 'quote-filter-active' : ''}`} onClick={() => setQuoteFilter('due')}>
                    Due {quoteFollowUpSummary.due}
                  </button>
                  <button type="button" className={`quote-filter-chip ${quoteFilter === 'requested' ? 'quote-filter-active' : ''}`} onClick={() => setQuoteFilter('requested')}>
                    Requested {quoteFollowUpSummary.requested}
                  </button>
                  <button type="button" className={`quote-filter-chip ${quoteFilter === 'received' ? 'quote-filter-active' : ''}`} onClick={() => setQuoteFilter('received')}>
                    Received {quoteFollowUpSummary.received}
                  </button>
                  <button type="button" className={`quote-filter-chip ${quoteFilter === 'not_requested' ? 'quote-filter-active' : ''}`} onClick={() => setQuoteFilter('not_requested')}>
                    Not Requested {quoteFollowUpSummary.notRequested}
                  </button>
                </div>
                {quoteFollowUpSummary.due > 0 ? (
                  <div className="quote-follow-up-alert">
                    <div>
                      <div className="row-title">Follow-ups Due</div>
                      <div className="panel-subtitle">{quoteFollowUpSummary.due} vendor {quoteFollowUpSummary.due === 1 ? 'needs' : 'need'} a quote follow-up today.</div>
                    </div>
                    <Button size="sm" variant="secondary" onClick={() => setQuoteFilter('due')}>
                      View Due
                    </Button>
                  </div>
                ) : null}
                <div className="vendor-grid">
                  {visibleVendorQuotes.length === 0 ? (
                    <EmptyState
                      title="No quotes match this filter"
                      subtitle="Try another quote status filter or refresh from vendor leads."
                    />
                  ) : visibleVendorQuotes.map((quote) => (
                  <Card key={quote.id} className="vendor-card">
                    <div className="vendor-header">
                      <div className="vendor-id">{quote.company_name || quote.cage || `Quote ${quote.id}`}</div>
                      <StatusPill status={quote.status || 'NEW'} />
                    </div>
                    <div className="panel-subtitle">
                      {compactMeta([
                        quote.cage ? `CAGE ${quote.cage}` : '',
                        quote.part_number ? `Part ${quote.part_number}` : '',
                        Number.isFinite(Number(quote.unit_price)) ? `Unit Price ${formatCurrency(quote.unit_price)}` : '',
                        quote.lead_time_days ? `Lead Time ${quote.lead_time_days} days` : '',
                      ]) || 'Quote details have not been entered yet.'}
                    </div>
                    <div className="artifact-note-box">
                      <div className="row-title">{recommendedQuote?.id === quote.id ? 'Recommended Quote Candidate' : 'Quote Snapshot'}</div>
                      <div className="panel-subtitle">
                        Status: {humanizeLabel(quoteComparison.find((item) => item.id === quote.id)?.normalized_status || quote.status, '-')}
                        {quote.unit_price ? ` | ${formatCurrency(quote.unit_price)}` : ''}
                        {quote.lead_time_days ? ` | ${quote.lead_time_days} day lead time` : ''}
                      </div>
                    </div>
                    <div className={`quote-follow-up-box ${quote.follow_up_due ? 'quote-follow-up-due' : ''}`}>
                      <div className="quote-follow-up-header">
                        <div className="row-title">Follow-up</div>
                        <Badge
                          label={quote.follow_up_label || 'No follow-up schedule'}
                          variant={quote.follow_up_due ? 'warning' : quote.follow_up_status === 'CLOSED' ? 'success' : 'info'}
                        />
                      </div>
                      <div className="panel-subtitle">
                        {compactMeta([
                          quote.requested_at ? `Requested ${formatDateOnly(quote.requested_at)}` : '',
                          quote.last_follow_up_at ? `Last ${formatDateOnly(quote.last_follow_up_at)}` : '',
                          quote.follow_up_count ? `${quote.follow_up_count} follow-up${quote.follow_up_count === 1 ? '' : 's'}` : '',
                        ]) || 'A follow-up schedule starts after the quote request is sent.'}
                      </div>
                    </div>
                    <div className="company-form-grid">
                      <Input label="Status" value={quote.status || ''} onChange={(event) => patchVendorQuoteDraft(quote.id, 'status', event.target.value)} />
                      <Input label="Unit Price" type="number" value={quote.unit_price ?? ''} onChange={(event) => patchVendorQuoteDraft(quote.id, 'unit_price', event.target.value === '' ? '' : Number(event.target.value))} />
                      <Input label="Lead Time Days" type="number" value={quote.lead_time_days ?? ''} onChange={(event) => patchVendorQuoteDraft(quote.id, 'lead_time_days', event.target.value === '' ? '' : Number(event.target.value))} />
                      <Input label="Contact Email" value={quote.email || ''} onChange={(event) => patchVendorQuoteDraft(quote.id, 'email', event.target.value)} />
                    </div>
                    <div className="company-form-stack">
                      <label className="textarea-label">Notes</label>
                      <textarea className="textarea-field" value={quote.notes || ''} onChange={(event) => patchVendorQuoteDraft(quote.id, 'notes', event.target.value)} />
                    </div>
                    <div className="company-form-actions">
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={isClosedSolicitation}
                        onClick={() => useQuoteForSubmission(quote)}
                      >
                        Use for Submission
                      </Button>
                      <Button
                        size="sm"
                        loading={upsertVendorQuoteMutation.isPending}
                        onClick={() =>
                          upsertVendorQuoteMutation.mutate({
                            opportunity_id: Number(id),
                            cage: quote.cage,
                            part_number: quote.part_number || null,
                            company_name: quote.company_name || null,
                            email: quote.email || null,
                            status: quote.status || null,
                            unit_price: quote.unit_price === '' ? null : quote.unit_price,
                            lead_time_days: quote.lead_time_days === '' ? null : quote.lead_time_days,
                            notes: quote.notes || null,
                          })
                        }
                      >
                        Save Quote Response
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={String(quote.status || '').toUpperCase() !== 'REQUESTED'}
                        loading={logQuoteFollowUpMutation.isPending}
                        onClick={() =>
                          logQuoteFollowUpMutation.mutate({
                            quoteId: quote.id,
                            notes: `Follow-up logged for ${quote.company_name || quote.cage || 'vendor'}.`,
                          })
                        }
                      >
                        Log Follow-up
                      </Button>
                    </div>
                  </Card>
                  ))}
                </div>
              </>
            )}
          </div>
        </Card>

      <Card title="Past Awardees">
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button
              variant="secondary"
              loading={usaspendingResearchQuery.isFetching}
              onClick={() => usaspendingResearchQuery.refetch()}
            >
              Refresh USAspending Research
            </Button>
            <Button
              variant="secondary"
              loading={runNsnIntelligenceMutation.isPending}
              onClick={() => runNsnIntelligenceMutation.mutate()}
            >
              Run NSN Intelligence
            </Button>
            <Button
              variant="secondary"
              loading={seedUsaspendingMutation.isPending}
              onClick={() => seedUsaspendingMutation.mutate('product_only')}
            >
              Seed Product-Like Leads
            </Button>
            <Button
              variant="secondary"
              loading={seedUsaspendingMutation.isPending}
              onClick={() => seedUsaspendingMutation.mutate('strict')}
            >
              Seed Strict Leads
            </Button>
          </div>
          {seedUsaspendingMutation.data ? (
            <div className="panel-subtitle">
              Seeded {seedUsaspendingMutation.data.seeded_count || 0} USAspending leads.
            </div>
          ) : null}
          {usaspendingVendors.length > 0 ? (
            <div className="panel-subtitle">
              Showing {Math.min(usaspendingVendors.length, 8)} likely past awardee{Math.min(usaspendingVendors.length, 8) === 1 ? '' : 's'} from USAspending history.
            </div>
          ) : null}
          {usaspendingHistoryMatchLabel ? (
            <div className={`settings-summary-box ${usaspendingHistoryMatchSource === 'fallback' ? 'research-warning-box' : ''}`}>
              <div className="row-title">History Match Quality</div>
              <div className="row-subtitle">{usaspendingHistoryMatchLabel}</div>
              <div className="row-subtitle">{usaspendingHistoryMatchQueryLabel || 'No successful query path yet.'}</div>
            </div>
          ) : null}
          {nsnTarget.nsn || nsnHistory.awards_found || nsnVendorProfiles.length || nsnAwardHistory.stored_count ? (
            <BriefDetailsBox
              title="NSN Intelligence"
              items={[
                formatDetailLine('NSN', nsnTarget.nsn || '-'),
                formatDetailLine('Item', nsnTarget.nomenclature || '-'),
                formatDetailLine('FSC / PSC', nsnTarget.fsc || '-'),
                formatDetailLine('Stored Award History', nsnAwardHistory.stored_count ?? nsnHistory.awards_found ?? '-'),
                formatDetailLine('High-Confidence Matches', `${nsnAwardConfidence.exact || 0} exact | ${nsnAwardConfidence.strong || 0} strong`),
                formatDetailLine('SAM Validated Records', nsnSamValidation.validated_count ?? '-'),
                formatDetailLine('Likely Vendors', nsnVendorProfiles.length || '-'),
                formatDetailLine('Average Unit Price', formatCurrency(nsnPricing.unit_price_average)),
              ]}
            />
          ) : null}
        </div>

        {storedAwardHistoryRows.length > 0 ? (
          <div className="vendor-grid">
            {(storedAwardees.length ? storedAwardees : storedAwardHistoryRows).slice(0, 8).map((awardee, index) => {
              const relatedAwards = storedAwardHistoryRows.filter((award) =>
                (awardee.recipient_name && award.recipient_name === awardee.recipient_name)
                || (awardee.recipient_cage && award.recipient_cage === awardee.recipient_cage)
              )
              const firstAward = relatedAwards[0] || awardee
              return (
                <Card key={`${awardee.recipient_name || awardee.recipient_cage || index}-stored-awardee`} className="vendor-card">
                  <div className="vendor-header">
                    <div className="vendor-id">{awardee.recipient_name || firstAward.recipient_name || 'Awardee unavailable'}</div>
                    <StatusPill status={awardee.best_confidence || firstAward.match_confidence || 'Award History'} />
                  </div>
                  <div className="panel-subtitle">
                    {compactMeta([
                      awardee.recipient_cage || firstAward.recipient_cage ? `CAGE ${awardee.recipient_cage || firstAward.recipient_cage}` : '',
                      awardee.award_count ? `Awards ${awardee.award_count}` : '',
                      Number(awardee.total_award_amount) ? `Total ${formatCurrency(awardee.total_award_amount)}` : '',
                      awardee.latest_award_date ? `Latest ${formatDateOnly(awardee.latest_award_date)}` : '',
                      (awardee.sources || []).join(' + '),
                    ]) || 'Stored award evidence is available.'}
                  </div>
                  <BriefDetailsBox
                    title="Why This Awardee Matters"
                    items={[
                      formatDetailLine('Evidence', `${awardee.best_confidence || firstAward.match_confidence || 'Stored'} match`),
                      formatDetailLine('Match Score', awardee.best_score || firstAward.match_score || ''),
                      formatDetailLine('PSC / FSC', firstAward.psc_code || ''),
                    ]}
                    emptyMessage="No matching rationale is available yet."
                  />
                  {relatedAwards.slice(0, 2).map((award, awardIndex) => (
                    <div key={`${award.award_id || awardIndex}-stored-award`} className="vendor-award-snippet">
                      <div className="row-title">{award.award_id || award.piid || 'Award record unavailable'}</div>
                      <div className="row-subtitle">
                        {compactMeta([
                          award.source_system || '',
                          formatDateOnly(award.award_date),
                          formatAwardAmount(award.award_amount),
                        ])}
                      </div>
                      <div className="structured-copy">{formatBriefText(award.description || 'No description available', { punctuate: false })}</div>
                      <div className="row-subtitle">
                        {(award.match_reasons || []).map((reason) => humanizeAwardeeSignal(reason)).join(' | ') || 'No supporting evidence captured'}
                      </div>
                    </div>
                  ))}
                  <div className="table-action-stack">
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={targetedEmailMutation.isPending}
                      onClick={() =>
                        targetedEmailMutation.mutate({
                          opportunity_id: Number(id),
                          vendor_name: awardee.recipient_name || firstAward.recipient_name,
                        })
                      }
                    >
                      Draft Awardee Email
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
        ) : usaspendingResearchQuery.isLoading ? (
          <LoadingState label="Loading USAspending awardees..." />
        ) : usaspendingResearchQuery.error ? (
          <EmptyState title="USAspending research unavailable" subtitle="Workspace vendor research could not be loaded." />
        ) : usaspendingVendors.length === 0 ? (
          <EmptyState title="No USAspending vendor results" subtitle="This opportunity does not yet have likely awardees from USAspending research." />
        ) : (
          <div className="vendor-grid">
            {usaspendingVendors.slice(0, 8).map((vendor, index) => (
              <Card key={`${vendor.vendor}-${index}`} className="vendor-card">
                <div className="vendor-header">
                  <div className="vendor-id">{vendor.vendor}</div>
                  <StatusPill status="Past Awardee" />
                </div>
                <div className="panel-subtitle">
                  {compactMeta([
                    `Award Count ${vendor.award_count || 0}`,
                    Number(vendor.total_award_amount) ? `Total Awards ${formatCurrency(vendor.total_award_amount)}` : '',
                    vendor.last_award_date ? `Last Award ${formatDateOnly(vendor.last_award_date)}` : '',
                  ]) || 'Past-award details are still limited.'}
                </div>
                <BriefDetailsBox
                  title="Why This Awardee Matters"
                  items={formatAwardeeSignalList(vendor.why_matched || [])}
                  emptyMessage="No matching rationale is available yet."
                />
                <BriefDetailsBox
                  title="Supporting Evidence"
                  items={formatAwardeeSignalList(vendor.match_reasons || [])}
                  emptyMessage="No supporting evidence was captured."
                />
                {(vendor.sample_awards || []).slice(0, 2).map((award, awardIndex) => (
                  <div key={`${vendor.vendor}-award-${awardIndex}`} className="vendor-award-snippet">
                    <div className="row-title">{award.award_id || 'Award record unavailable'}</div>
                    <div className="row-subtitle">
                      {compactMeta([
                        formatDateOnly(award.start_date),
                        formatAwardAmount(award.award_amount),
                        formatBriefText(award.awarding_agency || '', { punctuate: false }) || 'Agency unavailable',
                      ])}
                    </div>
                    <div className="structured-copy">{formatBriefText(award.description || 'No description available', { punctuate: false })}</div>
                    <div className="row-subtitle">
                      {formatAwardeeSignalList(award.relevance_reasons || []).join(' | ') || 'No supporting evidence captured'}
                    </div>
                  </div>
                ))}
                <div className="table-action-stack">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={targetedEmailMutation.isPending}
                    onClick={() =>
                      targetedEmailMutation.mutate({
                        opportunity_id: Number(id),
                        vendor_name: vendor.vendor,
                      })
                    }
                  >
                    Draft Awardee Email
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>
    </div>
  )

  const documentsContent = (
    <div className="workspace-documents-panel">
      <Card title={documentsCardTitle}>
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button loading={downloadPdfsMutation.isPending || isIntakeRunning} onClick={() => downloadPdfsMutation.mutate()}>
              {documentsButtonLabel}
            </Button>
          </div>
          {isSamOpportunity && samDocumentInventory.length > 0 ? (
            <div className="workspace-summary-grid sam-brief-grid">
              <Card title="Document Set">
                <div className="artifact-list">
                  {samDocumentInventory.map((item, index) => (
                    <div key={`sam-doc-inventory-${item.file_id || index}`} className="artifact-list-item">
                      <strong>{item.document_type || 'Document'}:</strong> {item.filename}
                      {item.amendment_number ? ` | ${item.amendment_number}` : ''}
                    </div>
                  ))}
                </div>
              </Card>
              <Card title="Amendment Tracker">
                {samAmendments.length === 0 ? (
                  <div className="panel-subtitle">No amendments are currently identified in the downloaded document set.</div>
                ) : (
                  <div className="artifact-list">
                    {samAmendments.map((item, index) => (
                      <div key={`sam-amendment-${index}`} className="artifact-list-item">
                        <strong>{item.amendment_number || 'Amendment'}:</strong> {item.filename}
                        {item.return_by ? ` | Due ${formatDateTime(item.return_by)}` : ''}
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          ) : null}
          {activeIntakeJob ? (
            <div className="search-progress-box">
              <div className="search-progress-header">
                <div>
                  <div className="row-title">
                    {activeIntakeJob.status === 'success'
                      ? 'Document intake complete'
                      : activeIntakeJob.status === 'failed'
                        ? 'Document intake failed'
                        : 'Document intake in progress'}
                  </div>
                  <div className="row-subtitle">
                    {activeIntakeJob.status === 'failed'
                      ? activeIntakeJob.error || 'Pipeline failed.'
                      : activeIntakeJob.progress?.current_label || 'Starting pipeline'}
                  </div>
                </div>
                <strong>{activeIntakeJob.progress?.percent || 0}%</strong>
              </div>
              <div className="search-progress-track">
                <div className="search-progress-fill" style={{ width: `${activeIntakeJob.progress?.percent || 0}%` }} />
              </div>
              <div className="row-subtitle">
                {(activeIntakeJob.progress?.completed_steps || 0)} of {(activeIntakeJob.progress?.total_steps || 0)} step{(activeIntakeJob.progress?.total_steps || 0) === 1 ? '' : 's'} complete.
              </div>
              {dibbsSourceUnavailable ? (
                <div className="workspace-mode-banner" style={{ marginTop: 12 }}>
                  <div className="row-title">DIBBS temporarily unavailable</div>
                  <div className="panel-subtitle">
                    {dibbsSourceUnavailable.message || 'DIBBS appears to be under maintenance. Retry the official PDF download later.'}
                  </div>
                </div>
              ) : null}
            </div>
          ) : null}
          {filesQuery.isLoading ? (
            <LoadingState label={documentsLoadingLabel} />
          ) : visibleFiles.length === 0 ? (
            <EmptyState
              title={documentsEmptyTitle}
              subtitle={documentsEmptySubtitle}
            />
          ) : isCompactWorkspace ? (
            <div className="workspace-mobile-card-list">
              {visibleFiles.map((file) => (
                <div key={file.id} className="workspace-mobile-card">
                  <button
                    type="button"
                    className={`document-select-button ${selectedFileId === file.id ? 'selected' : ''}`}
                    onClick={() => setSelectedFileId(file.id)}
                  >
                    {file.filename}
                  </button>
                  <div className="workspace-mobile-card-meta">
                    <StatusPill status={getDocumentStatusLabel(file)} />
                    {file.review_required ? (
                      <div className="panel-subtitle">Review recommended</div>
                    ) : null}
                  </div>
                  <div className="workspace-mobile-card-actions">
                    <a className="action-btn-small" href={`${API_BASE_URL}/api/files/download/${file.id}`} target="_blank" rel="noreferrer">Download</a>
                    <Button
                      size="sm"
                      variant="secondary"
                      loading={parseFileMutation.isPending && parseFileMutation.variables === file.id}
                      onClick={() => parseFileMutation.mutate(file.id)}
                    >
                      {getDocumentStatusLabel(file) === 'Failed' ? 'Retry' : 'Reprocess'}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Filename</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleFiles.map((file) => (
                  <TableRow key={file.id}>
                    <TableCell>
                      <button
                        type="button"
                        className={`document-select-button ${selectedFileId === file.id ? 'selected' : ''}`}
                        onClick={() => setSelectedFileId(file.id)}
                      >
                        {file.filename}
                      </button>
                    </TableCell>
                    <TableCell>
                      <div className="workspace-action-column">
                        <StatusPill status={getDocumentStatusLabel(file)} />
                        {file.review_required ? (
                          <div className="panel-subtitle">Review recommended</div>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="table-action-stack">
                        <a className="action-btn-small" href={`${API_BASE_URL}/api/files/download/${file.id}`} target="_blank" rel="noreferrer">Download</a>
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={parseFileMutation.isPending && parseFileMutation.variables === file.id}
                          onClick={() => parseFileMutation.mutate(file.id)}
                        >
                          {getDocumentStatusLabel(file) === 'Failed' ? 'Retry' : 'Reprocess'}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
          {!selectedFile ? (
            <EmptyState
              title="No file selected"
              subtitle="Choose a document to review its processing status."
            />
          ) : fileInsightsQuery.isLoading ? (
            <LoadingState label="Loading document insights..." />
          ) : fileInsightsQuery.error ? (
            <EmptyState
              title="Document insights unavailable"
              subtitle={`We couldn't load insights for ${selectedFile.filename}.`}
            />
          ) : (
            <div className="workspace-detail-panel">
              <div className="workspace-summary-grid">
                <div>
                  <div className="row-title">{fileInsights?.filename || selectedFile.filename}</div>
                  <div className="row-subtitle">
                    {documentsInsightsSubtitle}
                  </div>
                </div>
                <div className="workspace-action-column">
                  <StatusPill status={getDocumentStatusLabel(fileInsights || selectedFile)} />
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={parseFileMutation.isPending && parseFileMutation.variables === selectedFile.id}
                    onClick={() => parseFileMutation.mutate(selectedFile.id)}
                  >
                    {getDocumentStatusLabel(fileInsights || selectedFile) === 'Failed' ? 'Retry' : 'Reprocess'}
                  </Button>
                </div>
              </div>

              {parseFileMutation.data?.file_id === selectedFile.id ? (
                <div className="panel-subtitle">Latest document processing completed for {parseFileMutation.data.filename}.</div>
              ) : null}
            </div>
          )}
        </div>
      </Card>

      <Card title={packageReviewCardTitle}>
        {!complianceArtifact ? (
          <EmptyState
            title={packageReviewEmptyTitle}
            subtitle={packageReviewEmptySubtitle}
          />
        ) : (
          <div className="workspace-action-column">
            {isSamOpportunity ? (
              <div className="workspace-summary-grid sam-brief-grid">
                <Card title="Scope Map">
                  <div className="workspace-action-column">
                    <div className="artifact-note-box">
                      <div className="row-title">Service Pursuit Summary</div>
                      <div className="structured-copy">
                        {(samScopeMap.scope_summary || []).join(' ')}
                      </div>
                    </div>
                    <div className="artifact-section">
                      <div className="row-title">Performance Signals</div>
                      {(samScopeMap.performance_signals || []).length === 0 ? (
                        <div className="panel-subtitle">No service-performance signals have been extracted yet.</div>
                      ) : (
                        <div className="sam-chip-list">
                          {(samScopeMap.performance_signals || []).map((item, index) => (
                            <div key={`sam-signal-${index}`} className="sam-chip">{item}</div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </Card>
                <Card title="Conflict Detection">
                  {samConflictFlags.length === 0 ? (
                    <div className="artifact-note-box sam-okay-box">
                      <div className="row-title">No major document conflicts detected</div>
                      <div className="panel-subtitle">Due date, submission destination, period of performance, and page-limit signals are currently aligned across the loaded SAM document set.</div>
                    </div>
                  ) : (
                    <div className="workspace-action-column">
                      <div className="artifact-note-box sam-warning-box">
                        <div className="row-title">Review these document conflicts before shaping the proposal</div>
                      </div>
                      <div className="artifact-list">
                        {samConflictFlags.map((item, index) => (
                          <div key={`sam-conflict-${index}`} className="artifact-list-item">{item}</div>
                        ))}
                      </div>
                    </div>
                  )}
                </Card>
              </div>
            ) : null}
            <BriefDetailsBox
              title={packageFactsTitle}
              items={isSamOpportunity ? [
                formatDetailLine('Solicitation', samMergedFields.solicitation_number || factSolicitation || '-'),
                formatDetailLine('Agency', opp.agency || '-'),
                formatDetailLine('NAICS', samMergedFields.naics_code || factNaics || '-'),
                formatDetailLine('Set-Aside', samMergedFields.set_aside_hint ? setAsideBadgeLabel(samMergedFields.set_aside_hint) : (factSetAside ? setAsideBadgeLabel(factSetAside) : '-')),
                formatDetailLine('Place of Performance', samServiceSignals.place_of_performance || opp.place_of_performance || '-'),
                formatDetailLine('Period of Performance', samServiceSignals.period_of_performance || samMergedFields.period_of_performance || '-'),
                formatDetailLine('Return By', formatDateTime(samMergedFields.return_by || factReturnBy)),
                formatDetailLine('Submission Office', samMergedFields.submission_office_hint || factSubmissionOffice || '-'),
                formatDetailLine('Source File', factSourceFile || '-'),
              ] : [
                formatDetailLine('Solicitation', factSolicitation || '-'),
                formatDetailLine('NSN', factNsn || '-'),
                formatDetailLine('Item', factNomenclature || '-'),
                formatDetailLine('Quantity', factQuantity || '-'),
                formatDetailLine('Return By', formatDateTime(factReturnBy)),
                formatDetailLine('PR Number', factPrNumber || '-'),
                formatDetailLine('Delivery', factDeliveryDays ? `${factDeliveryDays} days ADO` : ''),
                formatDetailLine('FOB', factFobTerms || ''),
                formatDetailLine('Packaging', factPackaging || ''),
              ]}
            />
            <div className="artifact-note-box">
              <div className="row-title">{packageBasisTitle}</div>
              <div className="structured-copy">
                {formatBriefText(packageBasisText, { punctuate: true })}
              </div>
            </div>
            {isSamOpportunity ? (
              <>
                <div className="artifact-section">
                  <div className="row-title">Scope And Performance Signals</div>
                  <div className="artifact-list">
                    {(complianceArtifact.content_json?.document_findings || []).length ? (
                      (complianceArtifact.content_json?.document_findings || []).map((item, index) => (
                        <div key={`sam-finding-${index}`} className="artifact-list-item">{item}</div>
                      ))
                    ) : (
                      <div className="artifact-list-item">No scope or performance signals were extracted yet.</div>
                    )}
                  </div>
                </div>
                <div className="artifact-section">
                  <div className="row-title">Submission Requirements</div>
                  <div className="artifact-list">
                    {(complianceActionItems.length ? complianceActionItems : ['No submission requirements were extracted yet.']).map((item, index) => (
                      <div key={`sam-action-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                </div>
                <div className="artifact-section">
                  <div className="row-title">Evaluation Factors</div>
                  {samEvaluationFactors.length === 0 ? (
                    <div className="panel-subtitle">No clear evaluation factors have been extracted yet from the current document set.</div>
                  ) : (
                    <div className="sam-chip-list">
                      {samEvaluationFactors.map((item, index) => (
                        <div key={`sam-eval-${index}`} className="sam-chip">{item}</div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="artifact-section">
                  <div className="row-title">Required Attachments</div>
                  {samRequiredAttachments.length === 0 ? (
                    <div className="panel-subtitle">No explicit attachment requirements have been extracted yet.</div>
                  ) : (
                    <div className="artifact-list">
                      {samRequiredAttachments.map((item, index) => (
                        <div key={`sam-attachment-${index}`} className="artifact-list-item">{item}</div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="artifact-section">
                  <div className="row-title">Missing Or Unconfirmed Information</div>
                  {complianceNeedsReview.length === 0 ? (
                    <div className="panel-subtitle">No major gaps are currently flagged from the loaded documents.</div>
                  ) : (
                    <div className="artifact-list">
                      {complianceNeedsReview.map((item, index) => (
                        <div key={`sam-review-${index}`} className="artifact-list-item">{item}</div>
                      ))}
                    </div>
                  )}
                </div>
                <div className="artifact-section">
                  <div className="row-title">Amendment Notes</div>
                  {samAmendments.length === 0 ? (
                    <div className="panel-subtitle">No amendment notes are available yet.</div>
                  ) : (
                    <div className="artifact-list">
                      {samAmendments.flatMap((item, index) =>
                        (item.likely_changes || []).map((change, changeIndex) => (
                          <div key={`sam-amendment-note-${index}-${changeIndex}`} className="artifact-list-item">
                            <strong>{item.amendment_number || 'Amendment'}:</strong> {change}
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              </>
            ) : null}
          </div>
        )}
      </Card>
    </div>
  )

  const scoringContent = (
    <div className="workspace-scoring-panel">
      <Card title={workspaceProgressCardTitle}>
        {!pipeline ? (
          <EmptyState
            title="No pipeline record yet"
              subtitle={
                isArchivedOpportunity
                  ? 'This archived solicitation stays searchable for sourcing, pricing, documents, and extracted intelligence.'
                  : isClosedSolicitation
                  ? 'This closed solicitation can still be researched, but new active pipeline tracking is disabled.'
                  : 'Create a workspace record to start tracking review, proposal, and submission progress.'
              }
              action={isArchivedOpportunity ? null : (
                <Button
                  loading={ensurePipelineMutation.isPending}
                  disabled={isClosedSolicitation}
                  onClick={() => ensurePipelineMutation.mutate()}
                >
                  Create Workspace Record
                </Button>
              )}
            />
        ) : (
          <div className="workspace-action-column">
            <div><strong>Status:</strong> <StatusPill status={pipeline.decision_status} /></div>
            <div className="company-form-grid">
              <Input
                label="Owner"
                value={pipelineForm.owner}
                disabled={isClosedSolicitation}
                onChange={(event) => setPipelineForm((current) => ({ ...current, owner: event.target.value }))}
              />
              <div className="input-wrapper">
                <label className="input-label">Priority</label>
                <select
                  disabled={isClosedSolicitation}
                  value={pipelineForm.priority}
                  onChange={(event) => setPipelineForm((current) => ({ ...current, priority: event.target.value }))}
                >
                  <option value="">Not set</option>
                  <option value="LOW">Low</option>
                  <option value="MEDIUM">Medium</option>
                  <option value="HIGH">High</option>
                </select>
              </div>
              <Input
                label="Target Submit Date"
                type="datetime-local"
                value={pipelineForm.target_submit_date}
                disabled={isClosedSolicitation}
                onChange={(event) => setPipelineForm((current) => ({ ...current, target_submit_date: event.target.value }))}
              />
              {!isSamOpportunity ? (
                <Input
                  label="Probability of Win"
                  type="number"
                  min="0"
                  max="100"
                  value={pipelineForm.probability_of_win}
                  disabled={isClosedSolicitation}
                  onChange={(event) => setPipelineForm((current) => ({ ...current, probability_of_win: event.target.value }))}
                />
              ) : null}
            </div>
            <div className="company-form-stack">
              <label className="textarea-label">Notes</label>
              <textarea
                className="textarea-field"
                value={pipelineForm.notes}
                disabled={isClosedSolicitation}
                onChange={(event) => setPipelineForm((current) => ({ ...current, notes: event.target.value }))}
                placeholder="Add capture notes, risks, owner context, or next steps."
              />
            </div>
            <div className="company-form-actions">
              <Button
                loading={updatePipelineMutation.isPending || ensurePipelineMutation.isPending}
                disabled={isClosedSolicitation}
                onClick={savePipelineDetails}
              >
                Save Pipeline Details
              </Button>
              <div className="panel-subtitle">
                {isClosedSolicitation
                  ? 'Pipeline edits are disabled because this solicitation is closed.'
                  : `Last target submit date: ${formatDateTime(pipeline.target_submit_date)}`}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  )

  const tasksContent = (
    <div className="workspace-scoring-panel">
      <Card title={workspaceTasksCardTitle}>
        <div className="workspace-action-column">
          <div className="company-form-grid">
            <Input
              label="Task Type"
              value={newTaskForm.task_type}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, task_type: event.target.value }))}
            />
            <Input
              label="Due Date"
              type="datetime-local"
              value={newTaskForm.due_at}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, due_at: event.target.value }))}
            />
          </div>
          <div className="company-form-stack">
            <label className="textarea-label">Task Notes</label>
            <textarea
              className="textarea-field"
              value={newTaskForm.notes}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, notes: event.target.value }))}
              placeholder="Add the next action, dependency, or owner note."
            />
          </div>
          <div className="company-form-actions">
            <Button
              loading={createTaskMutation.isPending}
              disabled={isClosedSolicitation}
              onClick={() =>
                createTaskMutation.mutate({
                  opportunity_id: Number(id),
                  task_type: newTaskForm.task_type,
                  due_at: newTaskForm.due_at || null,
                  notes: newTaskForm.notes || null,
                })
              }
            >
              Add Task
            </Button>
            {isClosedSolicitation ? (
              <div className="panel-subtitle">Task creation is disabled for closed solicitations.</div>
            ) : null}
          </div>

          {visibleWorkspaceTasks.length === 0 ? (
            <EmptyState
              title={isSamOpportunity ? 'No planning tasks yet' : 'No tasks yet'}
              subtitle={isSamOpportunity ? 'Structured planning tasks will appear here once the proposal workflow is prepared.' : 'Add the next concrete actions for capture, quoting, and submission.'}
            />
          ) : (
            <div className="workspace-action-column">
              {visibleWorkspaceTasks.map((task) => (
                <div key={task.id} className="task-card">
                  <div className="task-card-row">
                    <div className="row-title">{formatWorkspaceTaskType(task.task_type, isSamOpportunity)}</div>
                    <select
                      disabled={isClosedSolicitation}
                      value={task.status}
                      onChange={(event) =>
                        updateTaskMutation.mutate({
                          taskId: task.id,
                          body: { status: event.target.value },
                        })
                      }
                    >
                      {TASK_STATUSES.map((status) => (
                        <option key={status} value={status}>{humanizeLabel(status)}</option>
                      ))}
                    </select>
                  </div>
                  <div className="row-subtitle">Due: {formatDateTime(task.due_at)}</div>
                  <textarea
                    className="textarea-field textarea-compact"
                    defaultValue={task.notes || ''}
                    disabled={isClosedSolicitation}
                    onBlur={(event) =>
                      updateTaskMutation.mutate({
                        taskId: task.id,
                        body: { notes: event.target.value },
                      })
                    }
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>
    </div>
  )

  const artifactsContent = (
    <div className="workspace-scoring-panel">
      {!isSamOpportunity ? (
        <Card title={checklistArtifactTitle}>
          {!checklistArtifact ? (
            <EmptyState
              title="No checklist yet"
              subtitle={checklistArtifactEmptySubtitle}
              action={<Button loading={generateChecklistMutation.isPending} onClick={() => generateChecklistMutation.mutate()}>Generate Checklist</Button>}
            />
          ) : (
            <div className="workspace-action-column">
              <div className="workspace-summary-grid">
                <div className="workspace-action-column">
                  <div><strong>Status:</strong> {checklistArtifact.content_json?.solicitation_status || solicitationStatus}</div>
                  <div><strong>Completed:</strong> {checklistCompletedCount} of {checklistTotalCount}</div>
                  <div><strong>Progress:</strong> {checklistProgress}%</div>
                </div>
                <div className="workspace-action-column">
                  <div><strong>NSN:</strong> {checklistArtifact.content_json?.nsn || parsedSummary.nsn || '-'}</div>
                  <div><strong>Solicitation:</strong> {checklistArtifact.content_json?.solicitation || opp.solicitation_number || '-'}</div>
                  <div><strong>Due:</strong> {formatDateTime(checklistArtifact.content_json?.due_at || opp.due_at)}</div>
                </div>
              </div>
              <div className="workspace-action-column">
                {checklistDraft.map((item, index) => {
                  const isCustomItem = String(item.id || '').startsWith('custom-')
                  return (
                    <div key={item.id || index} className="task-card">
                      <div className="checklist-toggle-row">
                        <label className="checklist-text-block">
                          <input
                            type="checkbox"
                            checked={item.done}
                            onChange={(event) =>
                              setChecklistDraft((current) =>
                                current.map((entry, entryIndex) =>
                                  entryIndex === index ? { ...entry, done: event.target.checked } : entry
                                )
                              )
                            }
                          />
                          <span className={item.done ? 'checklist-text completed' : 'checklist-text'}>{item.text}</span>
                        </label>
                        {isCustomItem ? (
                          <Button
                            size="sm"
                            variant="secondary"
                            onClick={() =>
                              setChecklistDraft((current) => current.filter((_, entryIndex) => entryIndex !== index))
                            }
                          >
                            Remove
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  )
                })}
              </div>
              <div className="checklist-add-row">
                <Input
                  placeholder="Add a custom checklist item..."
                  value={newChecklistItem}
                  onChange={(event) => setNewChecklistItem(event.target.value)}
                />
                <Button
                  variant="secondary"
                  onClick={() => {
                    const nextText = newChecklistItem.trim()
                    if (!nextText) return
                    setChecklistDraft((current) => [
                      ...current,
                      {
                        id: `custom-${Date.now()}`,
                        text: nextText,
                        done: false,
                      },
                    ])
                    setNewChecklistItem('')
                  }}
                >
                  Add Item
                </Button>
              </div>
              <div className="company-form-actions">
                <Button
                  loading={updateArtifactMutation.isPending}
                  onClick={async () => {
                    await updateArtifactMutation.mutateAsync({
                      artifactId: checklistArtifact.id,
                      body: {
                        content_json: {
                          ...checklistArtifact.content_json,
                          solicitation_status: checklistArtifact.content_json?.solicitation_status || solicitationStatus,
                          checklist: checklistDraft.map((item) => ({ id: item.id, text: item.text, done: item.done })),
                        },
                      },
                    })
                  }}
                >
                  Save Checklist
                </Button>
                <Button
                  variant="secondary"
                  loading={generateChecklistMutation.isPending}
                  onClick={() => generateChecklistMutation.mutate()}
                >
                  Regenerate
                </Button>
              </div>
            </div>
          )}
        </Card>
      ) : null}

      {isSamOpportunity ? (
        <Card title="Compliance Matrix">
          {!complianceMatrixArtifact ? (
            <EmptyState
              title="No compliance matrix yet"
              subtitle="Download the solicitation package and the workspace will organize requirements, review items, and missing information here."
            />
          ) : (
            <div className="workspace-action-column">
              <div className="panel-subtitle">
                Source file: {complianceMatrixArtifact.content_json?.source_file || 'Not captured yet'}
              </div>
              <div className="artifact-list">
                {(complianceMatrixArtifact.content_json?.matrix_rows || []).map((row, index) => (
                  <div key={row.id || `matrix-row-${index}`} className="artifact-list-item">
                    <strong>{row.category || 'Requirement'}:</strong> {row.requirement}
                    {row.due_at ? ` | Due ${formatDateOnly(row.due_at)}` : ''}
                    {row.owner_hint ? ` | ${row.owner_hint}` : ''}
                  </div>
                ))}
                {!(complianceMatrixArtifact.content_json?.matrix_rows || []).length ? (
                  <div className="artifact-list-item">No compliance rows were generated yet.</div>
                ) : null}
              </div>
            </div>
          )}
        </Card>
      ) : null}

      {!isSamOpportunity ? (
        <Card title="Artifact Center">
        <div className="company-form-actions">
          <a className="action-btn-small" href={`${API_BASE_URL}/api/export/bid_package?opportunity_id=${id}`} target="_blank" rel="noreferrer">
            Export Bid Package
          </a>
        </div>
        {artifacts.length === 0 ? (
          <EmptyState title="No artifacts yet" subtitle="Generated outputs will appear here with their timestamps and current content." />
        ) : (
          <div className="workspace-action-column">
            {artifacts.map((artifact) => (
              <div key={artifact.id} className="artifact-history-row">
                <div>
                  <div className="row-title">{artifact.title}</div>
                  <div className="row-subtitle">
                    {artifact.artifact_type} | {artifact.artifact_category || 'GENERAL'} | {artifact.artifact_status || 'ACTIVE'} | {formatDateTime(artifact.created_at)}
                  </div>
                  <div className="row-subtitle">
                    Versions: {artifact.version_count || 0} | Outreach events: {artifact.outreach_count || 0}
                  </div>
                  {(artifact.version_history || []).slice(-2).reverse().map((version, index) => (
                    <div key={`version-${artifact.id}-${index}`} className="row-subtitle">
                      Version saved {formatDateTime(version.timestamp)} ({version.action || 'updated'})
                    </div>
                  ))}
                  {(artifact.outreach_log || []).slice(-2).reverse().map((entry, index) => (
                    <div key={`outreach-${artifact.id}-${index}`} className="row-subtitle">
                      Outreach {entry.action} to {entry.vendor_name || entry.recipient || 'recipient'} at {formatDateTime(entry.timestamp)}
                    </div>
                  ))}
                </div>
                <div className="workspace-action-column">
                  <StatusPill status={artifact.artifact_type} />
                  {(artifact.version_history || []).length > 0 ? (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={restoreArtifactMutation.isPending}
                        onClick={() =>
                          restoreArtifactMutation.mutate({
                            artifactId: artifact.id,
                            versionIndex: artifact.version_history.length - 1,
                          })
                        }
                      >
                        Restore Last Version
                      </Button>
                    </>
                  ) : null}
                  {artifact.artifact_type === 'EMAIL_DRAFT' || artifact.artifact_type === 'OUTREACH_PLAN' ? (
                    <>
                      <a
                        className="action-btn-small"
                        href={`mailto:${artifact.content_json?.target_vendor_email || artifact.content_json?.to || ''}?subject=${encodeURIComponent(artifact.content_json?.subject || '')}&body=${encodeURIComponent(artifact.content_json?.body || '')}`}
                      >
                        Open Mail App
                      </a>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={sendArtifactEmailMutation.isPending}
                        onClick={() => sendArtifactEmailMutation.mutate(artifact.id)}
                      >
                        Send Email
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        loading={outreachLogMutation.isPending}
                        onClick={() =>
                          outreachLogMutation.mutate({
                            artifactId: artifact.id,
                            body: {
                              action: 'sent',
                              recipient: artifact.content_json?.target_vendor_email || artifact.content_json?.to,
                              vendor_name: artifact.content_json?.target_vendor_name || artifact.content_json?.company_name,
                            },
                          })
                        }
                      >
                        Mark Sent
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
      ) : null}
    </div>
  )

  const agentsContent = (
    <div className="workspace-scoring-panel">
      <Card title="Bid Team Workflow">
        <div className="workspace-action-column">
          <div className="panel-subtitle">
            The workspace team runs in sequence so the solicitation gets read first, then vendor outreach is prepared, then the execution plan is tightened for submission.
          </div>
          {lastAgentPhaseResult ? (
            <div className="workspace-mode-banner">
              <div className="row-title">{AGENT_PHASE_LABELS[lastAgentPhaseResult.phase] || lastAgentPhaseResult.phase} completed</div>
              <div className="panel-subtitle">
                {(lastAgentPhaseResult.results || []).filter((item) => item.status === 'success').length} successful run(s),
                {' '}
                {(lastAgentPhaseResult.results || []).filter((item) => item.status === 'failed').length} failed run(s).
              </div>
              <div className="panel-subtitle">
                {(lastAgentPhaseResult.results || []).every((item) => item.persisted_run === false)
                  ? 'Agent outputs were returned even though run-history persistence is not available yet in this database.'
                  : 'Agent run history is available for this phase.'}
              </div>
              {(lastAgentPhaseResult.results || []).some((item) => item.fallback_reason) ? (
                <div className="panel-subtitle">
                  {formatAgentFallback((lastAgentPhaseResult.results || []).find((item) => item.fallback_reason))}
                </div>
              ) : null}
            </div>
          ) : null}
          {agentPhaseError ? (
            <div className="workspace-mode-banner">
              <div className="row-title">Phase run failed</div>
              <div className="panel-subtitle">{agentPhaseError}</div>
            </div>
          ) : null}
          <div className="workspace-summary-grid">
            {Object.entries(agentPhases).map(([phase, agents]) => (
              <Card key={phase} title={AGENT_PHASE_LABELS[phase] || phase}>
                <div className="workspace-action-column">
                  <div className="row-subtitle">
                    {(agents || []).map((agentKey) => getAgentMeta(agentKey, agentCatalog).label).join(', ')}
                  </div>
                  <Button
                    loading={runAgentPhaseMutation.isPending && runAgentPhaseMutation.variables === phase}
                    onClick={() => runAgentPhaseMutation.mutate(phase)}
                  >
                    Run {AGENT_PHASE_LABELS[phase] || phase}
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Team Roles">
        <div className="workspace-action-column">
          <div className="panel-subtitle">
            Start with the Solicitation Analyst when you want the system to read the notice or package and tell you what it means.
          </div>
          {lastAgentRunResult ? (
            <div className="workspace-mode-banner">
              <div className="row-title">{getAgentMeta(lastAgentRunResult.agent_key, agentCatalog).label} completed</div>
              <div className="panel-subtitle">
                Model: {lastAgentRunResult.model_name || 'workspace_phased_agent'}
              </div>
              <div className="panel-subtitle">
                {lastAgentRunResult.persisted_run === false
                  ? 'Output was generated, but this database has not persisted agent run history yet.'
                  : 'Run history was saved and is listed below.'}
              </div>
              {lastAgentRunResult.fallback_reason ? (
                <div className="panel-subtitle">
                  {formatAgentFallback(lastAgentRunResult)}
                </div>
              ) : null}
            </div>
          ) : null}
          {agentRunError ? (
            <div className="workspace-mode-banner">
              <div className="row-title">Agent run failed</div>
              <div className="panel-subtitle">{agentRunError}</div>
            </div>
          ) : null}
          {Object.keys(agentCatalog).length ? Object.entries(agentCatalog).map(([agentKey, meta]) => (
            <div key={agentKey} className="artifact-history-row">
              <div>
                <div className="row-title">{meta.label || agentKey.replace(/_/g, ' ')}</div>
                <div className="row-subtitle">{meta.description || ''}</div>
              </div>
              <Button
                size="sm"
                loading={runAgentMutation.isPending && runAgentMutation.variables === agentKey}
                onClick={() => runAgentMutation.mutate(agentKey)}
              >
                Run Role
              </Button>
            </div>
          )) : Object.entries(AGENT_CATALOG_FALLBACK).map(([agentKey, meta]) => (
            <div key={agentKey} className="artifact-history-row">
              <div>
                <div className="row-title">{meta.label}</div>
                <div className="row-subtitle">{meta.description}</div>
              </div>
              <Button
                size="sm"
                loading={runAgentMutation.isPending && runAgentMutation.variables === agentKey}
                onClick={() => runAgentMutation.mutate(agentKey)}
              >
                Run Role
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Current Agent Findings">
        <div className="workspace-summary-grid">
          <Card title="Solicitation Analyst">
            <div className="workspace-action-column">
              <div className="panel-subtitle">
                {stripRecommendationPrefix(solicitationAnalystFinding.summary || '') || 'No analyst summary yet.'}
              </div>
              <StructuredList
                title="History Signals"
                items={solicitationHistorySignals.length ? solicitationHistorySignals : [...solicitationOutcomePatterns.slice(0, 2), ...solicitationResponsePatterns.slice(0, 2)]}
                emptyMessage="No local pattern signals yet."
              />
            </div>
          </Card>

          <Card title="Compliance Reviewer">
            <div className="workspace-action-column">
              <div className="panel-subtitle">
                {complianceMatrixLines.length
                  ? 'Structured requirements and review items are ready from the current document set.'
                  : 'No structured requirement matrix has been generated yet.'}
              </div>
              <StructuredList
                title="Requirement Matrix"
                items={complianceMatrixLines}
                emptyMessage="Run the Compliance Reviewer to build the requirement matrix."
              />
            </div>
          </Card>

          <Card title="Market Researcher">
            <div className="workspace-action-column">
              <StructuredList
                title="Market Findings"
                items={marketFindingLines}
                emptyMessage="No market findings are available yet."
              />
              <StructuredList
                title="Suggested Targets"
                items={marketTargetLines}
                emptyMessage="No suggested targets have been surfaced yet."
              />
            </div>
          </Card>

          <Card title="Capability Matcher">
            <div className="workspace-action-column">
              <div className="panel-subtitle">
                {capabilityMatcherFinding.summary || 'Capability fit has not been reviewed yet.'}
              </div>
              <StructuredList
                title="Capability Signals"
                items={capabilitySignalLines}
                emptyMessage="No capability signals are available yet."
              />
            </div>
          </Card>

          <Card title="Outreach Coordinator">
            <div className="workspace-action-column">
              <StructuredList
                title="Outreach Notes"
                items={outreachFindingLines}
                emptyMessage="No outreach plan has been generated yet."
              />
            </div>
          </Card>

          <Card title="Proposal Coordinator">
            <div className="workspace-action-column">
              <StructuredList
                title="Execution Notes"
                items={proposalFindingLines}
                emptyMessage="No execution plan has been generated yet."
              />
            </div>
          </Card>
        </div>
      </Card>

    </div>
  )

  const submissionContent = (
    <div className="workspace-scoring-panel">
      <Card title="Submission Workflow">
        <div className="workspace-action-column">
          <div className="company-form-grid">
            <Input
              label="Planned Vendor"
              value={submissionForm.planned_vendor_name || submissionForm.planned_vendor_cage || ''}
              disabled
            />
            <div className="input-wrapper">
              <label className="input-label">Submission Status</label>
              <select
                disabled={isClosedSolicitation}
                value={submissionForm.status}
                onChange={(event) => setSubmissionForm((current) => ({ ...current, status: event.target.value }))}
              >
                {SUBMISSION_STATUSES.map((status) => (
                  <option key={status} value={status}>{status.replace('_', ' ')}</option>
                ))}
              </select>
            </div>
            <Input
              label="Submitted At"
              type="datetime-local"
              value={submissionForm.submitted_at}
              disabled={isClosedSolicitation}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, submitted_at: event.target.value }))}
            />
            <Input
              label="Submitted Unit Price"
              type="number"
              value={submissionForm.submitted_unit_price}
              disabled={isClosedSolicitation}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, submitted_unit_price: event.target.value }))}
            />
            <Input
              label="Vendor CAGE"
              value={submissionForm.submitted_vendor_cage}
              disabled={isClosedSolicitation}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, submitted_vendor_cage: event.target.value }))}
            />
            <Input
              label="Vendor Name"
              value={submissionForm.submitted_vendor_name}
              disabled={isClosedSolicitation}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, submitted_vendor_name: event.target.value }))}
            />
          </div>
          <div className="company-form-stack">
            <label className="textarea-label">Submission Notes</label>
            <textarea
              className="textarea-field"
              value={submissionForm.notes}
              disabled={isClosedSolicitation}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, notes: event.target.value }))}
            />
          </div>
          <div className="company-form-actions">
            <Button
              loading={saveSubmissionMutation.isPending}
              disabled={isClosedSolicitation}
              onClick={() =>
                saveSubmissionMutation.mutate({
                  opportunity_id: Number(id),
                  status: submissionForm.status,
                  submitted_at: submissionForm.submitted_at || null,
                  submitted_unit_price: submissionForm.submitted_unit_price === '' ? null : Number(submissionForm.submitted_unit_price),
                  submitted_vendor_cage: submissionForm.submitted_vendor_cage || null,
                  submitted_vendor_name: submissionForm.submitted_vendor_name || null,
                  planned_vendor_quote_id: submissionForm.planned_vendor_quote_id || null,
                  planned_vendor_cage: submissionForm.planned_vendor_cage || null,
                  planned_vendor_name: submissionForm.planned_vendor_name || null,
                  awarded_at: submissionForm.awarded_at || null,
                  award_amount: submissionForm.award_amount === '' ? null : Number(submissionForm.award_amount),
                  winning_vendor_cage: submissionForm.winning_vendor_cage || null,
                  winning_vendor_name: submissionForm.winning_vendor_name || null,
                  outcome_summary: submissionForm.outcome_summary || null,
                  notes: submissionForm.notes || null,
                })
              }
            >
                Save Submission
              </Button>
              <div className="panel-subtitle">
                {isClosedSolicitation
                  ? 'Submission updates are disabled because the solicitation is closed.'
                  : `Current status: ${humanizeLabel(submission?.status, 'Draft')}${submission?.planned_vendor_name || submission?.planned_vendor_cage ? ` | Planned vendor: ${submission?.planned_vendor_name || submission?.planned_vendor_cage}` : ''}`}
              </div>
            </div>
          </div>
        </Card>

      <Card title="Outcome Tracking">
        <div className="workspace-action-column">
          <div className="company-form-grid">
            <Input
              label="Awarded At"
              type="datetime-local"
              value={submissionForm.awarded_at}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, awarded_at: event.target.value }))}
            />
            <Input
              label="Award Amount"
              type="number"
              value={submissionForm.award_amount}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, award_amount: event.target.value }))}
            />
            <Input
              label="Winning Vendor CAGE"
              value={submissionForm.winning_vendor_cage}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, winning_vendor_cage: event.target.value }))}
            />
            <Input
              label="Winning Vendor Name"
              value={submissionForm.winning_vendor_name}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, winning_vendor_name: event.target.value }))}
            />
          </div>
          <div className="company-form-stack">
            <label className="textarea-label">Outcome Summary</label>
            <textarea
              className="textarea-field"
              value={submissionForm.outcome_summary}
              onChange={(event) => setSubmissionForm((current) => ({ ...current, outcome_summary: event.target.value }))}
            />
          </div>
          <div className="panel-subtitle">
            Track the final outcome here after submission so vendor and opportunity history stay useful over time.
          </div>
        </div>
      </Card>
    </div>
  )

  const submissionPackageContent = (
    <div className="workspace-scoring-panel">
      <Card title="Submission Package">
        <div className="workspace-action-column">
          <div className="results-toolbar">
            <div>
              <div className="row-title">Execution-ready package view</div>
              <div className="panel-subtitle">
                Review planned vendor, compliance facts, quote comparison, and submission blockers in one place before sending.
              </div>
            </div>
            <div className="company-form-actions">
              <Button variant="secondary" onClick={exportQuoteComparisonCsv}>
                Export Quote Comparison
              </Button>
              <Button
                variant="secondary"
                loading={generateSubmissionPackageMutation.isPending}
                onClick={() => generateSubmissionPackageMutation.mutate()}
              >
                Save Package Artifact
              </Button>
              <Button onClick={printSubmissionPackage}>
                Print Submission Package
              </Button>
            </div>
          </div>

          <div className="submission-package-hero">
            <div className="submission-package-panel submission-package-panel-accent">
              <div className="row-title">Planned Vendor</div>
              <div className="submission-package-emphasis">
                {submissionForm.planned_vendor_name || submissionForm.planned_vendor_cage || 'Not selected yet'}
              </div>
              <div className="panel-subtitle">
                {packageVendor?.unit_price ? `Unit price ${formatCurrency(packageVendor.unit_price)}` : 'No price selected yet'}
                {packageVendor?.lead_time_days ? ` | Lead time ${packageVendor.lead_time_days} days` : ''}
              </div>
            </div>
            <div className="submission-package-panel">
              <div className="row-title">Submission Status</div>
              <div className="submission-package-emphasis">{submissionForm.status || 'DRAFT'}</div>
              <div className="panel-subtitle">
                Due {formatDateOnly(factReturnBy)} | {files.length} document{files.length === 1 ? '' : 's'}
              </div>
            </div>
            <div className="submission-package-panel">
              <div className="row-title">Recommended Candidate</div>
              <div className="submission-package-emphasis">
                {recommendedQuote?.company_name || recommendedQuote?.cage || 'No recommendation yet'}
              </div>
              <div className="panel-subtitle">
                {recommendedQuote?.unit_price ? `Unit price ${formatCurrency(recommendedQuote.unit_price)}` : 'Awaiting quote comparison data'}
                {recommendedQuote?.lead_time_days ? ` | Lead time ${recommendedQuote.lead_time_days} days` : ''}
              </div>
            </div>
          </div>

          <div className="submission-package-grid">
            <Card title="Submission Snapshot">
              <BriefDetailsBox
                title="Submission Details"
                items={packageSubmissionFacts.map((item) => formatDetailLine(item.label, item.value || '-'))}
              />
            </Card>

            <Card title="Execution Readiness">
              <div className="submission-package-columns">
                <div>
                  <div className="row-title">Strengths</div>
                  <div className="artifact-list">
                    {(readinessStrengths.length ? readinessStrengths : ['No strengths captured yet.']).map((item, index) => (
                      <div key={`strength-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                </div>
                <div>
                  <div className="row-title">Blockers</div>
                  <div className="artifact-list">
                    {(readinessBlockers.length ? readinessBlockers : ['No blockers currently flagged.']).map((item, index) => (
                      <div key={`blocker-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>
          </div>

          <Card title="Summary">
            <div className="artifact-list">
              {(packageHighlights.length ? packageHighlights : ['No executive summary generated yet.']).map((item, index) => (
                <div key={`highlight-${index}`} className="artifact-list-item">{item}</div>
              ))}
            </div>
            <div className="panel-subtitle">
              Saved package: {submissionPackageArtifact ? `${submissionPackageArtifact.title} | ${formatDateTime(submissionPackageArtifact.created_at)}` : 'Not saved yet'}
            </div>
          </Card>

          <Card title="Quote Comparison">
            {quoteComparison.length === 0 ? (
              <EmptyState
                title="No quote comparison available"
                subtitle="Seed the quote tracker and log vendor responses to assemble the final submission package."
              />
            ) : (
              <div className="workspace-action-column">
                {quoteComparison.map((quote) => (
                  <div key={`package-quote-${quote.id}`} className="artifact-note-box">
                    <div className="row-title">{quote.company_name || quote.cage || `Quote ${quote.id}`}</div>
                    <div className="row-subtitle">
                      {compactMeta([
                        String(submissionForm.planned_vendor_quote_id || '') === String(quote.id)
                          ? 'Planned Vendor'
                          : recommendedQuote?.id === quote.id
                            ? 'Recommended Candidate'
                            : '',
                        quote.normalized_status || '',
                      ]) || 'Quote comparison entry'}
                    </div>
                    <div className="artifact-brief-lines">
                      {[ 
                        formatDetailLine('CAGE', quote.cage || '-'),
                        formatDetailLine('Unit Price', formatCurrency(quote.unit_price)),
                        formatDetailLine('Lead Time', quote.lead_time_days ? `${quote.lead_time_days} days` : '-'),
                        formatDetailLine('Email', quote.email || '-'),
                      ].filter(Boolean).map((line, index) => (
                        <div key={`package-quote-line-${quote.id}-${index}`} className="artifact-brief-line">{line}</div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card title="Historical Pricing">
            {(packagePriceHistory.count || nsnPricing.price_fact_count) ? (
              <div className="workspace-action-column">
                <BriefDetailsBox
                  title="Price Range"
                  items={[
                    formatDetailLine('Average Unit Price', formatCurrency(packagePriceHistory.average_unit_price ?? nsnPricing.unit_price_average)),
                    formatDetailLine('Low Unit Price', formatCurrency(packagePriceHistory.low_unit_price ?? nsnPricing.unit_price_low)),
                    formatDetailLine('High Unit Price', formatCurrency(packagePriceHistory.high_unit_price ?? nsnPricing.unit_price_high)),
                    formatDetailLine('Average Award Amount', formatCurrency(packagePriceHistory.average_total_award_amount)),
                    formatDetailLine('Award Amount Range', packagePriceHistory.low_total_award_amount || packagePriceHistory.high_total_award_amount ? `${formatCurrency(packagePriceHistory.low_total_award_amount)} - ${formatCurrency(packagePriceHistory.high_total_award_amount)}` : ''),
                    formatDetailLine('Last Supplier', packagePriceHistory.last_award?.supplier_name || packagePriceHistory.last_award?.cage || '-'),
                    formatDetailLine('Last Award Date', packagePriceHistory.last_award?.award_date || '-'),
                  ]}
                />
                {(packagePriceHistory.items || []).slice(0, 3).map((item, index) => (
                  <div key={`price-history-${item.id || index}`} className="artifact-note-box">
                    <div className="row-title">{item.supplier_name || item.cage || 'Historical price point'}</div>
                    <div className="artifact-brief-lines">
                      {[
                        formatDetailLine('Unit Price', formatCurrency(item.unit_price)),
                        formatDetailLine('Quantity', item.quantity || '-'),
                        formatDetailLine('CAGE', item.cage || '-'),
                        formatDetailLine('Source', item.source_label || '-'),
                      ].filter(Boolean).map((line, lineIndex) => (
                        <div key={`price-history-line-${index}-${lineIndex}`} className="artifact-brief-line">{line}</div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState title="No historical pricing extracted yet" subtitle="Run Prepare Workspace after downloading the solicitation PDF to extract previous award pricing when the document includes it." />
            )}
          </Card>

        </div>
      </Card>
    </div>
  )

  const advancedContent = (
    <div className="workspace-scoring-panel">
      <Card title="Task Manager">
        <div className="workspace-action-column">
          <div className="company-form-grid">
            <Input
              label="Task Type"
              value={newTaskForm.task_type}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, task_type: event.target.value }))}
            />
            <Input
              label="Due Date"
              type="datetime-local"
              value={newTaskForm.due_at}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, due_at: event.target.value }))}
            />
          </div>
          <div className="company-form-stack">
            <label className="textarea-label">Task Notes</label>
            <textarea
              className="textarea-field"
              value={newTaskForm.notes}
              onChange={(event) => setNewTaskForm((current) => ({ ...current, notes: event.target.value }))}
              placeholder="Add the next action, dependency, or owner note."
            />
          </div>
          <div className="company-form-actions">
            <Button
              loading={createTaskMutation.isPending}
              disabled={isClosedSolicitation}
              onClick={() =>
                createTaskMutation.mutate({
                  opportunity_id: Number(id),
                  task_type: newTaskForm.task_type,
                  due_at: newTaskForm.due_at || null,
                  notes: newTaskForm.notes || null,
                })
              }
            >
              Add Task
            </Button>
          </div>
          {tasks.length === 0 ? (
            <EmptyState title="No tasks yet" subtitle="Use this area only when you need deeper task editing." />
          ) : (
            <div className="workspace-action-column">
              {tasks.map((task) => (
                <div key={task.id} className="task-card">
                  <div className="task-card-row">
                    <div className="row-title">{task.task_type}</div>
                    <select
                      disabled={isClosedSolicitation}
                      value={task.status}
                      onChange={(event) =>
                        updateTaskMutation.mutate({
                          taskId: task.id,
                          body: { status: event.target.value },
                        })
                      }
                    >
                      {TASK_STATUSES.map((status) => (
                        <option key={status} value={status}>{status.replace('_', ' ')}</option>
                      ))}
                    </select>
                  </div>
                  <div className="row-subtitle">Due: {formatDateTime(task.due_at)}</div>
                  <textarea
                    className="textarea-field textarea-compact"
                    defaultValue={task.notes || ''}
                    disabled={isClosedSolicitation}
                    onBlur={(event) =>
                      updateTaskMutation.mutate({
                        taskId: task.id,
                        body: { notes: event.target.value },
                      })
                    }
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </Card>

      {agentsContent}

      <Card title="Recent Activity">
        {recentActivity.length === 0 ? (
          <EmptyState title="No activity yet" subtitle="Parse, download, and pipeline updates will start showing here." />
        ) : (
          <div className="workspace-action-column">
            {recentActivity.map((item, index) => (
              <div key={`${item.type}-${item.timestamp || index}`} className="activity-row">
                <div className="activity-row-main">
                  <StatusPill status={item.type} />
                  <div>
                    <div className="row-title">{item.title}</div>
                    <div className="row-subtitle">{item.detail || '-'}</div>
                  </div>
                </div>
                <div className="panel-subtitle">{formatDateTime(item.timestamp)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

    </div>
  )

  const tabs = isDibbsOpportunity
    ? [
        { label: 'Overview', content: overviewContent },
        { label: 'Sources & Quotes', content: vendorsContent },
        { label: 'RFQ Package', content: documentsContent },
        { label: 'Submission Package', content: submissionPackageContent },
        { label: 'Submission', content: submissionContent },
      ]
    : [
        { label: 'Overview', content: overviewContent },
        {
          label: 'Planning',
          content: (
            <div className="workspace-action-column">
              {scoringContent}
            </div>
          ),
        },
        {
          label: 'Compliance',
          content: (
            <div className="workspace-action-column">
              {artifactsContent}
              {documentsContent}
            </div>
          ),
        },
        { label: 'Market Intelligence', content: samMarketIntelligenceContent },
        {
          label: 'Submission',
          content: (
            <div className="workspace-action-column">
              {submissionPackageContent}
              {submissionContent}
            </div>
          ),
        },
      ]

  return (
    <div className="page workspace-page">
      <Tabs
        tabs={tabs}
        activeTab={activeTab}
        onChange={setActiveTab}
        className="workspace-tabs"
      />
    </div>
  )
}
