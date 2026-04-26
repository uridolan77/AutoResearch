import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClientProvider } from '@tanstack/react-query'
import { ErrorBoundary } from 'react-error-boundary'
import { Toaster } from 'sonner'
import App from './App'
import { queryClient } from './api/queryClient'
import './index.css'

function RootCrashFallback() {
  return (
    <div className="crash-shell">
      <div className="crash-card">
        <p className="eyebrow">Render failure</p>
        <h1>The frontend hit an unrecoverable error.</h1>
        <p className="muted">Reload the page after checking the browser console.</p>
        <button type="button" className="button button-primary" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary FallbackComponent={RootCrashFallback}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ErrorBoundary>
      <Toaster position="bottom-right" richColors />
    </QueryClientProvider>
  </React.StrictMode>,
)