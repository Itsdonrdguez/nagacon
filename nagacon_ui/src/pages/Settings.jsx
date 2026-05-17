import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Button, EmptyState, Input, LoadingState, StatusPill } from '../components/ui'

export default function Settings() {
  const queryClient = useQueryClient()
  const [externalApiKeysCsv, setExternalApiKeysCsv] = useState('')
  const [pdfDownloadPath, setPdfDownloadPath] = useState('')
  const [masterCatalogExportPath, setMasterCatalogExportPath] = useState('')
  const [providerForm, setProviderForm] = useState({
    sam_api_key: '',
    openai_api_key: '',
    openai_model: 'gpt-4o-mini',
    smtp_host: '',
    smtp_port: '',
    smtp_from_email: '',
  })

  const integrationSettingsQuery = useQuery({
    queryKey: ['integration-settings'],
    queryFn: async () => {
      const res = await api.get('/api/settings/integrations')
      return res.data
    },
    retry: 1,
  })

  const providerSettingsQuery = useQuery({
    queryKey: ['provider-settings'],
    queryFn: async () => {
      const res = await api.get('/api/settings/providers')
      return res.data
    },
    retry: 1,
  })

  useEffect(() => {
    if (integrationSettingsQuery.data) {
      setExternalApiKeysCsv('')
      setPdfDownloadPath(integrationSettingsQuery.data.pdf_download_path || '')
      setMasterCatalogExportPath(integrationSettingsQuery.data.master_catalog_export_path || '')
    }
  }, [integrationSettingsQuery.data])

  useEffect(() => {
    if (providerSettingsQuery.data) {
      setProviderForm({
        sam_api_key: '',
        openai_api_key: '',
        openai_model: providerSettingsQuery.data.openai_model || 'gpt-4o-mini',
        smtp_host: providerSettingsQuery.data.smtp_host || '',
        smtp_port: providerSettingsQuery.data.smtp_port || '',
        smtp_from_email: providerSettingsQuery.data.smtp_from_email || '',
      })
    }
  }, [providerSettingsQuery.data])

  const saveIntegrationMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.put('/api/settings/integrations', payload)
      return res.data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['integration-settings'], data)
      queryClient.invalidateQueries({ queryKey: ['integration-settings'] })
    },
  })

  const saveProviderMutation = useMutation({
    mutationFn: async (payload) => {
      const res = await api.put('/api/settings/providers', payload)
      return res.data
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['provider-settings'], data)
      queryClient.invalidateQueries({ queryKey: ['provider-settings'] })
    },
  })

  const exportNowMutation = useMutation({
    mutationFn: async () => {
      const res = await api.post('/api/settings/integrations/master-catalog/export-now')
      return res.data
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['integration-settings'] })
      queryClient.invalidateQueries({ queryKey: ['work-queue-today'] })
      queryClient.setQueryData(['integration-settings'], (current) => ({
        ...(current || {}),
        ...data,
      }))
    },
  })

  const isLoading = integrationSettingsQuery.isLoading || providerSettingsQuery.isLoading
  const queryError = integrationSettingsQuery.error || providerSettingsQuery.error
  const currentOrg = providerSettingsQuery.data?.organization || integrationSettingsQuery.data?.organization || null

  if (isLoading) {
    return (
      <div className="page">
        <Card>
          <LoadingState label="Loading settings..." />
        </Card>
      </div>
    )
  }

  if (queryError) {
    return (
      <div className="page">
        <EmptyState
          title="Settings unavailable"
          subtitle={queryError.message || 'Could not load settings.'}
          action={<Button onClick={() => {
            integrationSettingsQuery.refetch()
            providerSettingsQuery.refetch()
          }}>Retry</Button>}
        />
      </div>
    )
  }

  return (
    <div className="page">
      <h1 className="page-title">Settings</h1>

      {currentOrg ? (
        <Card title="Organization Context">
          <div className="settings-summary-box">
            <div className="row-title">{currentOrg.name}</div>
            <div className="row-subtitle">{currentOrg.slug}</div>
          </div>
        </Card>
      ) : null}

      <Card title="Personal Provider Settings">
        <div className="company-form">
          <div className="panel-subtitle">
            These credentials are intended to belong to the signed-in user, so each operator can use their own OpenAI, SAM, and outbound email configuration.
          </div>
          <div className="settings-status-grid">
            <div className="settings-summary-box">
              <div className="row-title">SAM</div>
              <StatusPill status={providerSettingsQuery.data?.sam_configured ? 'Configured' : 'Missing'} />
              <div className="row-subtitle">
                Source: {providerSettingsQuery.data?.sam_api_key_source || 'missing'}
              </div>
            </div>
            <div className="settings-summary-box">
              <div className="row-title">OpenAI</div>
              <StatusPill status={providerSettingsQuery.data?.openai_configured ? 'Configured' : 'Missing'} />
            </div>
            <div className="settings-summary-box">
              <div className="row-title">SMTP</div>
              <StatusPill status={providerSettingsQuery.data?.smtp_configured ? 'Configured' : 'Missing'} />
            </div>
          </div>

          <div className="company-form-grid">
            <Input
              label="SAM API Key"
              value={providerForm.sam_api_key}
              onChange={(event) => setProviderForm((current) => ({ ...current, sam_api_key: event.target.value }))}
              placeholder={providerSettingsQuery.data?.sam_configured ? 'Configured. Enter a new key to replace it.' : 'SAM-...'}
            />
            <Input
              label="OpenAI API Key"
              value={providerForm.openai_api_key}
              onChange={(event) => setProviderForm((current) => ({ ...current, openai_api_key: event.target.value }))}
              placeholder={providerSettingsQuery.data?.openai_configured ? 'Configured. Enter a new key to replace it.' : 'sk-...'}
            />
            <Input
              label="OpenAI Model"
              value={providerForm.openai_model}
              onChange={(event) => setProviderForm((current) => ({ ...current, openai_model: event.target.value }))}
              placeholder="gpt-4o-mini"
            />
            <Input
              label="SMTP Host"
              value={providerForm.smtp_host}
              onChange={(event) => setProviderForm((current) => ({ ...current, smtp_host: event.target.value }))}
              placeholder="smtp.example.com"
            />
            <Input
              label="SMTP Port"
              value={providerForm.smtp_port}
              onChange={(event) => setProviderForm((current) => ({ ...current, smtp_port: event.target.value }))}
              placeholder="587"
            />
            <Input
              label="SMTP From Email"
              value={providerForm.smtp_from_email}
              onChange={(event) => setProviderForm((current) => ({ ...current, smtp_from_email: event.target.value }))}
              placeholder="noreply@company.com"
            />
          </div>

          <div className="company-form-actions">
            <Button
              loading={saveProviderMutation.isPending}
              onClick={() => saveProviderMutation.mutate(providerForm)}
            >
              Save Personal Provider Settings
            </Button>
            <Button
              variant="secondary"
              loading={saveProviderMutation.isPending}
              onClick={() => saveProviderMutation.mutate({ ...providerForm, sam_api_key: '', clear_sam_api_key: true })}
            >
              Clear Saved SAM Key
            </Button>
            {saveProviderMutation.data ? <span className="form-success">Personal provider settings saved.</span> : null}
            {saveProviderMutation.error ? <span className="form-error">{saveProviderMutation.error.message || 'Failed to save provider settings.'}</span> : null}
          </div>
          <div className="panel-subtitle">
            Secret values are hidden after saving. Leave a key blank to keep the current value.
          </div>
          <div className="panel-subtitle">
            If SAM enrichment starts returning unauthorized errors, clearing the saved SAM key will make local mode fall back to the backend environment key when one is configured.
          </div>
          <div className="panel-subtitle">
            Recommended low-cost starting model for NagaCon agent tests: <code>gpt-4o-mini</code>
          </div>
        </div>
      </Card>

      <Card title="External API Access">
        <div className="company-form">
          <div className="panel-subtitle">
            Add one or more external API keys here to allow outside systems to call the protected
            {' '}
            <code>/api/integrations/*</code>
            {' '}
            endpoints using the
            {' '}
            <code>X-API-Key</code>
            {' '}
            header.
          </div>
          <div className="company-form-stack">
            <label className="textarea-label" htmlFor="external_api_keys_csv">External API Keys</label>
            <textarea
              id="external_api_keys_csv"
              className="textarea-field"
              value={externalApiKeysCsv}
              onChange={(event) => setExternalApiKeysCsv(event.target.value)}
              placeholder={integrationSettingsQuery.data?.configured ? 'Configured keys are hidden. Enter replacement keys to rotate them.' : 'key-one, key-two, key-three'}
            />
            <div className="panel-subtitle">
              Use commas to separate multiple keys. Leave blank to keep existing keys.
            </div>
          </div>
          <div className="company-form-grid">
            <Input
              label="PDF Download Path"
              value={pdfDownloadPath}
              onChange={(event) => setPdfDownloadPath(event.target.value)}
              placeholder="C:\\NagaCon\\pdfs"
            />
            <Input
              label="Master Catalog Export Path"
              value={masterCatalogExportPath}
              onChange={(event) => setMasterCatalogExportPath(event.target.value)}
              placeholder="C:\\NagaCon\\exports\\master_catalog.csv"
            />
          </div>
          <div className="panel-subtitle">
            Set a local folder where opportunity PDFs and notice files should be downloaded. Leave blank to use the default local storage root.
          </div>
          <div className="panel-subtitle">
            The master catalog export keeps an updatable flat file of FSC, NSN, vendor, and part number records using the best CAGE-enriched vendor names we have.
          </div>
          <div className="company-form-actions">
            <Button
              loading={saveIntegrationMutation.isPending}
              onClick={() => saveIntegrationMutation.mutate({
                external_api_keys_csv: externalApiKeysCsv,
                pdf_download_path: pdfDownloadPath,
                master_catalog_export_path: masterCatalogExportPath,
              })}
            >
              Save Integration Settings
            </Button>
            <Button
              variant="secondary"
              loading={saveIntegrationMutation.isPending}
              onClick={() => saveIntegrationMutation.mutate({ external_api_keys_csv: externalApiKeysCsv, pdf_download_path: '', clear_pdf_download_path: true })}
            >
              Clear PDF Download Path
            </Button>
            <Button
              variant="secondary"
              loading={saveIntegrationMutation.isPending}
              onClick={() => saveIntegrationMutation.mutate({
                external_api_keys_csv: externalApiKeysCsv,
                master_catalog_export_path: '',
                clear_master_catalog_export_path: true,
              })}
            >
              Clear Catalog Export Path
            </Button>
            <Button
              variant="secondary"
              loading={exportNowMutation.isPending}
              onClick={() => exportNowMutation.mutate()}
            >
              Export Now
            </Button>
            {saveIntegrationMutation.data ? <span className="form-success">Integration settings saved.</span> : null}
            {saveIntegrationMutation.error ? <span className="form-error">{saveIntegrationMutation.error.message || 'Failed to save external API keys.'}</span> : null}
            {exportNowMutation.data?.master_catalog_export_status?.written ? (
              <span className="form-success">Master catalog export updated.</span>
            ) : null}
            {exportNowMutation.data?.master_catalog_export_status && !exportNowMutation.data?.master_catalog_export_status?.written ? (
              <span className="form-error">
                {exportNowMutation.data.master_catalog_export_status.reason === 'path_not_configured'
                  ? 'Set a catalog export path before exporting.'
                  : 'Master catalog export did not complete.'}
              </span>
            ) : null}
            {exportNowMutation.error ? <span className="form-error">{exportNowMutation.error.message || 'Failed to export master catalog.'}</span> : null}
          </div>
          <div className="settings-summary-box">
            <div className="row-title">Current status</div>
            <div className="row-subtitle">
              {integrationSettingsQuery.data?.configured
                ? `${integrationSettingsQuery.data.external_api_key_count || 0} external API key(s) configured.`
                : 'No external API keys configured yet.'}
            </div>
            <div className="row-subtitle">
              PDF download path: {integrationSettingsQuery.data?.pdf_download_path || 'Using default local storage root'}
            </div>
            <div className="row-subtitle">
              Master catalog export: {integrationSettingsQuery.data?.master_catalog_export_path || 'Not configured'}
            </div>
            <div className="row-subtitle">
              Catalog status: {integrationSettingsQuery.data?.master_catalog_export_last_status || 'Unknown'}
              {integrationSettingsQuery.data?.master_catalog_export_last_reason
                ? ` | ${integrationSettingsQuery.data.master_catalog_export_last_reason}`
                : ''}
            </div>
            <div className="row-subtitle">
              Last catalog attempt: {integrationSettingsQuery.data?.master_catalog_export_last_attempted_at || 'Never'}
            </div>
            <div className="row-subtitle">
              Last catalog write: {integrationSettingsQuery.data?.master_catalog_export_last_written_at || 'Never'} | Rows: {integrationSettingsQuery.data?.master_catalog_export_last_row_count || 0}
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
