// components/ui/Input/Input.jsx
import { forwardRef } from 'react'
import './Input.css'

const Input = forwardRef(({
  label,
  error,
  helperText,
  fullWidth = false,
  size = 'md',
  className = '',
  ...props
}, ref) => {
  const inputClasses = [
    'input',
    `input-${size}`,
    error && 'input-error',
    fullWidth && 'input-full-width',
    className
  ].filter(Boolean).join(' ')

  return (
    <div className="input-wrapper">
      {label && (
        <label className="input-label">
          {label}
        </label>
      )}
      <input
        ref={ref}
        className={inputClasses}
        {...props}
      />
      {error && <span className="input-error-text">{error}</span>}
      {helperText && !error && <span className="input-helper-text">{helperText}</span>}
    </div>
  )
})

Input.displayName = 'Input'

export default Input