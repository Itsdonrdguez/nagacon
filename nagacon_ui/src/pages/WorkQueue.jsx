import { Link } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, Button, Card, EmptyState, LoadingState } from '../components/ui'

const PRIORITY_VARIANT = {
  HIGH: 'error',
  MEDIUM: 'warning',
  LOW: 'info',
}

const TYPE_LABELS = {
  QUOTE_FOLLOW_UP_DUE: 'Quote Chase',
  QUOTE_REQUESTED_NO_RESPONSE: 'Awaiting Quote',
  RFQ_CLOSING_SOON: 'Due Soon',
  MISSING_VENDOR_LEADS: 'Sourcing',
  MISSING_PART_FINDER: 'NSN Intelligence',
  RFQ_NOT_SENT: 'Supplier Outreach',
  READY_TO_SUBMIT: 'Package Prep',
  MISSING_SUBMISSION_PACKAGE: 'Submission Prep',
  CLOSED_WORKSPACE_PREP: 'Closed Prep',
  AWARDEE_ENRICHMENT_READY: 'Closed Intelligence',
  NSN_INTELLIGENCE_REFRESH: 'NSN Intelligence',
  WORKSPACE_PREP_RUNNING: 'Workspace Prep',
  SAM_CHECKLIST_MISSING: 'Proposal Setup',
  SAM_COMPLIANCE_MATRIX_MISSING: 'Compliance Review',
  SAM_CO_EMAIL_MISSING: 'CO Outreach',
  SAM_TARGET_SUBMIT_DATE_MISSING: 'Proposal Setup',
  SAM_TASKS_NOT_SEEDED: 'Proposal Setup',
  SAM_OPEN_TASKS_MISSING: 'Proposal Review',
  SAM_SUBMISSION_PACKAGE_MISSING: 'Submission Prep',
  DIBBS_RFQ_PACKAGE_MISSING: 'RFQ Package',
}

const DESK_FILTERS = [
  ['all', 'All Work'],
  ['needs_review', 'Needs Review'],
  ['ready_to_work', 'Ready to Work'],
  ['waiting_on_vendor', 'Waiting on Vendor'],
  ['due_soon', 'Due Soon'],
  ['overdue', 'Overdue'],
  ['done', 'Done'],
]

const DESK_SECTIONS = ['needs_review', 'ready_to_work', 'waiting_on_vendor', 'due_soon', 'overdue', 'done']

const DESK_LABELS = {
  needs_review: 'Needs Review',
  ready_to_work: 'Ready to Work',
  waiting_on_vendor: 'Waiting on Vendor',
  due_soon: 'Due Soon',
  overdue: 'Overdue',
  done: 'Done',
}

const DESK_SUBTITLES = {
  needs_review: 'New work that needs a first look before we commit time.',
  ready_to_work: 'Prepared items we can move forward right now.',
  waiting_on_vendor: 'Work that depends on supplier or quote movement.',
  due_soon: 'Time-sensitive items that need attention before the deadline closes in.',
  overdue: 'Missed or failed work that needs recovery.',
  done: 'Recently completed items kept here for quick confirmation.',
}

const ACTION_RANK = {
  QUOTE_FOLLOW_UP_DUE: 0,
  READY_TO_SUBMIT: 1,
  RFQ_NOT_SENT: 2,
  MISSING_VENDOR_LEADS: 3,
  MISSING_PART_FINDER: 4,
  NSN_INTELLIGENCE_REFRESH: 5,
  WORKSPACE_PREP_RUNNING: 6,
  DIBBS_RFQ_PACKAGE_MISSING: 6,
  RFQ_CLOSING_SOON: 7,
  MISSING_SUBMISSION_PACKAGE: 8,
  QUOTE_REQUESTED_NO_RESPONSE: 9,
  AWARDEE_ENRICHMENT_READY: 10,
}

