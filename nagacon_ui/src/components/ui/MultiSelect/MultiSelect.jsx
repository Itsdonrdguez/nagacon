import { useEffect, useMemo, useRef, useState } from 'react'
import './MultiSelect.css'

function normalizeDefault(value) {
  return String(value || '').trim()
}

export default function MultiSelect({
  label,
  value = [],
  options = [],
  onChange,
  helperText,
  placeholder = 'Search codes',
  emptyText = 'No matching options',
  allowCustom = false,
  customTypeLabel = 'code',
  normalizeValue = normalizeDefault,
  disabled = false,
}) {
  const wrapperRef = useRef(null)
  const [isOpen, setIsOpen] = useState(false)
  const [search, setSearch] = useState('')

  useEffect(() => {
    function handlePointerDown(event) {
      if (!wrapperRef.current?.contains(event.target)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handlePointerDown)
    return () => document.removeEventListener('mousedown', handlePointerDown)
  }, [])

  const normalizedValue = useMemo(
    () => (value || []).map((item) => normalizeValue(item)).filter(Boolean),
    [value, normalizeValue],
  )

  const selectedSet = useMemo(() => new Set(normalizedValue), [normalizedValue])

  const filteredOptions = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return options
    return options.filter((option) => {
      const searchText = String(option.searchText || `${option.value} ${option.label}`).toLowerCase()
      return searchText.includes(query)
    })
  }, [options, search])

  const customValue = useMemo(() => normalizeValue(search), [search, normalizeValue])
  const canAddCustom = allowCustom && customValue && !options.some((option) => option.value === customValue) && !selectedSet.has(customValue)

  const selectedSummary = useMemo(() => {
    if (!normalizedValue.length) return 'Select one or more'
    if (normalizedValue.length <= 3) return normalizedValue.join(', ')
    return `${normalizedValue.length} selected`
  }, [normalizedValue])

  function updateSelection(nextSelected) {
    onChange?.(nextSelected)
  }

  function toggleOption(optionValue) {
    const normalized = normalizeValue(optionValue)
    if (!normalized) return
    if (selectedSet.has(normalized)) {
      updateSelection(normalizedValue.filter((item) => item !== normalized))
      return
    }
    updateSelection([...normalizedValue, normalized])
  }

  function addCustomOption() {
    if (!canAddCustom) return
    updateSelection([...normalizedValue, customValue])
    setSearch('')
  }

  function addCustomValuesFromInput(rawValue) {
    const nextValues = String(rawValue || '')
      .split(/[,\n;]+/)
      .map((item) => normalizeValue(item))
      .filter(Boolean)

    if (!nextValues.length) return false

    const knownOptionValues = new Set(options.map((option) => option.value))
    const merged = [...normalizedValue]
    let changed = false

    nextValues.forEach((nextValue) => {
      if (selectedSet.has(nextValue)) return
      if (knownOptionValues.has(nextValue)) {
        merged.push(nextValue)
        changed = true
        return
      }
      if (allowCustom) {
        merged.push(nextValue)
        changed = true
      }
    })

    if (!changed) return false
    updateSelection(merged)
    setSearch('')
    return true
  }

  function handleSearchKeyDown(event) {
    if (event.key === 'Enter') {
      if (addCustomValuesFromInput(search)) {
        event.preventDefault()
      }
    }
  }

  function handleSearchPaste(event) {
    if (!allowCustom) return
    const pastedText = event.clipboardData?.getData('text') || ''
    if (!/[,\n;]/.test(pastedText)) return
    if (addCustomValuesFromInput(pastedText)) {
      event.preventDefault()
    }
  }

  return (
    <div className="multi-select-wrapper" ref={wrapperRef}>
      {label ? <label className="input-label">{label}</label> : null}
      <button
        type="button"
        className={`multi-select-trigger ${isOpen ? 'open' : ''}`}
        onClick={() => !disabled && setIsOpen((current) => !current)}
        disabled={disabled}
      >
        <span className={normalizedValue.length ? 'multi-select-value' : 'multi-select-placeholder'}>
          {normalizedValue.length ? selectedSummary : 'Select one or more'}
        </span>
        <span className="multi-select-chevron">{isOpen ? '^' : 'v'}</span>
      </button>
      {isOpen ? (
        <div className="multi-select-panel">
          <input
            className="multi-select-search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={handleSearchKeyDown}
            onPaste={handleSearchPaste}
            placeholder={placeholder}
            autoFocus
          />
          {allowCustom ? (
            <div className="multi-select-instruction">
              Type one or more {customTypeLabel}s separated by commas, then press Enter to add them.
            </div>
          ) : null}
          <div className="multi-select-options">
            {filteredOptions.map((option) => {
              const checked = selectedSet.has(option.value)
              return (
                <label key={option.value} className={`multi-select-option ${checked ? 'selected' : ''}`}>
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleOption(option.value)}
                  />
                  <span className="multi-select-option-text">
                    <span className="multi-select-option-label">{option.label}</span>
                    {option.description ? <span className="multi-select-option-subtitle">{option.description}</span> : null}
                  </span>
                </label>
              )
            })}
            {canAddCustom ? (
              <button type="button" className="multi-select-custom" onClick={addCustomOption}>
                Add {customValue} as a custom {customTypeLabel}
              </button>
            ) : null}
            {!filteredOptions.length && !canAddCustom ? <div className="multi-select-empty">{emptyText}</div> : null}
          </div>
        </div>
      ) : null}
      {helperText ? <span className="input-helper-text">{helperText}</span> : null}
    </div>
  )
}
