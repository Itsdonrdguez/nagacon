import './StatusPill.css'

const STATUS_VARIANTS = {
  active: 'success',
  completed: 'success',
  won: 'success',
  ready: 'success',
  submitted: 'success',
  open: 'info',
  new: 'info',
  research: 'info',
  pending: 'warning',
  partial_success: 'warning',
  due: 'warning',
  draft: 'warning',
  not_requested: 'default',
  on_hold: 'default',
  lost: 'error',
  closed: 'error',
  blocked: 'error',
  not_bid: 'error',
}

const STATUS_LABELS = {
  partial_success: 'Needs Attention',
  in_progress: 'In Progress',
  no_bid: 'No Bid',
  not_bid: 'No Bid',
  not_requested: 'Not Requested',
}

function normalizeStatus(status) {
  const raw = String(status || 'Unknown')
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
  const key = raw.toLowerCase().replace(/\s+/g, '_')
  if (STATUS_LABELS[key]) return STATUS_LABELS[key]
  return raw.replace(/\b\w+/g, (word) => {
    const upper = word.toUpperCase()
    if (['NSN', 'NAICS', 'FSC', 'PSC', 'PDF', 'RFQ', 'DIBBS', 'SAM', 'CAGE'].includes(upper)) return upper
    return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
  })
}

function variantForStatus(status) {
  const key = normalizeStatus(status).toLowerCase().replace(/\s+/g, '_')
  return STATUS_VARIANTS[key] || 'default'
}

export default function StatusPill({ status, className = '' }) {
  const label = normalizeStatus(status)
  const variant = variantForStatus(status)

  return (
    <span className={`status-pill status-pill-${variant} ${className}`.trim()}>
      {label}
    </span>
  )
}
