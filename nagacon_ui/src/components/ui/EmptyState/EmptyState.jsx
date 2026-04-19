export default function EmptyState({ title = 'No data', subtitle = '', action = null, icon = null }) {
  return (
    <div className="empty-state">
      {icon ? <div className="empty-state-icon">{icon}</div> : null}
      <div className="empty-state-title">{title}</div>
      {subtitle ? <div className="empty-state-subtitle">{subtitle}</div> : null}
      {action ? <div className="empty-state-action">{action}</div> : null}
    </div>
  )
}
