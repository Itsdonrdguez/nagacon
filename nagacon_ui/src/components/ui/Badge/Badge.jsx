import './Badge.css'

const Badge = ({
  label,
  variant = 'default',
  size = 'sm',
  className = ''
}) => {
  const variantClass = `badge-${variant}`
  const sizeClass = `badge-${size}`

  return (
    <span className={`badge ${variantClass} ${sizeClass} ${className}`}>
      {label}
    </span>
  )
}

export default Badge