const PRIMARY_ACTIONS = {
  QUOTE_FOLLOW_UP_DUE: {
    heading: 'Send follow-up',
    detail: 'RFQ outreach has gone quiet and the follow-up window has passed.',
  },
  QUOTE_REQUESTED_NO_RESPONSE: {
    heading: 'Check quote progress',
    detail: 'A quote request has been sent, but the response is still missing.',
  },
  RFQ_CLOSING_SOON: {
    heading: 'Review the due date now',
    detail: 'This opportunity is approaching its deadline and needs a decision on the next move.',
  },
  MISSING_VENDOR_LEADS: {
    heading: 'Find suppliers',
    detail: 'No usable supplier candidates are attached yet, so sourcing is the best next move.',
  },
  MISSING_PART_FINDER: {
    heading: 'Build NSN intelligence',
    detail: 'The item still needs part and source intelligence before supplier outreach will be reliable.',
  },
  RFQ_NOT_SENT: {
    heading: 'Open RFQ draft',
    detail: 'Suppliers exist, but RFQ outreach has not been sent yet.',
  },
  READY_TO_SUBMIT: {
    heading: 'Prepare submission package',
    detail: 'A usable quote exists, and the package can move toward submission.',
  },
  MISSING_SUBMISSION_PACKAGE: {
    heading: 'Prepare package',
    detail: 'The operational pieces are in motion, but the package is not assembled yet.',
  },
  CLOSED_WORKSPACE_PREP: {
    heading: 'Queue closed workspace prep',
    detail: 'This recently closed solicitation still needs the full extraction and intelligence pass.',
  },
  AWARDEE_ENRICHMENT_READY: {
    heading: 'Review closed intelligence',
    detail: 'This closed solicitation can sharpen future vendor and awardee research.',
  },
  NSN_INTELLIGENCE_REFRESH: {
    heading: 'Open NSN intelligence',
    detail: 'This NSN still needs a saved intelligence record before sourcing is complete.',
  },
  WORKSPACE_PREP_RUNNING: {
    heading: 'Workspace prep is running',
    detail: 'The background prep is building document coverage, part intelligence, vendor leads, and workspace artifacts.',
  },
  SAM_CHECKLIST_MISSING: {
    heading: 'Start win strategy review',
    detail: 'This SAM workspace still needs the basic proposal setup work before it can move cleanly.',
  },
  SAM_COMPLIANCE_MATRIX_MISSING: {
    heading: 'Build the compliance matrix',
    detail: 'Submission requirements still need to be captured into a usable review matrix.',
  },
  SAM_CO_EMAIL_MISSING: {
    heading: 'Draft contracting officer outreach',
    detail: 'There is no saved contracting officer draft yet for this SAM opportunity.',
  },
  SAM_TARGET_SUBMIT_DATE_MISSING: {
    heading: 'Set the target submit date',
    detail: 'Proposal tracking exists, but the internal target submit date is still missing.',
  },
  SAM_TASKS_NOT_SEEDED: {
    heading: 'Set up the proposal plan',
    detail: 'The workspace still needs the core planning steps that move the pursuit into execution.',
  },
  SAM_OPEN_TASKS_MISSING: {
    heading: 'Add active proposal steps',
    detail: 'The proposal is active, but there are no open work items driving it forward.',
  },
  SAM_SUBMISSION_PACKAGE_MISSING: {
    heading: 'Build the submission package',
    detail: 'Proposal work is active, but the final submission package has not been assembled yet.',
  },
  DIBBS_RFQ_PACKAGE_MISSING: {
    heading: 'Download the RFQ package',
    detail: 'The RFQ package is still missing, so the sourcing team cannot review the actual requirements yet.',
  },
}

const compactMeta = (parts) => parts.filter(Boolean).join(' | ')

const queueStatusLabel = (value) => String(value || '').toUpperCase() || 'QUEUED'

const formatDate = (value) => {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  })
}

