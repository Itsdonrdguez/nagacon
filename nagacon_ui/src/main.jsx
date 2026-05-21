import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider, NotificationProvider } from './contexts'
import App from './App'
import LoadingState from './components/ui/LoadingState/LoadingState'
import './styles.css'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Login = lazy(() => import('./pages/Login'))
const WorkQueue = lazy(() => import('./pages/WorkQueue'))
const Opportunities = lazy(() => import('./pages/Opportunities'))
const Workspace = lazy(() => import('./pages/Workspace'))
const Vendors = lazy(() => import('./pages/Vendors'))
const Providers = lazy(() => import('./pages/Providers'))
const NSNIntelligence = lazy(() => import('./pages/NSNIntelligence'))
const PublogReference = lazy(() => import('./pages/PublogReference'))
const Company = lazy(() => import('./pages/Company'))
const Ingestion = lazy(() => import('./pages/Ingestion'))
const Pipeline = lazy(() => import('./pages/Pipeline'))
const Settings = lazy(() => import('./pages/Settings'))
const SourceFreshness = lazy(() => import('./pages/SourceFreshness'))
const DataHealth = lazy(() => import('./pages/DataHealth'))
const LOCAL_MODE = String(import.meta.env.VITE_LOCAL_MODE ?? 'true').toLowerCase() !== 'false'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
    },
  },
})

function PageFallback() {
  return (
    <div className="page">
      <LoadingState label="Loading page..." />
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <NotificationProvider>
          <BrowserRouter>
            <Suspense fallback={<PageFallback />}>
              <Routes>
                <Route path="/login" element={LOCAL_MODE ? <Navigate to="/" replace /> : <Login />} />
                <Route path="/" element={<App />}>
                  <Route index element={<Dashboard />} />
                  <Route path="work-queue" element={<WorkQueue />} />
                  <Route path="company" element={<Company />} />
                  <Route path="ingestion" element={<Ingestion />} />
                  <Route path="opportunities" element={<Opportunities />} />
                  <Route path="pipeline" element={<Pipeline />} />
                  <Route path="settings" element={<Settings />} />
                  <Route path="data-health" element={<DataHealth />} />
                  <Route path="source-freshness" element={<SourceFreshness />} />
                  <Route path="workspace/:id" element={<Workspace />} />
                  <Route path="vendors" element={<Vendors />} />
                  <Route path="providers" element={<Providers />} />
                  <Route path="nsn-intelligence" element={<NSNIntelligence />} />
                  <Route path="publog-reference" element={<PublogReference />} />
                </Route>
              </Routes>
            </Suspense>
          </BrowserRouter>
        </NotificationProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>
)
