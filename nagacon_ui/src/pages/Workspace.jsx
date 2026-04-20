import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, API_BASE_URL } from '../api/client'
import { EmptyState, Tabs, Badge, Card, Button, Input, LoadingState, StatusPill, Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '../components/ui'
import { setAsideBadgeLabel, setAsideBadgeVariant } from '../utils/badges'

const DECISION_OPTIONS = ['NEW', 'IN_PROGRESS', 'BID', 'NO_BID', 'SUBMITTED']
const TASK_STATUSES = ['OPEN', 'IN_PROGRESS', 'DONE']
const SUBMISSION_STATUSES = ['DRAFT', 'SUBMITTED', 'AWARDED', 'LOST', 'NO_BID']
const AGENT_PHASE_LABELS = {
  phase_1: 'Phase 1',
  phase_2: 'Phase 2',
  phase_3: 'Phase 3',
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
const AGENT_DESCRIPTIONS = {
  opportunity_analyst: 'Analyze the opportunity and summarize risks, signals, and next actions.',
  compliance_document: 'Review parsed documents and expose compliance-oriented document insights.',
  vendor_research: 'Rank vendors and USAspending evidence using the research profile.',
  email_outreach: 'Create an outreach plan from the strongest vendor leads.',
  proposal_workspace: 'Turn current tasks and artifacts into an execution plan.',
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
  const [selectedArtifactCompare, setSelectedArtifactCompare] = useState(null)
  const [selectedFileId, setSelectedFileId] = useState(null)
  const [activeIntakeJobId, setActiveIntakeJobId] = useState(null)

  const workspaceQuery = useQuery({
    queryKey: ['workspace', id],
    queryFn: async () => {
      const res = await api.get(`/api/workspace/summary?opp_id=${id}`)
      return res.data
    },
    enabled: !!id,
    retry: 1,
  })

  const pipelineQuery = useQuery({
    queryKey: ['pipeline-by-opp', id],
    queryFn: async () => {
      const res = await api.get(`/api/pipeline/by-opportunity/${id}`)
      return res.data
    },
    enabled: !!id,
    retry: false,
  })

  const filesQuery = useQuery({
    queryKey: ['workspace-files', id],
    queryFn: async () => {
      const res = await api.get('/api/files/list', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id,
    retry: false,
  })
  const fileInsightsQuery = useQuery({
    queryKey: ['workspace-file-insights', selectedFileId],
    queryFn: async () => {
      const res = await api.get(`/api/files/${selectedFileId}/insights`)
      return res.data
    },
    enabled: !!selectedFileId,
    retry: false,
  })
  const vendorLeadsQuery = useQuery({
    queryKey: ['vendor-leads', id],
    queryFn: async () => {
      const res = await api.get('/api/vendors/leads', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id,
    retry: false,
  })
  const vendorQuotesQuery = useQuery({
    queryKey: ['vendor-quotes', id],
    queryFn: async () => {
      const res = await api.get('/api/vendors/quotes', { params: { opportunity_id: id } })
      return res.data
    },
    enabled: !!id,
    retry: false,
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
    enabled: !!id,
    retry: false,
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
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${activeIntakeJobId}`)
      return res.data
    },
  })
  const activeIntakeJob = intakeJobQuery.data
  const isIntakeRunning = activeIntakeJob && !['success', 'failed'].includes(activeIntakeJob.status)

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
    },
  })
  const generateEmailMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/workspace/generate/email', { opportunity_id: Number(id) })
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
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
    },
  })
  const outreachLogMutation = useMutation({
    mutationFn: async ({ artifactId, body }) => {
      const res = await api.post(`/api/workspace/artifacts/${artifactId}/outreach-log`, body)
      return res.data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', id] })
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
    },
  })

  const data = workspaceQuery.data
  const opp = data?.opportunity || {}
  const files = filesQuery.data || []
  const parsedSummary = data?.parsed_summary || {}
  const normalizedFacts = data?.normalized_facts || {}
  const normalizedPoc = normalizedFacts.poc || {}
  const pipeline = pipelineQuery.data || data?.pipeline_item || null
  const artifacts = data?.artifacts || []
  const tasks = data?.tasks || []
  const submission = data?.submission || null
  const vendorLeads = vendorLeadsQuery.data || []
  const vendorQuotes = vendorQuotesQuery.data || []
  const usaspendingVendors = usaspendingResearchQuery.data?.likely_vendors || []
  const usaspendingDebug = usaspendingResearchQuery.data?.query_debug || []
  const usaspendingHistoryMatchLabel = usaspendingResearchQuery.data?.history_match_label || ''
  const usaspendingHistoryMatchQueryLabel = usaspendingResearchQuery.data?.history_match_query_label || ''
  const usaspendingHistoryMatchSource = usaspendingResearchQuery.data?.history_match_source || 'none'
  const researchProfile = usaspendingResearchQuery.data?.research_profile || data?.research_profile || {}
  const checklistArtifact = artifacts.find((artifact) => artifact.artifact_type === 'CHECKLIST') || null
  const emailArtifact =
    artifacts.find((artifact) => artifact.artifact_type === 'EMAIL_DRAFT')
    || artifacts.find((artifact) => artifact.artifact_type === 'OUTREACH_PLAN')
    || null
  const vendorListArtifact = artifacts.find((artifact) => artifact.artifact_type === 'VENDOR_LIST') || null
  const researchBriefArtifact = artifacts.find((artifact) => artifact.artifact_type === 'RESEARCH_BRIEF') || null
  const opportunityAnalysisArtifact = artifacts.find((artifact) => artifact.artifact_type === 'OPPORTUNITY_ANALYSIS') || null
  const complianceArtifact = artifacts.find((artifact) => artifact.artifact_type === 'COMPLIANCE_BRIEF') || null
  const vendorResearchArtifact = artifacts.find((artifact) => artifact.artifact_type === 'VENDOR_RESEARCH') || null
  const submissionPackageArtifact = artifacts.find((artifact) => artifact.artifact_type === 'SUBMISSION_PACKAGE') || null
  const partFinderArtifact = artifacts.find((artifact) => artifact.artifact_type === 'PART_FINDER') || null
  const partFinder = partFinderArtifact?.content_json?.part_finder || {}
  const partFinderPart = partFinder.part || {}
  const partFinderProviders = partFinder.providers || []
  const partFinderAwardees = partFinder.awardees || []
  const partFinderNextActions = partFinder.next_actions || []
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
  const analysisAssessment =
    opportunityAnalysisArtifact?.content_json?.executive_assessment
    || null
  const analysisBidPosture =
    opportunityAnalysisArtifact?.content_json?.bid_posture
    || null
  const analysisReasons = formatBriefList(opportunityAnalysisArtifact?.content_json?.reasons || [])
  const analysisStrengths = formatBriefList(opportunityAnalysisArtifact?.content_json?.strengths || [])
  const analysisBlockers = formatBriefList(opportunityAnalysisArtifact?.content_json?.blockers || [])
  const analysisNextActions = formatBriefList(opportunityAnalysisArtifact?.content_json?.recommended_next_actions || [])
  const complianceFacts = complianceArtifact?.content_json?.extracted_facts || []
  const complianceMissingInfo = complianceArtifact?.content_json?.missing_information || []
  const complianceReviewFlags = complianceArtifact?.content_json?.review_flags || []
  const complianceVendorAsks = complianceArtifact?.content_json?.vendor_request_items || []
  const emailVendorAsks = emailArtifact?.content_json?.vendor_request_items || complianceVendorAsks
  const complianceFields = complianceArtifact?.content_json?.compliance_fields || {}
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
  const recommendedQuote = quoteComparison.find((quote) => quote.normalized_status === 'RECEIVED' && quote.hasPrice) || quoteComparison[0] || null
  const selectedQuote = quoteComparison.find((quote) => String(quote.id) === String(submissionForm.planned_vendor_quote_id || '')) || null
  const packageVendor = selectedQuote || recommendedQuote || null
  const packageDocuments = [...files]
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
    submission?.status && submission.status !== 'DRAFT' ? `Submission status is ${submission.status}.` : null,
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
    if (!filesQuery.data || filesQuery.data.length === 0) {
      if (selectedFileId !== null) {
        setSelectedFileId(null)
      }
      return
    }
    const hasSelectedFile = filesQuery.data.some((file) => file.id === selectedFileId)
    if (!hasSelectedFile) {
      setSelectedFileId(filesQuery.data[0].id)
    }
  }, [filesQuery.data, selectedFileId])

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
  const vendors = data.vendor_matches || []
  const recentActivity = data.recent_activity || []
  const agentRuns = data.agent_runs || []
  const agentPhases = data.agent_phases || {}
  const lastAgentRunResult = runAgentMutation.data || null
  const lastAgentPhaseResult = runAgentPhaseMutation.data || null
  const agentRunError = runAgentMutation.error?.response?.data?.detail || runAgentMutation.error?.message || ''
  const agentPhaseError = runAgentPhaseMutation.error?.response?.data?.detail || runAgentPhaseMutation.error?.message || ''
  const selectedFile = files.find((file) => file.id === selectedFileId) || null
  const fileInsights = fileInsightsQuery.data || null
  const solicitationStatus = opp.solicitation_status || 'OPEN'
  const isClosedSolicitation = solicitationStatus === 'CLOSED'
  const documentFields = opp.document_fields || {}
  const documentSummary = opp.document_summary || {}
  const summaryOverviewText =
    formatBriefText(opp.summary || documentSummary.summary_text || '', { punctuate: false })
    || 'No contract overview is available yet.'
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
  const checklistCompletedCount = checklistDraft.filter((item) => item.done).length
  const checklistTotalCount = checklistDraft.length
  const checklistProgress = checklistTotalCount > 0 ? Math.round((checklistCompletedCount / checklistTotalCount) * 100) : 0

  const readinessChecks = [
    { label: 'Opportunity parsed', done: Boolean(factNsn || factNomenclature || parsedSummary.approved_source_count) },
    { label: 'Vendor research started', done: vendors.length > 0 || (parsedSummary.approved_source_count || 0) > 0 },
    { label: 'Documents downloaded', done: files.length > 0 },
    { label: 'Email draft generated', done: Boolean(emailArtifact) },
    { label: 'Quote tracker seeded', done: vendorQuotes.length > 0 },
    { label: 'Received quote logged', done: quoteComparison.some((quote) => quote.normalized_status === 'RECEIVED') },
    { label: 'Bid decision recorded', done: Boolean(pipeline?.decision_status && pipeline.decision_status !== 'NEW') },
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
        <Card title="Opportunity Summary">
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
          </div>
        ) : null}

        {isClosedSolicitation ? (
          <div className="workspace-mode-banner">
            <div className="row-title">Closed solicitation - research only</div>
            <div className="panel-subtitle">
              {data.ui_hints?.closed_message || 'This workspace remains available for research, artifacts, and vendor intelligence.'}
            </div>
          </div>
        ) : null}

          <div className="summary-brief-layout">
            <div className="artifact-note-box summary-overview-box">
              <div className="row-title">Contract Overview</div>
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

          <div className="summary-decision-row">
            <div className="row-title">Bid Decision</div>
            <div className="decision-chip-row">
              {DECISION_OPTIONS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={`set-aside-chip ${(pipeline?.decision_status || analysis.decision_status || 'NEW') === option ? 'selected' : ''}`}
                  disabled={isClosedSolicitation}
                  onClick={() => updateDecisionStatus(option)}
                >
                  {option.replace('_', ' ')}
                </button>
              ))}
            </div>
            <div className="panel-subtitle">
              {isClosedSolicitation
                ? 'Decision changes are disabled because this solicitation is closed.'
                : 'Use this to track Bid / Not Bid status and pipeline progress.'}
            </div>
          </div>
      </Card>

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
                    <div className="row-title">Awardee Evidence</div>
                    <div className="artifact-list">
                      {(partFinderAwardees.length ? partFinderAwardees.slice(0, 5) : []).map((awardee, index) => (
                        <div key={`part-awardee-${awardee.cage || awardee.name || index}`} className="artifact-list-item">
                          {awardee.name || awardee.cage || 'Awardee'}
                          {awardee.cage ? ` | CAGE ${awardee.cage}` : ''}
                          {awardee.award_count ? ` | ${awardee.award_count} award${awardee.award_count === 1 ? '' : 's'}` : ''}
                          {awardee.total_award_amount ? ` | ${formatCurrency(awardee.total_award_amount)}` : ''}
                        </div>
                      ))}
                      {!partFinderAwardees.length ? <div className="artifact-list-item">No awardee evidence found yet.</div> : null}
                    </div>
                  </div>
                </div>

                <StructuredList
                  title="Next Sourcing Actions"
                  items={partFinderNextActions}
                  emptyMessage="Refresh Part Finder to generate sourcing actions."
                />
              </div>
            </Card>

            <Card title="Bid Readiness">
              <div className="workspace-action-column">
                <div className="artifact-note-box">
                  <div className="row-title">Readiness Snapshot</div>
                  <div className="structured-copy">
                    {`${readinessReadyCount} of ${readinessChecks.length} readiness signals are in place. ${readinessPendingCount} item${readinessPendingCount === 1 ? '' : 's'} still need attention.`}
                  </div>
                  <div className="panel-subtitle">
                    Submission state: {submission?.status || 'DRAFT'}
                  </div>
                </div>

                <div className="bid-readiness-vendors">
                  <BriefDetailsBox
                    title="Vendor Readiness"
                    items={[
                      formatDetailLine(
                        'Recommended Vendor',
                        recommendedQuote
                          ? `${recommendedQuote.company_name || recommendedQuote.cage || 'Vendor'}${recommendedQuote.unit_price ? ` | ${formatCurrency(recommendedQuote.unit_price)}` : ''}${recommendedQuote.lead_time_days ? ` | ${recommendedQuote.lead_time_days}d` : ''}`
                          : 'No vendor recommendation yet'
                      ),
                      formatDetailLine(
                        'Planned Submission Vendor',
                        submissionForm.planned_vendor_name || submissionForm.planned_vendor_cage
                          ? `${submissionForm.planned_vendor_name || 'Vendor'}${submissionForm.planned_vendor_cage ? ` | ${submissionForm.planned_vendor_cage}` : ''}${submissionForm.submitted_unit_price ? ` | ${formatCurrency(submissionForm.submitted_unit_price)}` : ''}`
                          : 'Not selected yet'
                      ),
                    ]}
                  />
                </div>

                <div className="bid-readiness-grid">
                  <div>
                    <div className="row-title">What Is Ready</div>
                    <div className="artifact-list">
                      {(readinessStrengths.length ? readinessStrengths : ['No readiness strengths captured yet.']).map((item, index) => (
                        <div key={`readiness-strength-${index}`} className="artifact-list-item">{item}</div>
                      ))}
                    </div>
                  </div>
                  <div>
                    <div className="row-title">What Still Needs Work</div>
                    <div className="artifact-list">
                      {(readinessBlockers.length ? readinessBlockers : ['No blockers are currently flagged.']).map((item, index) => (
                        <div key={`readiness-blocker-${index}`} className="artifact-list-item">{item}</div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </Card>

            <Card title="AI Briefing">
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
                  <div className="row-title">What This Contract Is About</div>
                  <div className="structured-copy">{analysisAssessment || contractAboutText}</div>
                </div>
                <BriefDetailsBox
                  title="Key Details"
                  items={briefingFacts}
                  emptyMessage="Core solicitation details will appear after documents are processed."
                />
                <StructuredList
                  title="What Matters"
                  items={analysisReasons}
                  emptyMessage="Run the analyst to capture important bid signals."
                />
                <StructuredList
                  title="Needs Attention"
                  items={analysisBlockers}
                  emptyMessage="No blockers are currently flagged."
                />
                <StructuredList
                  title="Next Best Actions"
                  items={analysisNextActions}
                  emptyMessage="No next actions are currently suggested."
                />
              </div>
            </Card>
          </div>
    </div>
  )

  const vendorsContent = (
    <div className="workspace-vendors">
      <Card title="Vendor Leads">
          <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button loading={generateVendorsMutation.isPending} onClick={() => generateVendorsMutation.mutate()}>
              Generate Vendor Shortlist
            </Button>
          </div>
          {vendorLeads.length > 0 ? (
            <div className="panel-subtitle">
              Showing {vendorLeads.length} vendor lead{vendorLeads.length === 1 ? '' : 's'} ready for review.
            </div>
          ) : null}
          {vendorLeadsQuery.isLoading ? (
          <LoadingState label="Loading vendor leads..." />
        ) : vendorLeads.length === 0 ? (
          <EmptyState title="No vendor leads yet" subtitle="Generate vendor research or seed USAspending awardees to start outreach." />
        ) : (
          <div className="vendor-grid">
            {vendorLeads.map((lead) => (
              <Card key={lead.id} className="vendor-card">
                <div className="vendor-header">
                  <div className="vendor-id">{lead.company_name || lead.cage || `Lead ${lead.id}`}</div>
                  <StatusPill status={lead.status || 'NEW'} />
                </div>
                <div className="panel-subtitle">
                  {compactMeta([
                    lead.cage ? `CAGE ${lead.cage}` : '',
                    lead.part_number ? `Part ${lead.part_number}` : '',
                    lead.source_label || formatBriefText(lead.source_type || 'Unknown', { punctuate: false }),
                  ]) || 'Lead details are still being organized.'}
                </div>
                {lead.provider_website || lead.provider_email || lead.provider_phone ? (
                  <div className="vendor-contact-strip">
                    {lead.provider_website ? (
                      <a href={lead.provider_website} target="_blank" rel="noreferrer">
                        Website
                      </a>
                    ) : null}
                    {lead.provider_email ? <span>{lead.provider_email}</span> : null}
                    {lead.provider_phone ? <span>{lead.provider_phone}</span> : null}
                  </div>
                ) : null}
                {lead.provider_item ? (
                  <div className="panel-subtitle">
                    Item: {formatBriefText(lead.provider_item, { punctuate: false })}
                  </div>
                ) : null}
                {lead.notes ? (
                  <div className="artifact-note-box">
                    <div className="row-title">Why This Lead Matters</div>
                    <div className="structured-copy">{formatBriefText(lead.notes, { punctuate: false })}</div>
                  </div>
                ) : null}
                <div className="table-action-stack">
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={targetedEmailMutation.isPending}
                    onClick={() =>
                      targetedEmailMutation.mutate({
                        opportunity_id: Number(id),
                        vendor_lead_id: lead.id,
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
                        vendor_lead_id: lead.id,
                      })
                    }
                  >
                    Promote to Quote Task
                  </Button>
                </div>
              </Card>
            ))}
          </div>
        )}
        </div>
      </Card>

        <Card title="Quote Response Tracker">
          {vendorQuotesQuery.isLoading ? (
            <LoadingState label="Loading vendor quotes..." />
          ) : vendorQuotes.length === 0 ? (
            <EmptyState
              title="No quote records yet"
              subtitle="Seed quote records from the current vendor leads, then log responses as vendors reply."
              action={<Button loading={seedQuotesMutation.isPending} onClick={() => seedQuotesMutation.mutate()}>Seed Quote Tracker</Button>}
            />
          ) : (
            <div className="workspace-action-column">
              <div className="results-toolbar">
                <div className="panel-subtitle">Tracking {vendorQuotes.length} vendor quote {vendorQuotes.length === 1 ? 'record' : 'records'}</div>
                <div className="company-form-actions">
                  <Button variant="secondary" loading={seedQuotesMutation.isPending} onClick={() => seedQuotesMutation.mutate()}>
                    Refresh From Leads
                  </Button>
                  <Button variant="secondary" onClick={exportQuoteComparisonCsv}>
                    Export Quote Comparison
                  </Button>
                  <Button variant="secondary" onClick={printBidSummary}>
                    Print Bid Summary
                  </Button>
                </div>
              </div>
              <div className="vendor-grid">
                {vendorQuotes.map((quote) => (
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
                        Status: {quoteComparison.find((item) => item.id === quote.id)?.normalized_status || quote.status || '-'}
                        {quote.unit_price ? ` | ${formatCurrency(quote.unit_price)}` : ''}
                        {quote.lead_time_days ? ` | ${quote.lead_time_days} day lead time` : ''}
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
                    </div>
                  </Card>
                ))}
              </div>
            </div>
          )}
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

      <div className="workspace-summary-grid">
          <Card title="Vendor Outreach Draft">
          {!emailArtifact ? (
            <EmptyState
              title="No outreach draft yet"
              subtitle="Generate a quote request draft grounded in the solicitation document and selected vendor context."
              action={<Button loading={generateEmailMutation.isPending} onClick={() => generateEmailMutation.mutate()}>Generate Email Draft</Button>}
            />
          ) : (
            <div className="workspace-action-column">
              {outreachSourceSummary ? (
                <div className="panel-subtitle">{outreachSourceSummary}</div>
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
                  }}
                >
                  Save Draft
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>
    </div>
  )

  const documentsContent = (
    <div className="workspace-documents-panel">
      <Card title="Documents">
        <div className="workspace-action-column">
          <div className="company-form-actions">
            <Button loading={downloadPdfsMutation.isPending || isIntakeRunning} onClick={() => downloadPdfsMutation.mutate()}>
              Download Documents
            </Button>
          </div>
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
            </div>
          ) : null}
          {filesQuery.isLoading ? (
            <LoadingState label="Loading documents..." />
          ) : files.length === 0 ? (
            <EmptyState
              title="No documents yet"
              subtitle={data.ui_hints?.empty_artifacts_message || 'Use Download Documents to fetch files for this opportunity.'}
            />
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
                {files.map((file) => (
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
                    Document processing is used by the workspace agents and compliance brief.
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

      <Card title="Compliance Brief">
        {!complianceArtifact ? (
          <EmptyState
            title="No compliance brief yet"
            subtitle="Download documents and let the processing pipeline organize what the solicitation requires, what is still missing, and what vendors need to answer."
          />
        ) : (
          <div className="workspace-action-column">
            <BriefDetailsBox
              title="Confirmed Facts"
              items={[
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
              <div className="row-title">Document Basis</div>
              <div className="structured-copy">
                {formatBriefText(
                  `${factSourceFile || 'Primary source document unavailable'} was used to build this compliance brief`,
                  { punctuate: true }
                )}
              </div>
            </div>
          </div>
        )}
      </Card>
    </div>
  )

  const scoringContent = (
    <div className="workspace-scoring-panel">
      <Card title="Pipeline Status">
        {!pipeline ? (
          <EmptyState
            title="No pipeline record yet"
            subtitle={
              isClosedSolicitation
                ? 'This closed solicitation can still be researched, but new active pipeline tracking is disabled.'
                : 'Create a workspace record to start tracking Bid / Not Bid decisions.'
            }
            action={
              <Button
                loading={ensurePipelineMutation.isPending}
                disabled={isClosedSolicitation}
                onClick={() => ensurePipelineMutation.mutate()}
              >
                Create Workspace Record
              </Button>
            }
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
                label="Probability of Win"
                type="number"
                min="0"
                max="100"
                value={pipelineForm.probability_of_win}
                disabled={isClosedSolicitation}
                onChange={(event) => setPipelineForm((current) => ({ ...current, probability_of_win: event.target.value }))}
              />
              <Input
                label="Target Submit Date"
                type="datetime-local"
                value={pipelineForm.target_submit_date}
                disabled={isClosedSolicitation}
                onChange={(event) => setPipelineForm((current) => ({ ...current, target_submit_date: event.target.value }))}
              />
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
      <Card title="Workspace Tasks">
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

          {tasks.length === 0 ? (
            <EmptyState title="No tasks yet" subtitle="Add the next concrete actions for capture, quoting, and submission." />
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
    </div>
  )

  const artifactsContent = (
    <div className="workspace-scoring-panel">
      <Card title="Checklist Artifact">
        {!checklistArtifact ? (
          <EmptyState
            title="No checklist yet"
            subtitle="Generate a checklist artifact to track requirements and bid readiness."
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
            {checklistDraft.map((item, index) => (
              <div key={item.id || index} className="checklist-edit-row">
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
                <Input
                  value={item.text}
                  onChange={(event) =>
                    setChecklistDraft((current) =>
                      current.map((entry, entryIndex) =>
                        entryIndex === index ? { ...entry, text: event.target.value } : entry
                      )
                    )
                  }
                />
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() =>
                    setChecklistDraft((current) => current.filter((_, entryIndex) => entryIndex !== index))
                  }
                >
                  Remove
                </Button>
              </div>
            ))}
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

        <Card title="Email Draft Artifact">
          {!emailArtifact ? (
            <EmptyState
              title="No email draft yet"
              subtitle="Generate an email draft artifact for vendor outreach."
            action={<Button loading={generateEmailMutation.isPending} onClick={() => generateEmailMutation.mutate()}>Generate Email Draft</Button>}
          />
          ) : (
            <div className="workspace-action-column">
              <BriefDetailsBox
                title="Draft Snapshot"
                items={[
                  formatDetailLine('Generated By', emailArtifact.content_json?.provider_status === 'openai' ? 'OpenAI' : 'Fallback workflow'),
                  formatDetailLine('Model', emailArtifact.content_json?.model_name || '-'),
                  formatDetailLine('Target Vendor', emailArtifact.content_json?.target_vendor_name || emailArtifact.content_json?.recommended_target_vendor?.company_name || '-'),
                  formatDetailLine('Source File', emailArtifact.content_json?.document_context?.source_file || '-'),
                ]}
              />
              <div className="artifact-note-box">
                <div className="row-title">Solicitation Context</div>
                <div className="panel-subtitle">{joinList(emailArtifact.content_json?.document_context?.document_signals || [])}</div>
              </div>
              <div className="artifact-section">
                <div className="row-title">Vendor Quote Items Requested</div>
                {emailVendorAsks.length === 0 ? (
                  <div className="panel-subtitle">No explicit vendor ask items have been generated yet.</div>
                ) : (
                  <div className="artifact-list">
                    {emailVendorAsks.map((item, index) => (
                      <div key={`email-ask-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                )}
              </div>
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
              {emailArtifact.content_json?.document_context?.extracted_preview ? (
                <div className="artifact-compare-box">
                  <div className="row-title">Document Preview Used</div>
                  <div className="row-subtitle debug-prewrap">
                    {emailArtifact.content_json.document_context.extracted_preview}
                  </div>
                </div>
              ) : null}
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
                Save Email Draft
              </Button>
            </div>
          </div>
        )}
      </Card>

      <Card title="Opportunity Analysis Artifact">
        {!analysisAssessment && !opportunityAnalysisArtifact ? (
          <EmptyState
            title="No opportunity analysis yet"
            subtitle="Run the Opportunity Analyst agent to generate a plain-English summary, risks, and recommended next actions."
          />
        ) : (
          <div className="workspace-action-column">
            <div><strong>Assessment:</strong> {analysisAssessment || '-'}</div>
            <div><strong>Reasons:</strong> {(analysisReasons || []).join(' | ') || '-'}</div>
            <div><strong>Risks / Blockers:</strong> {(analysisBlockers || []).join(' | ') || '-'}</div>
            <div><strong>Next Actions:</strong> {(analysisNextActions || []).join(' | ') || '-'}</div>
          </div>
        )}
      </Card>

        <Card title="Compliance Brief Artifact">
          {!complianceArtifact ? (
            <EmptyState
              title="No compliance brief yet"
              subtitle="Run the Compliance Document agent to summarize document findings and submission requirements."
            />
          ) : (
            <div className="workspace-action-column">
              <BriefDetailsBox
                title="Compliance Snapshot"
                items={
                  complianceFacts.length > 0
                    ? complianceFacts.map((fact) => formatDetailLine(fact.label, fact.label === 'Return By' ? formatDateTime(fact.value) : fact.value))
                    : [
                        formatDetailLine('Return By', formatDateTime(complianceArtifact.content_json?.compliance_fields?.return_by)),
                        formatDetailLine('Quantity', complianceArtifact.content_json?.compliance_fields?.quantity || '-'),
                        formatDetailLine('Solicitation', complianceArtifact.content_json?.compliance_fields?.solicitation_number || '-'),
                        formatDetailLine('PR Number', complianceArtifact.content_json?.compliance_fields?.pr_number || '-'),
                        formatDetailLine('Source File', complianceArtifact.content_json?.compliance_fields?.source_file || '-'),
                        formatDetailLine('Set-Aside', complianceArtifact.content_json?.compliance_fields?.set_aside_hint || '-'),
                      ]
                }
              />
              <div className="artifact-note-box">
                <div className="row-title">Compliance Snapshot</div>
                <div className="panel-subtitle">
                  Document count: {complianceArtifact.content_json?.document_count || 0} | Submission office: {complianceArtifact.content_json?.compliance_fields?.submission_office_hint || '-'} | Set-aside: {complianceArtifact.content_json?.compliance_fields?.set_aside_hint || '-'}
                </div>
              </div>
              <div className="artifact-section">
                <div className="row-title">Document Findings</div>
                <div className="artifact-list">
                  {(complianceArtifact.content_json?.document_findings || []).map((item, index) => (
                    <div key={`finding-${index}`} className="artifact-list-item">{item}</div>
                  ))}
                </div>
              </div>
              <div className="artifact-section">
                <div className="row-title">Requirements To Track</div>
                <div className="artifact-list">
                  {(complianceArtifact.content_json?.submission_requirements || []).map((item, index) => (
                    <div key={`submission-${index}`} className="artifact-list-item">{item}</div>
                  ))}
                  {(complianceArtifact.content_json?.compliance_fields?.clauses_or_requirements || []).map((item, index) => (
                    <div key={`clause-${index}`} className="artifact-list-item">{item}</div>
                  ))}
                </div>
              </div>
              <div className="artifact-section">
                <div className="row-title">Missing Or Unconfirmed Information</div>
                {complianceMissingInfo.length === 0 && !(complianceArtifact.content_json?.missing_documents || []).length ? (
                  <div className="panel-subtitle">No obvious missing information was flagged from the current documents.</div>
                ) : (
                  <div className="artifact-list">
                    {complianceMissingInfo.map((item, index) => (
                      <div key={`missing-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                    {(complianceArtifact.content_json?.missing_documents || []).map((item, index) => (
                      <div key={`missing-doc-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                )}
              </div>
              <div className="artifact-section">
                <div className="row-title">Vendor Quote Items To Request</div>
                {complianceVendorAsks.length === 0 ? (
                  <div className="panel-subtitle">No explicit vendor request items were generated yet.</div>
                ) : (
                  <div className="artifact-list">
                    {complianceVendorAsks.map((item, index) => (
                      <div key={`vendor-request-${index}`} className="artifact-list-item">{item}</div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </Card>

      <Card title="Vendor Research Artifact">
        {!vendorResearchArtifact ? (
          <EmptyState
            title="No vendor research yet"
            subtitle="Run the Vendor Research agent to capture likely vendors, approved sources, and query evidence."
          />
        ) : (
          <div className="workspace-action-column">
            <div><strong>Top Workspace Leads:</strong> {(vendorResearchArtifact.content_json?.top_workspace_leads || []).length}</div>
            <div><strong>Likely Vendors:</strong> {(vendorResearchArtifact.content_json?.likely_vendors || []).length}</div>
            {(vendorResearchArtifact.content_json?.top_workspace_leads || []).slice(0, 3).map((lead, index) => (
              <div key={`lead-${index}`} className="row-subtitle">
                {lead.company_name} | {lead.cage || '-'} | {lead.source_type || '-'} | confidence {lead.confidence ?? '-'}
              </div>
            ))}
            {(vendorResearchArtifact.content_json?.likely_vendors || []).slice(0, 3).map((vendor, index) => (
              <div key={`vendor-${index}`} className="row-subtitle">
                {vendor.vendor} | {(vendor.why_matched || []).join(', ') || '-'}
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Vendor Shortlist Artifact">
        {!vendorListArtifact ? (
          <EmptyState
            title="No vendor shortlist yet"
            subtitle="Generate vendor research to create the shortlist artifact."
            action={<Button loading={generateVendorsMutation.isPending} onClick={() => generateVendorsMutation.mutate()}>Generate Vendor Shortlist</Button>}
          />
        ) : (
          <div className="workspace-action-column">
            <div><strong>Approved Sources:</strong> {vendorListArtifact.content_json?.approved_source_count || 0}</div>
            <div><strong>CAGE Codes:</strong> {(vendorListArtifact.content_json?.cage_codes || []).slice(0, 8).join(', ') || '-'}</div>
            <div><strong>Part Numbers:</strong> {(vendorListArtifact.content_json?.part_numbers || []).slice(0, 8).join(', ') || '-'}</div>
            <div><strong>Profile Terms:</strong> {(vendorListArtifact.content_json?.research_profile?.keyword_terms || []).join(', ') || '-'}</div>
          </div>
        )}
      </Card>

      <Card title="Research Brief Artifact">
        {!researchBriefArtifact ? (
          <EmptyState
            title="No research brief yet"
            subtitle="Generate a research brief to capture parsed signals, risks, and USAspending vendor evidence."
            action={
              <Button loading={generateResearchBriefMutation.isPending} onClick={() => generateResearchBriefMutation.mutate()}>
                Generate Research Brief
              </Button>
            }
          />
        ) : (
          <div className="workspace-action-column">
            <div><strong>Summary:</strong> {researchBriefArtifact.content_json?.summary?.title || opp.display_title || opp.title}</div>
            <div><strong>Status:</strong> {researchBriefArtifact.content_json?.summary?.solicitation_status || solicitationStatus}</div>
            <div><strong>Likely Vendors:</strong> {(researchBriefArtifact.content_json?.usaspending_snapshot?.likely_vendors || []).length}</div>
            <div><strong>Risks:</strong> {(researchBriefArtifact.content_json?.risks || []).join(' | ') || '-'}</div>
            <details className="workspace-detail-panel">
              <summary>View research brief detail</summary>
              <div className="artifact-compare-box">
                <div className="row-subtitle debug-prewrap">
                  {JSON.stringify(researchBriefArtifact.content_json || {}, null, 2)}
                </div>
              </div>
            </details>
          </div>
        )}
      </Card>

      <Card title="Submission Package Artifact">
        {!submissionPackageArtifact ? (
          <EmptyState
            title="No saved submission package yet"
            subtitle="Save the current submission package so this review state is preserved as a workspace artifact."
            action={
              <Button loading={generateSubmissionPackageMutation.isPending} onClick={() => generateSubmissionPackageMutation.mutate()}>
                Save Submission Package
              </Button>
            }
          />
        ) : (
          <div className="workspace-action-column">
            <BriefDetailsBox
              title="Saved Snapshot"
              items={[
                formatDetailLine('Generated', formatDateTime(submissionPackageArtifact.created_at)),
                formatDetailLine('Status', submissionPackageArtifact.content_json?.submission?.status || '-'),
                formatDetailLine('Planned Vendor', submissionPackageArtifact.content_json?.planned_vendor?.company_name || submissionPackageArtifact.content_json?.planned_vendor?.cage || '-'),
                formatDetailLine('Outcome', submissionPackageArtifact.content_json?.submission?.outcome_summary || submissionPackageArtifact.content_json?.submission?.status || '-'),
              ]}
            />
            <div className="artifact-note-box">
              <div className="row-title">Snapshot Summary</div>
              <div className="panel-subtitle">
                {submissionPackageArtifact.content_json?.summary?.title || opp.display_title || opp.title}
              </div>
            </div>
          </div>
        )}
      </Card>

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
                  {selectedArtifactCompare?.artifactId === artifact.id ? (
                    <div className="artifact-compare-box">
                      <div className="row-subtitle"><strong>Current title:</strong> {artifact.title}</div>
                      <div className="row-subtitle"><strong>Previous title:</strong> {selectedArtifactCompare.version?.title || '-'}</div>
                      <div className="row-subtitle debug-prewrap">
                        {JSON.stringify(selectedArtifactCompare.version?.content_json || {}, null, 2)}
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="workspace-action-column">
                  <StatusPill status={artifact.artifact_type} />
                  {(artifact.version_history || []).length > 0 ? (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() =>
                          setSelectedArtifactCompare({
                            artifactId: artifact.id,
                            versionIndex: (artifact.version_history || []).length - 1,
                            version: (artifact.version_history || [])[artifact.version_history.length - 1],
                          })
                        }
                      >
                        Compare Last Version
                      </Button>
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
    </div>
  )

  const agentsContent = (
    <div className="workspace-scoring-panel">
      <Card title="Phased Agent Center">
        <div className="workspace-action-column">
          <div className="panel-subtitle">
            Agents are phased so we can keep outputs traceable: analysis first, then outreach, then execution planning.
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
                  <div className="row-subtitle">{(agents || []).join(', ')}</div>
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

      <Card title="Individual Agents">
        <div className="workspace-action-column">
          {lastAgentRunResult ? (
            <div className="workspace-mode-banner">
              <div className="row-title">{String(lastAgentRunResult.agent_key || '').replace(/_/g, ' ')} completed</div>
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
          {Object.entries(AGENT_DESCRIPTIONS).map(([agentKey, description]) => (
            <div key={agentKey} className="artifact-history-row">
              <div>
                <div className="row-title">{agentKey.replace(/_/g, ' ')}</div>
                <div className="row-subtitle">{description}</div>
              </div>
              <Button
                size="sm"
                loading={runAgentMutation.isPending && runAgentMutation.variables === agentKey}
                onClick={() => runAgentMutation.mutate(agentKey)}
              >
                Run Agent
              </Button>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Agent Run History">
        {agentRuns.length === 0 ? (
          <EmptyState
            title="No agent runs yet"
            subtitle="Run a phase or individual agent to start building traceable AI outputs in the workspace."
          />
        ) : (
          <div className="workspace-action-column">
            {agentRuns.map((run) => (
              <div key={run.id} className="artifact-history-row">
                <div>
                  <div className="row-title">{String(run.agent_key || run.agent_type || '').replace(/_/g, ' ')}</div>
                  <div className="row-subtitle">
                    Created {formatDateTime(run.created_at)}{run.completed_at ? ` | Completed ${formatDateTime(run.completed_at)}` : ''}
                  </div>
                  {run.error_message ? <div className="row-subtitle">{run.error_message}</div> : null}
                  {run.output_payload ? (
                    <details className="workspace-detail-panel">
                      <summary>View agent output</summary>
                      <div className="row-subtitle debug-prewrap">
                        {JSON.stringify(run.output_payload, null, 2)}
                      </div>
                    </details>
                  ) : null}
                </div>
                <StatusPill status={run.status || 'pending'} />
              </div>
            ))}
          </div>
        )}
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
                  : `Current status: ${submission?.status || 'DRAFT'}${submission?.planned_vendor_name || submission?.planned_vendor_cage ? ` | Planned vendor: ${submission?.planned_vendor_name || submission?.planned_vendor_cage}` : ''}`}
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

      <Card title="Research Debug">
        {usaspendingDebug.length === 0 ? (
          <EmptyState title="No query trace yet" subtitle="Run USAspending research to inspect the fallback payload path when you actually need it." />
        ) : (
          <div className="workspace-action-column">
            {usaspendingDebug.map((entry, index) => (
              <div key={`debug-${index}`} className="artifact-history-row">
                <div>
                  <div className="row-title">{entry.label}</div>
                  <div className="row-subtitle">Results: {entry.count || 0}</div>
                  <details className="workspace-detail-panel">
                    <summary>View query payload</summary>
                    <div className="row-subtitle debug-prewrap">{JSON.stringify(entry.filters || {}, null, 2)}</div>
                  </details>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )

  const tabs = [
    { label: 'Overview', content: overviewContent },
    { label: 'Vendors', content: vendorsContent },
    { label: 'Documents', content: documentsContent },
    { label: 'Submission Package', content: submissionPackageContent },
    { label: 'Submission', content: submissionContent },
  ]

  return (
    <div className="page">
      <div className="workspace-header workspace-hero">
        <div className="workspace-hero-copy">
          <div className="workspace-kicker">Opportunity Workspace</div>
          <h1 className="page-title">{opp.display_title || opp.title || 'Opportunity Workspace'}</h1>
          <div className="workspace-hero-subtitle">
            {opp.agency || 'Agency unavailable'} | {opp.source || 'Source unavailable'} | Due {formatDateOnly(factReturnBy)}
          </div>
        </div>
        <div className="workspace-hero-meta">
          <StatusPill status={solicitationStatus || 'UNKNOWN'} />
          {opp.source ? <Badge label={opp.source} variant={opp.source === 'SAM' ? 'success' : 'info'} /> : null}
          {opp.set_aside_type ? <Badge label={setAsideBadgeLabel(opp.set_aside_type)} variant={setAsideBadgeVariant(opp.set_aside_type)} /> : null}
        </div>
      </div>
      <Tabs tabs={tabs} />
    </div>
  )
}
