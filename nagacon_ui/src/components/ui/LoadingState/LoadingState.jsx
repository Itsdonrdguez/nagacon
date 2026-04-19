import './LoadingState.css'

export default function LoadingState({ label = 'Loading...' }) {
  return (
    <div className="loading-state" role="status" aria-live="polite">
      <div className="loading-state-spinner" />
      <div className="loading-state-label">{label}</div>
    </div>
  )
}
