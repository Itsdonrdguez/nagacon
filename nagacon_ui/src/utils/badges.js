export const setAsideBadgeVariant = (setAsideType) => {
  if (!setAsideType) return 'default'

  const type = setAsideType.toLowerCase()
  if (type.includes('8(a)') || type.includes('8a')) return 'success'
  if (type.includes('sdvosb')) return 'warning'
  if (type.includes('wosb')) return 'info'
  if (type.includes('small')) return 'warning'
  return 'default'
}

export const setAsideBadgeLabel = (setAsideType) => {
  if (!setAsideType) return null

  return setAsideType
    .replace(/Service-Disabled Veteran-Owned Small Business/i, 'SDVOSB')
    .replace(/Women-Owned Small Business/i, 'WOSB')
    .replace(/Small Business/i, 'SB')
    .replace(/\s+/g, ' ')
    .trim()
}

export const setAsideIcon = (setAsideType) => {
  if (!setAsideType) return ''

  const type = setAsideType.toLowerCase()
  if (type.includes('8(a)') || type.includes('8a')) return '8A'
  if (type.includes('sdvosb')) return 'SDVOSB'
  if (type.includes('wosb')) return 'WOSB'
  if (type.includes('small')) return 'SB'
  return 'SET'
}

export const sourceIcon = (source) => {
  if (source === 'SAM') return 'SAM'
  if (source === 'DIBBS') return 'DIBBS'
  return ''
}
