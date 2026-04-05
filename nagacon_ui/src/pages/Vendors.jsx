import { useState } from 'react'
import { api } from '../api/client'

export default function Vendors() {
  const [form, setForm] = useState({ naics_code: '621910', keywords: 'medical, transportation', awarding_agency: 'JUSTICE, DEPARTMENT OF', page: 1, limit: 5 })
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  async function runSearch(e) {
    e.preventDefault()
    setError('')
    try {
      const payload = { ...form, keywords: form.keywords.split(',').map(x => x.trim()).filter(Boolean), page: Number(form.page), limit: Number(form.limit) }
      const res = await api.post('/api/vendors/usaspending/search', payload)
      setData(res.data)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Vendor search failed')
    }
  }

  return (
    <div className="page">
      <h1 className="page-title">Vendor Intelligence</h1>
      <div className="card">
        <form className="form-grid" onSubmit={runSearch}>
          <input value={form.naics_code} onChange={e => setForm({ ...form, naics_code: e.target.value })} placeholder="NAICS" />
          <input value={form.awarding_agency} onChange={e => setForm({ ...form, awarding_agency: e.target.value })} placeholder="Awarding agency" />
          <input value={form.keywords} onChange={e => setForm({ ...form, keywords: e.target.value })} placeholder="Comma-separated keywords" />
          <button className="action-btn" type="submit">Search USAspending</button>
        </form>
        {error ? <p className="error">{error}</p> : null}
      </div>
      <div className="card">
        <h2>Results</h2>
        {!data ? <p>Run a vendor search.</p> : (
          <table className="data-table">
            <thead><tr><th>Name</th><th>Award Amount</th><th>Agency</th><th>Award ID</th></tr></thead>
            <tbody>
              {(data.results || []).map((row, idx) => (
                <tr key={idx}><td>{row.name || '-'}</td><td>{row.award_amount || '-'}</td><td>{row.awarding_agency || '-'}</td><td>{row.award_id || '-'}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
