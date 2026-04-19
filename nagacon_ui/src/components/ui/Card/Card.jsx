export default function Card({ title, children, className = '' }) {
  return (
    <div className={`card ${className}`}>
      {title ? <div className="card-title">{title}</div> : null}
      <div className="card-body">{children}</div>
    </div>
  )
}
