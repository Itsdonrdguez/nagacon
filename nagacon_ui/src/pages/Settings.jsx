import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Card, Button, EmptyState, Input, LoadingState, StatusPill } from '../components/ui'

export default function Settings() {
  const queryClient = useQueryClient()
  const [externalApiKeysCsv, setExternalApiKeysCsv] = useState('')
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
      setExternalApiKeysCsv(integrationSettingsQuery.data.external_api_keys_csv || '')
    }
  }, [integrationSettingsQuery.data])

  useEffect(() => {
    if (providerSettingsQuery.data) {
      setProviderForm({
        sam_api_key: providerSettingsQuery.data.sam_api_key || '',
        openai_api_key: providerSettingsQuery.data.openai_api_key || '',
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

      <Card title="Provider Settings">
        <div className="company-form">
          <div className="settings-status-grid">
            <div className="settings-summary-box">
              <div className="row-title">SAM</div>
              <StatusPill status={providerSettingsQuery.data?.sam_configured ? 'Configured' : 'Missing'} />
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
              placeholder="SAM-..."
            />
            <Input
              label="OpenAI API Key"
              value={providerForm.openai_api_key}
              onChange={(event) => setProviderForm((current) => ({ ...current, openai_api_key: event.target.value }))}
              placeholder="sk-..."
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
              Save Provider Settings
            </Button>
            {saveProviderMutation.data ? <span className="form-success">Provider settings saved.</span> : null}
            {saveProviderMutation.error ? <span className="form-error">{saveProviderMutation.error.message || 'Failed to save provider settings.'}</span> : null}
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
              placeholder="key-one, key-two, key-three"
            />
            <div className="panel-subtitle">
              Use commas to separate multiple keys.
            </div>
          </div>
          <div className="company-form-actions">
            <Button
              loading={saveIntegrationMutation.isPending}
              onClick={() => saveIntegrationMutation.mutate({ external_api_keys_csv: externalApiKeysCsv })}
            >
              Save External API Keys
            </Button>
            {saveIntegrationMutation.data ? <span className="form-success">External API keys saved.</span> : null}
            {saveIntegrationMutation.error ? <span className="form-error">{saveIntegrationMutation.error.message || 'Failed to save external API keys.'}</span> : null}
          </div>
          <div className="settings-summary-box">
            <div className="row-title">Current status</div>
            <div className="row-subtitle">
              {integrationSettingsQuery.data?.configured
                ? `${(integrationSettingsQuery.data.external_api_keys || []).length} external API key(s) configured.`
                : 'No external API keys configured yet.'}
            </div>
          </div>
        </div>
      </Card>
    </div>
  )
}
