export default function TableActions({ actions = [] }) {
  return (
    <div className="table-actions">
      {actions.map((action, idx) => (
        <button
          key={idx}
          className={`action-btn ${action.variant || 'primary'}`}
          onClick={action.onClick}
          disabled={action.disabled}
          title={action.title}
        >
          {action.label}
        </button>
      ))}
    </div>
  )
}
