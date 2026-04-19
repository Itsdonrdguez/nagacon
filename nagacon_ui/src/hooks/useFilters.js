// hooks/useFilters.js
import { useState, useCallback } from 'react'

export const useFilters = (initialFilters = {}) => {
  const [filters, setFilters] = useState(initialFilters)

  const updateFilter = useCallback((key, value) => {
    setFilters(prev => ({ ...prev, [key]: value }))
  }, [])

  const clearFilter = useCallback((key) => {
    setFilters(prev => {
      const newFilters = { ...prev }
      delete newFilters[key]
      return newFilters
    })
  }, [])

  const clearAllFilters = useCallback(() => {
    setFilters(initialFilters)
  }, [initialFilters])

  const hasActiveFilters = Object.keys(filters).some(key =>
    filters[key] !== initialFilters[key] && filters[key] !== '' && filters[key] !== null
  )

  return {
    filters,
    updateFilter,
    clearFilter,
    clearAllFilters,
    hasActiveFilters,
    setFilters
  }
}