const parseDate = (value) => {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function buildVendorResearchUrl(item) {
  const params = new URLSearchParams()
  params.set('source', 'today')
  params.set('opportunity_id', String(item.opportunity?.id || ''))
  if (item.meta?.title || item.opportunity?.title) params.set('title', item.meta?.title || item.opportunity?.title)
  if (item.meta?.agency || item.opportunity?.agency) params.set('agency', item.meta?.agency || item.opportunity?.agency)
  if (item.opportunity?.solicitation_number) params.set('sol', item.opportunity.solicitation_number)
  if (item.meta?.nsn) params.set('nsn', item.meta.nsn)
  if (item.meta?.fsc || item.opportunity?.fsc) params.set('fsc', item.meta?.fsc || item.opportunity?.fsc)
  if (item.meta?.title || item.opportunity?.title) params.set('q', item.meta?.title || item.opportunity?.title)
  return `/vendors?${params.toString()}`
}

function buildWorkspaceUrl(item, tab = '') {
  const oppId = item?.opportunity?.id
  if (!oppId) return '/work-queue'
  const params = new URLSearchParams()
  if (tab) params.set('tab', tab)
  const query = params.toString()
  return `/workspace/${oppId}${query ? `?${query}` : ''}`
}

function buildNsnIntelligenceUrl(item, mode = 'lookup') {
  const params = new URLSearchParams()
  params.set('source', 'today')
  params.set('mode', mode)
  params.set('opportunity_id', String(item.opportunity?.id || ''))
  if (item.opportunity?.solicitation_number) params.set('sol', item.opportunity.solicitation_number)
  if (item.opportunity?.title) params.set('title', item.opportunity.title)
  if (item.meta?.nsn) params.set('nsn', item.meta.nsn)
  return `/nsn-intelligence?${params.toString()}`
}

function recommendedActionLink(item) {
  if (!item) return { to: item?.action_url || '/work-queue', label: 'Open Workspace' }
  if (item.type === 'MISSING_VENDOR_LEADS') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Find Suppliers' }
  }
  if (item.type === 'MISSING_PART_FINDER') {
    return { to: buildNsnIntelligenceUrl(item, 'lookup'), label: 'Analyze NSN' }
  }
  if (item.type === 'NSN_INTELLIGENCE_REFRESH') {
    return { to: buildNsnIntelligenceUrl(item, 'build'), label: 'Open NSN Intelligence' }
  }
  if (item.type === 'WORKSPACE_PREP_RUNNING') {
    return { to: buildWorkspaceUrl(item), label: 'Open Workspace' }
  }
  if (item.type === 'RFQ_NOT_SENT') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Open RFQ Draft' }
  }
  if (item.type === 'READY_TO_SUBMIT') {
    return { to: buildWorkspaceUrl(item, 'submission-package'), label: 'Open Submission Package' }
  }
  if (item.type === 'RFQ_CLOSING_SOON') {
    return { to: buildWorkspaceUrl(item), label: 'Review Opportunity' }
  }
  if (item.type === 'MISSING_SUBMISSION_PACKAGE') {
    return { to: buildWorkspaceUrl(item, 'submission-package'), label: 'Prepare Package' }
  }
  if (item.type === 'QUOTE_REQUESTED_NO_RESPONSE') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Review Quote Progress' }
  }
  if (item.type === 'QUOTE_FOLLOW_UP_DUE') {
    return { to: buildWorkspaceUrl(item, 'sources-quotes'), label: 'Send Follow-up' }
  }
  if (item.type === 'DIBBS_RFQ_PACKAGE_MISSING') {
    return { to: buildWorkspaceUrl(item, 'rfq-package'), label: 'Open RFQ Package' }
  }
  if (item.type === 'CLOSED_WORKSPACE_PREP') {
    return { to: buildWorkspaceUrl(item), label: 'Open Closed Workspace' }
  }
  if (item.type === 'AWARDEE_ENRICHMENT_READY') {
    return { to: item.action_url, label: 'Review Closed Intelligence' }
  }
  if (item.type === 'MISSING_VENDOR_LEADS') {
    return { to: buildVendorResearchUrl(item), label: 'Research Vendors' }
  }
  return { to: item.action_url, label: item.action_label || 'Open Workspace' }
}

function groupActionItems(items) {
  const groups = new Map()
  for (const item of items) {
    const oppId = item.opportunity?.id || item.id
    const current = groups.get(oppId) || {
      opportunity: item.opportunity,
      items: [],
    }
    current.items.push(item)
    groups.set(oppId, current)
  }
  return Array.from(groups.values())
    .map((group) => {
      const sorted = [...group.items].sort((a, b) => {
        const priorityOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
        const priorityGap = (priorityOrder[a.priority] ?? 9) - (priorityOrder[b.priority] ?? 9)
        if (priorityGap !== 0) return priorityGap
        return (ACTION_RANK[a.type] ?? 99) - (ACTION_RANK[b.type] ?? 99)
      })
      const primary = sorted[0]
      return {
        ...group,
        primary,
        additionalItems: sorted.slice(1),
      }
    })
    .sort((a, b) => {
      const priorityOrder = { HIGH: 0, MEDIUM: 1, LOW: 2 }
      const primaryGap = (priorityOrder[a.primary?.priority] ?? 9) - (priorityOrder[b.primary?.priority] ?? 9)
      if (primaryGap !== 0) return primaryGap
      return (a.primary?.due_at || '9999').localeCompare(b.primary?.due_at || '9999')
    })
}

