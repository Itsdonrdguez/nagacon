import { forwardRef } from 'react'
import './Table.css'

const Table = forwardRef(({
  children,
  className = '',
  ...props
}, ref) => {
  return (
    <div className="table-container">
      <table
        ref={ref}
        className={`table ${className}`}
        {...props}
      >
        {children}
      </table>
    </div>
  )
})

Table.displayName = 'Table'

const TableHeader = ({ children, className = '', ...props }) => (
  <thead className={`table-header ${className}`} {...props}>
    {children}
  </thead>
)

const TableBody = ({ children, className = '', ...props }) => (
  <tbody className={`table-body ${className}`} {...props}>
    {children}
  </tbody>
)

const TableRow = ({ children, className = '', onClick, ...props }) => (
  <tr
    className={`table-row ${onClick ? 'table-row-clickable' : ''} ${className}`}
    onClick={onClick}
    {...props}
  >
    {children}
  </tr>
)

const TableHead = ({ children, sortable = false, sortDirection, onSort, className = '', ...props }) => (
  <th
    className={`table-head ${sortable ? 'table-head-sortable' : ''} ${className}`}
    onClick={sortable ? onSort : undefined}
    {...props}
  >
    <div className="table-head-content">
      {children}
      {sortable && sortDirection && (
        <span className="table-sort-indicator">
          {sortDirection === 'asc' ? 'asc' : 'desc'}
        </span>
      )}
    </div>
  </th>
)

const TableCell = ({ children, className = '', ...props }) => (
  <td className={`table-cell ${className}`} {...props}>
    {children}
  </td>
)

export {
  Table,
  TableHeader,
  TableBody,
  TableRow,
  TableHead,
  TableCell
}
