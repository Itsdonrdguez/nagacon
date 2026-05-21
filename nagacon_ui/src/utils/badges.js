const normalizeSetAside = (setAsideType) => {
  const text = String(setAsideType || '').trim()
  if (!text) return ''

  const upper = text.toUpperCase().replace(/[\s-]+/g, '_')
  if (upper === 'EIGHT_A' || /\b8\s*\(?A\)?\b/i.test(text)) return 'EIGHT_A'
  if (upper === 'EDWOSB' || /EDWOSB|ECONOMICALLY DISADVANTAGED WOMEN/i.test(text)) return 'EDWOSB'
  if (upper === 'WOSB' || /WOMEN-OWNED|WOMAN-OWNED/i.test(text)) return 'WOSB'
  if (upper === 'HUBZONE' || /HUB\s*ZONE/i.test(text)) return 'HUBZONE'
  if (upper === 'SDVOSB' || /SERVICE[-\s]*DISABLED VETERAN/i.test(text)) return 'SDVOSB'
  if (upper === 'VOSB' || /VETERAN[-\s]*OWNED/i.test(text)) return 'VOSB'
  if (upper === 'SMALL_BUSINESS' || /SMALL BUSINESS|TOTAL SMALL/i.test(text)) return 'SMALL_BUSINESS'
  if (upper === 'COMBINED' || /COMBINED/i.test(text)) return 'COMBINED'
  if (upper === 'UNRESTRICTED' || /FULL AND OPEN|NOT SET ASIDE|UNRESTRICTED/i.test(text)) return 'UNRESTRICTED'
  return upper
}

export const setAsideBadgeVariant = (setAsideType) => {
  if (!setAsideType) return 'default'

  const type = normalizeSetAside(setAsideType)
  if (type === 'EIGHT_A') return 'success'
  if (type === 'SDVOSB' || type === 'VOSB') return 'warning'
  if (type === 'WOSB' || type === 'EDWOSB') return 'info'
  if (type === 'HUBZONE') return 'success'
  if (type === 'SMALL_BUSINESS') return 'warning'
  if (type === 'UNRESTRICTED') return 'default'
  return 'default'
}

export const setAsideBadgeLabel = (setAsideType) => {
  if (!setAsideType) return null

  const type = normalizeSetAside(setAsideType)
  if (type === 'EIGHT_A') return '8(a)'
  if (type === 'EDWOSB') return 'EDWOSB'
  if (type === 'WOSB') return 'WOSB'
  if (type === 'HUBZONE') return 'HUBZone'
  if (type === 'SDVOSB') return 'SDVOSB'
  if (type === 'VOSB') return 'Veteran-Owned'
  if (type === 'SMALL_BUSINESS') return 'Small Business'
  if (type === 'COMBINED') return 'Combined Set-Aside'
  if (type === 'UNRESTRICTED') return 'Full and Open'
  return String(setAsideType).replace(/\s+/g, ' ').trim()
}

export const setAsideIcon = (setAsideType) => {
  if (!setAsideType) return ''

  const type = normalizeSetAside(setAsideType)
  if (type === 'EIGHT_A') return '8A'
  if (type === 'SDVOSB') return 'SDVOSB'
  if (type === 'EDWOSB') return 'EDWOSB'
  if (type === 'WOSB') return 'WOSB'
  if (type === 'HUBZONE') return 'HUB'
  if (type === 'VOSB') return 'VOSB'
  if (type === 'SMALL_BUSINESS') return 'SB'
  if (type === 'UNRESTRICTED') return 'OPEN'
  return 'SET'
}

export const setAsideOptionLabel = (setAsideType) => setAsideBadgeLabel(setAsideType) || setAsideType

export const sourceIcon = (source) => {
  if (source === 'SAM') return 'SAM'
  if (source === 'DIBBS') return 'DIBBS'
  return ''
}