function classifyDeskStatus(item, kind = 'group') {
  const queueState = item.queue_state || {}
  const status = String(queueState.status || item.status || '').toLowerCase()
  const type = String(item.type || '').toUpperCase()
  const dueAt = parseDate(item.due_at || item.opportunity?.due_at)
  const now = new Date()

  if (kind === 'completed' || status === 'success' || status === 'completed') return 'done'
  if (kind === 'failed' || status === 'failed') return 'overdue'
  if (type === 'RFQ_CLOSING_SOON' && dueAt && dueAt < now) return 'overdue'
  if (type === 'WORKSPACE_PREP_RUNNING' || type === 'READY_TO_SUBMIT' || type === 'MISSING_SUBMISSION_PACKAGE' || type === 'MISSING_PART_FINDER' || type === 'NSN_INTELLIGENCE_REFRESH' || type === 'DIBBS_RFQ_PACKAGE_MISSING' || type === 'AWARDEE_ENRICHMENT_READY' || type === 'CLOSED_WORKSPACE_PREP' || type.startsWith('SAM_')) {
    return 'ready_to_work'
  }
  if (type === 'QUOTE_FOLLOW_UP_DUE' || type === 'QUOTE_REQUESTED_NO_RESPONSE' || type === 'RFQ_NOT_SENT' || type === 'MISSING_VENDOR_LEADS') {
    return 'waiting_on_vendor'
  }
  if (type === 'RFQ_CLOSING_SOON') return 'due_soon'
  return 'needs_review'
}

function getOpportunityIdFromCard(card) {
  return Number(card?.group?.opportunity?.id || card?.item?.opportunity?.id || 0) || null
}

