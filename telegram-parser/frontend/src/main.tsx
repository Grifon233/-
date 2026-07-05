import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter as Router } from 'react-router-dom'
import App from './App'
import './index.css'

// Global error handler for catching React errors
window.addEventListener('error', (event) => {
  console.error('[GLOBAL ERROR]', event.error?.message || event.message, event.error?.stack)
})

window.addEventListener('unhandledrejection', (event) => {
  console.error('[UNHANDLED REJECTION]', event.reason)
})

const VITE_PRELOAD_RETRY_KEY = 'vite-preload-error-retry'

window.setTimeout(() => {
  sessionStorage.removeItem(VITE_PRELOAD_RETRY_KEY)
}, 5000)

window.addEventListener('vite:preloadError', (event) => {
  event.preventDefault()
  if (sessionStorage.getItem(VITE_PRELOAD_RETRY_KEY) === '1') {
    sessionStorage.removeItem(VITE_PRELOAD_RETRY_KEY)
    return
  }
  sessionStorage.setItem(VITE_PRELOAD_RETRY_KEY, '1')
  window.location.reload()
})

console.log('[APP] Starting Telegram Comb frontend...')

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Router>
      <App />
    </Router>
  </React.StrictMode>,
)
