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

function normalizeStatus(status) {
  return String(status || 'Unknown')
    .trim()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
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