export default function WorkQueue() {
  const [filter, setFilter] = useState('all')
  const [backgroundJobId, setBackgroundJobId] = useState(null)
  const [queueTodayResult, setQueueTodayResult] = useState(null)
  const [hideCompleted, setHideCompleted] = useState(true)
  const [selectedOpportunityIds, setSelectedOpportunityIds] = useState([])
  const queryClient = useQueryClient()

  const workQueueQuery = useQuery({
    queryKey: ['work-queue-today'],
    queryFn: async () => {
      const res = await api.get('/api/work-queue/today')
      return res.data
    },
    retry: 1,
  })

  const data = workQueueQuery.data || {}
  const items = data.items || []
  const inProgressItems = data.in_progress_items || []
  const recentCompletedItems = data.recent_completed_items || []
  const recentFailedItems = data.recent_failed_items || []
  const collectionSummary = data.collection_summary || {}

  const backgroundJobQuery = useQuery({
    queryKey: ['work-queue-background-job', backgroundJobId],
    enabled: Boolean(backgroundJobId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'success' || status === 'failed' ? false : 1500
    },
    queryFn: async () => {
      const res = await api.get(`/api/search-jobs/${backgroundJobId}`)
      return res.data
    },
  })

  const refreshQueue = () => {
    queryClient.invalidateQueries({ queryKey: ['work-queue-today'] })
  }

  const queueBackgroundMutation = useMutation({
    mutationFn: async (item) => {
      const opportunityId = item.opportunity?.id
      if (item.type === 'AWARDEE_ENRICHMENT_READY') {
        const res = await api.post(`/api/opportunities/${opportunityId}/awardee-enrichment-job`, null, {
          params: { force: true },
        })
        return res.data
      }
      if (item.type === 'NSN_INTELLIGENCE_REFRESH' && item.meta?.nsn) {
        const cleanNsn = String(item.meta.nsn || '').replace(/\D+/g, '')
        const res = await api.post(`/api/nsn/${cleanNsn}/build-job`, null, {
          params: {
            run_usaspending: true,
            seed_providers: true,
            limit: 50,
          },
        })
        return res.data
      }
      throw new Error('No background job available for this work item.')
    },
    onSuccess: (job) => {
      setBackgroundJobId(job.id)
      refreshQueue()
    },
  })

  const queueTodayMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/work-queue/queue-today', null, {
        params: { limit: 200 },
      })
      return res.data
    },
    onSuccess: (result) => {
      setQueueTodayResult(result)
      refreshQueue()
      const firstJobId = result?.queued_jobs?.[0]?.job_id
      if (firstJobId) setBackgroundJobId(firstJobId)
    },
  })

  const bulkPrepareMutation = useMutation({
    mutationFn: async (opportunityIds) => {
      const res = await api.post('/api/opportunities/bulk/workspace-intake', {
        opportunity_ids: opportunityIds,
        download_documents: true,
        run_usaspending: true,
      })
      return res.data
    },
    onSuccess: (result) => {
      setQueueTodayResult({
        queued_count: result.queued_count || 0,
        skipped_duplicate_count: result.skipped_duplicate_count || 0,
        queueable_items: result.requested_count || 0,
        queued_jobs: result.queued_jobs || [],
      })
      setSelectedOpportunityIds([])
      refreshQueue()
      const firstJobId = result?.queued_jobs?.[0]?.job_id
      if (firstJobId) setBackgroundJobId(firstJobId)
    },
  })

  const markReviewedMutation = useMutation({
    mutationFn: async (opportunityIds) => {
      const results = []
      for (const opportunityId of opportunityIds) {
        let pipeline = null
        try {
          const existing = await api.get(`/api/pipeline/by-opportunity/${opportunityId}`)
          pipeline = existing.data
        } catch (error) {
          pipeline = null
        }
        if (!pipeline?.id) {
          const created = await api.post(`/api/pipeline/by-opportunity/${opportunityId}`)
          pipeline = created.data
        }
        const updated = await api.patch(`/api/pipeline/${pipeline.id}`, {
          decision_status: 'IN_PROGRESS',
        })
        results.push(updated.data)
      }
      return results
    },
    onSuccess: () => {
      setSelectedOpportunityIds([])
      refreshQueue()
    },
  })

  const refreshIntelligenceMutation = useMutation({
    mutationFn: async (cards) => {
      const results = []
      for (const card of cards) {
        const opportunityId = getOpportunityIdFromCard(card)
        if (!opportunityId) continue
        const primaryItem = card.group?.primary || card.item
        if (primaryItem?.type === 'AWARDEE_ENRICHMENT_READY' || primaryItem?.type === 'CLOSED_WORKSPACE_PREP') {
          const res = await api.post(`/api/opportunities/${opportunityId}/awardee-enrichment-job`, null, {
            params: { force: true },
          })
          results.push(res.data)
          continue
        }
        const res = await api.post(`/api/parts/opportunity/${opportunityId}/refresh`)
        results.push(res.data)
      }
      return results
    },
    onSuccess: () => {
      setSelectedOpportunityIds([])
      refreshQueue()
    },
  })

  const groupedVisibleItems = useMemo(() => groupActionItems(items), [items])

  const missionCards = useMemo(() => {
    const cards = []

    for (const item of inProgressItems) {
      cards.push({
        kind: 'job',
        deskStatus: classifyDeskStatus(item, 'job'),
        statusLabel: String(item.display_status || queueStatusLabel(item.queue_state?.status)).toUpperCase(),
        item,
      })
    }

    for (const item of recentFailedItems) {
      cards.push({
        kind: 'failed',
        deskStatus: 'overdue',
        statusLabel: 'FAILED',
        item,
      })
    }

    for (const group of groupedVisibleItems) {
      const primary = group.primary
      cards.push({
        kind: 'group',
        deskStatus: classifyDeskStatus(primary, 'group'),
        statusLabel: String(primary.display_status || 'OPEN').toUpperCase(),
        item: primary,
        group,
      })
    }

    for (const item of recentCompletedItems) {
      cards.push({
        kind: 'completed',
        deskStatus: 'done',
        statusLabel: 'DONE',
        item,
      })
    }

    return cards
  }, [groupedVisibleItems, inProgressItems, recentCompletedItems, recentFailedItems])

  const filterCounts = useMemo(() => {
    const counts = { all: 0 }
    for (const card of missionCards) {
      counts.all += hideCompleted && card.deskStatus === 'done' ? 0 : 1
      counts[card.deskStatus] = (counts[card.deskStatus] || 0) + 1
    }
    return counts
  }, [missionCards, hideCompleted])

  const visibleCards = useMemo(() => {
    const base = missionCards.filter((card) => !(hideCompleted && card.deskStatus === 'done'))
    if (filter === 'all') return base
    return base.filter((card) => card.deskStatus === filter)
  }, [filter, hideCompleted, missionCards])

  const cardsBySection = useMemo(() => {
    const grouped = Object.fromEntries(DESK_SECTIONS.map((key) => [key, []]))
    for (const card of visibleCards) {
      grouped[card.deskStatus]?.push(card)
    }
    return grouped
  }, [visibleCards])

  const spotlightStats = useMemo(() => ([
    { key: 'needs_review', label: 'Needs Review', value: filterCounts.needs_review || 0, subtitle: 'New work to triage' },
    { key: 'ready_to_work', label: 'Ready to Work', value: filterCounts.ready_to_work || 0, subtitle: 'Actionable now' },
    { key: 'waiting_on_vendor', label: 'Waiting on Vendor', value: filterCounts.waiting_on_vendor || 0, subtitle: 'Quote and outreach movement' },
    { key: 'due_soon', label: 'Due Soon', value: filterCounts.due_soon || 0, subtitle: 'Deadline pressure building' },
    { key: 'overdue', label: 'Overdue', value: filterCounts.overdue || 0, subtitle: 'Needs recovery' },
    { key: 'done', label: 'Done', value: filterCounts.done || 0, subtitle: 'Recently completed' },
  ]), [filterCounts])

  const selectedCards = useMemo(
    () => visibleCards.filter((card) => selectedOpportunityIds.includes(getOpportunityIdFromCard(card))),
    [selectedOpportunityIds, visibleCards],
  )

  const selectedSummary = useMemo(() => {
    const labels = new Set(selectedCards.map((card) => DESK_LABELS[card.deskStatus] || 'Work'))
    return Array.from(labels).join(' | ')
  }, [selectedCards])

  useEffect(() => {
    if (backgroundJobQuery.data?.status === 'success') {
      refreshQueue()
    }
  }, [backgroundJobQuery.data?.status])

  const primaryActionMeta = (item) => PRIMARY_ACTIONS[item?.type] || {
    heading: item?.action_label || 'Open workspace',
    detail: item?.subtitle || 'Open the workspace and continue the next step.',
  }

  const toggleSelection = (card) => {
    const opportunityId = getOpportunityIdFromCard(card)
    if (!opportunityId) return
    setSelectedOpportunityIds((current) => (
      current.includes(opportunityId)
        ? current.filter((value) => value !== opportunityId)
        : [...current, opportunityId]
    ))
  }

  const handleBulkPrepare = () => {
    if (selectedOpportunityIds.length === 0) return
    if (!window.confirm(`Prepare ${selectedOpportunityIds.length} selected workspace${selectedOpportunityIds.length === 1 ? '' : 's'} and send them into Today queue?`)) return
    bulkPrepareMutation.mutate(selectedOpportunityIds)
  }

  const handleMarkReviewed = () => {
    if (selectedOpportunityIds.length === 0) return
    if (!window.confirm(`Mark ${selectedOpportunityIds.length} selected item${selectedOpportunityIds.length === 1 ? '' : 's'} as reviewed?`)) return
    markReviewedMutation.mutate(selectedOpportunityIds)
  }

  const handleRefreshIntelligence = () => {
    if (selectedCards.length === 0) return
    if (!window.confirm(`Refresh intelligence for ${selectedCards.length} selected item${selectedCards.length === 1 ? '' : 's'}?`)) return
    refreshIntelligenceMutation.mutate(selectedCards)
  }

  if (workQueueQuery.isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading work queue..." />
        </Card>
      </div>
    )
  }

  if (workQueueQuery.error) {
    return (
      <div className="page">
        <EmptyState
          title="Work queue unavailable"
          subtitle={workQueueQuery.error.message || 'Failed to load daily work queue.'}
          action={<Button onClick={() => workQueueQuery.refetch()}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <div className="page-kicker">Command Center</div>
          <h1 className="page-title">Today</h1>
          <div className="page-subtitle">
            Use this as your follow-up desk: review new work, move ready items forward, and keep vendor motion from getting buried.
          </div>
        </div>
        <div className="company-form-actions">
          <Button onClick={() => queueTodayMutation.mutate()} loading={queueTodayMutation.isPending}>
            Queue Work
          </Button>
          <Button variant="secondary" onClick={() => workQueueQuery.refetch()}>
            Refresh Status
          </Button>
          <a className="btn btn-secondary btn-sm" href={`${api.defaults.baseURL}/api/export/work_queue.csv`} target="_blank" rel="noreferrer">
            Export CSV
          </a>
        </div>
      </div>

      <div className="stats-grid work-queue-stats-grid">
        {spotlightStats.map((stat) => (
          <button
            key={stat.key}
            type="button"
            className={`card stat-card work-queue-stat ${filter === stat.key ? 'work-queue-stat-active' : ''}`}
            onClick={() => setFilter(stat.key)}
          >
            <div className="stat-label">{stat.label}</div>
            <div className="stat-value">{stat.value}</div>
            <div className="stat-subtitle">{stat.subtitle}</div>
          </button>
        ))}
      </div>

      <Card title="Desk Controls">
        <div className="work-queue-toolbar">
          <div className="quote-follow-up-summary">
            {DESK_FILTERS.map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`quote-filter-chip ${filter === value ? 'quote-filter-active' : ''}`}
                onClick={() => setFilter(value)}
              >
                {label} {value === 'all' ? filterCounts.all || 0 : filterCounts[value] || 0}
              </button>
            ))}
          </div>
          <label className="inline-checkbox">
            <input type="checkbox" checked={hideCompleted} onChange={(event) => setHideCompleted(event.target.checked)} />
            Hide completed
          </label>
        </div>
      </Card>

      {selectedOpportunityIds.length > 0 ? (
        <Card title="Selected Work">
          <div className="work-queue-selected-bar">
            <div>
              <div className="row-title">
                {selectedOpportunityIds.length} selected
              </div>
              <div className="panel-subtitle">{selectedSummary || 'Selected work items are ready for action.'}</div>
            </div>
            <div className="work-queue-selected-actions">
              <Button size="sm" onClick={handleBulkPrepare} loading={bulkPrepareMutation.isPending}>
                Prepare Workspace
              </Button>
              <Button size="sm" variant="secondary" onClick={handleMarkReviewed} loading={markReviewedMutation.isPending}>
                Mark Reviewed
              </Button>
              <Button size="sm" variant="secondary" onClick={handleRefreshIntelligence} loading={refreshIntelligenceMutation.isPending}>
                Refresh Intelligence
              </Button>
              <Button size="sm" variant="secondary" onClick={() => setSelectedOpportunityIds([])}>
                Clear Selection
              </Button>
            </div>
          </div>
        </Card>
      ) : null}

      {(queueTodayResult || collectionSummary.tracked_total || backgroundJobQuery.data) ? (
        <Card title="Collection Activity">
          <div className="work-queue-activity-grid">
            {queueTodayResult ? (
              <div className="settings-summary-box">
                <div className="row-title">Latest queue run</div>
                <div className="row-subtitle">
                  Queued {queueTodayResult.queued_count || 0}
                  {' | '}
                  Skipped {queueTodayResult.skipped_duplicate_count || 0}
                  {' | '}
                  Considered {queueTodayResult.queueable_items || 0}
                </div>
              </div>
            ) : null}
            <div className="settings-summary-box">
              <div className="row-title">Background jobs</div>
              <div className="row-subtitle">
                Queued {collectionSummary.queued || 0}
                {' | '}
                Running {collectionSummary.running || 0}
                {' | '}
                Completed {collectionSummary.completed || 0}
                {' | '}
                Failed {collectionSummary.failed || 0}
              </div>
              {backgroundJobQuery.data ? (
                <div className="panel-subtitle">
                  Latest job: {String(backgroundJobQuery.data.status || '').toUpperCase()}
                  {backgroundJobQuery.data.progress?.current_label ? ` | ${backgroundJobQuery.data.progress.current_label}` : ''}
                </div>
              ) : null}
            </div>
          </div>
        </Card>
      ) : null}

      <Card title="My Work">
        {visibleCards.length === 0 ? (
          <EmptyState
            title="No work items match this view"
            subtitle="Try another filter or refresh the queue."
          />
        ) : (
          <div className="work-queue-sections">
            {DESK_SECTIONS.filter((section) => !(hideCompleted && section === 'done') && (filter === 'all' || filter === section)).map((section) => {
              const sectionCards = cardsBySection[section] || []
              if (sectionCards.length === 0) return null
              return (
                <section key={section} className="work-queue-section">
                  <div className="work-queue-section-header">
                    <div>
                      <div className="row-title">{DESK_LABELS[section]}</div>
                      <div className="panel-subtitle">{DESK_SUBTITLES[section]}</div>
                    </div>
                    <Badge label={`${sectionCards.length}`} variant="default" />
                  </div>
                  <div className="work-queue-list">
                    {sectionCards.map((card, index) => {
                      const item = card.item
                      const queueState = item.queue_state || {}
                      const actionMeta = primaryActionMeta(item)
                      const recommendedAction = recommendedActionLink(item)
                      const isRunning = String(card.statusLabel || '').toUpperCase() === 'RUNNING'
                      const progress = queueState.progress?.percent
                      const group = card.group
                      const opportunityId = getOpportunityIdFromCard(card)
                      const isSelected = opportunityId ? selectedOpportunityIds.includes(opportunityId) : false
                      const contextTitle = group?.opportunity?.title || item.opportunity?.title || item.title
                      const contextMeta = compactMeta([
                        item.opportunity?.source,
                        item.meta?.nsn,
                        item.opportunity?.solicitation_number,
                        item.opportunity?.agency,
                        item.meta?.company_name,
                      ])
                      const explanation = [
                        item.subtitle,
                        item.readiness?.summary || '',
                        isRunning && queueState.progress?.current_label ? queueState.progress.current_label : '',
                        card.kind === 'failed' ? (queueState.error || 'Collection job failed and needs attention.') : '',
                      ].filter(Boolean).join(' | ')
                      const secondaryText = group?.additionalItems?.length
                        ? `Also needs attention: ${group.additionalItems.map((entry) => TYPE_LABELS[entry.type] || entry.type).join(', ')}.`
                        : ''
                      return (
                        <div
                          key={`${card.kind}-${item.id}-${index}`}
                          className={`work-queue-item work-queue-${String(item.priority || '').toLowerCase()} work-queue-item-spotlight ${isSelected ? 'work-queue-item-selected' : ''}`}
                        >
                          <div className="work-queue-item-select">
                            {opportunityId ? (
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelection(card)}
                                aria-label={`Select ${contextTitle}`}
                              />
                            ) : null}
                          </div>
                          <div className="work-queue-item-main">
                            <div className="work-queue-item-header">
                              <Badge label={card.statusLabel} variant={card.kind === 'failed' ? 'error' : (isRunning ? 'warning' : (PRIORITY_VARIANT[item.priority] || 'default'))} />
                              <Badge label={DESK_LABELS[card.deskStatus]} variant="info" />
                              <Badge label={TYPE_LABELS[item.type] || item.type} variant="default" />
                              {item.due_at ? <span className="row-subtitle">Due {formatDate(item.due_at)}</span> : null}
                              {isRunning && progress !== undefined ? <span className="row-subtitle">{progress}%</span> : null}
                            </div>
                            <div className="row-title">{contextTitle}</div>
                            <div className="panel-subtitle">{explanation || actionMeta.detail}</div>
                            <div className="row-subtitle">{contextMeta}</div>
                            <div className="work-queue-next-step">
                              <div className="row-title">{actionMeta.heading}</div>
                              <div className="panel-subtitle">
                                {[actionMeta.detail, item.readiness?.next_actions?.[0]].filter(Boolean).join(' | ')}
                              </div>
                            </div>
                            {secondaryText ? <div className="panel-subtitle">{secondaryText}</div> : null}
                          </div>
                          <div className="work-queue-actions">
                            <Link className="btn btn-sm" to={recommendedAction.to}>
                              {recommendedAction.label}
                            </Link>
                            {card.kind === 'failed' && ['AWARDEE_ENRICHMENT_READY', 'NSN_INTELLIGENCE_REFRESH'].includes(item.type) ? (
                              <Button
                                variant="secondary"
                                size="sm"
                                onClick={() => queueBackgroundMutation.mutate(item)}
                              >
                                Retry Failed Job
                              </Button>
                            ) : null}
                            <Link className="row-subtitle" to={item.action_url}>
                              Open workspace
                            </Link>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </Card>
    </div>
  )
}
