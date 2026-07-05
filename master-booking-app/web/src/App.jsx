import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Calendar from './pages/Calendar.jsx'
import Settings from './pages/Settings.jsx'
import ClientBook from './pages/ClientBook.jsx'
import Superadmin from './pages/superadmin/Superadmin.jsx'
import PaymentResult from './pages/PaymentResult.jsx'
import './styles/globals.css'

export default function App() {
  const isSuperadmin = window.location.pathname === '/superadmin'
  const appBackground = isSuperadmin
    ? 'linear-gradient(180deg, #fffaf0 0%, #f7f3ea 48%, #f5f7fb 100%)'
    : 'var(--color-bg)'
  return (
    <BrowserRouter>
      <div className="min-h-screen" style={{ background: appBackground }}>
        <main className={`${isSuperadmin ? 'max-w-[1680px]' : 'max-w-6xl'} mx-auto px-8 py-8 max-md:px-4 max-md:py-4 max-md:pb-24`}>
          <Routes>
            <Route path="/" element={<Navigate to="/calendar" replace />} />
            <Route path="/calendar" element={<Calendar />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/call" element={<ClientBook />} />
            <Route path="/payment-result" element={<PaymentResult />} />
            <Route path="/superadmin" element={<Superadmin />} />
          </Routes>
        </main>
        <TGAuthIndicator />
      </div>
    </BrowserRouter>
  )
}

function TGAuthIndicator() {
  const [authUser, setAuthUser] = useState(null)
  const [isDemoMode, setIsDemoMode] = useState(false)
  const [isVk, setIsVk] = useState(false)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const isDemo = params.get('demo') === '1'
    setIsDemoMode(isDemo)

    let resolvedUser = null
    let vkMode = false

    const userParam = params.get('user')
    const vkUserParam = params.get('vk_user')
      || (params.get('auth_source') === 'vk' && userParam ? String(Math.abs(parseInt(userParam, 10))) : null)
      || (userParam && parseInt(userParam, 10) < 0 ? String(Math.abs(parseInt(userParam, 10))) : null)
    const nameParam = params.get('name')

    if (vkUserParam) {
      vkMode = true
      resolvedUser = {
        id: parseInt(vkUserParam, 10),
        first_name: repairMojibake(nameParam || 'Пользователь ВКонтакте'),
      }
    } else if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp.initDataUnsafe?.user
      if (tg) resolvedUser = tg
    }

    if (!vkUserParam) {
      const usernameParam = params.get('username')
      if (userParam && !resolvedUser) {
        if (userParam.startsWith('{')) {
          try {
            resolvedUser = JSON.parse(decodeURIComponent(userParam))
          } catch {}
        } else {
          resolvedUser = {
            id: parseInt(userParam, 10),
            first_name: nameParam || 'Пользователь',
            username: usernameParam || null
          }
        }
      }
    }

    setIsVk(vkMode)
    setAuthUser(resolvedUser)
  }, [])

  if (!authUser && !isDemoMode) return null

  const displayName = authUser?.first_name
    ? `${authUser.first_name}${authUser.last_name ? ' ' + authUser.last_name : ''}`
    : null
  const displayId = isVk
    ? (authUser?.id ? `VK ID: ${authUser.id}` : null)
    : (authUser?.username ? `@${authUser.username}` : (authUser ? 'логин не указан' : null))
  const authLabel = isVk ? 'Авторизация через ВКонтакте' : 'Авторизация через Telegram'

  return (
    <div className="pointer-events-none md:fixed md:bottom-4 md:right-4 md:z-40 max-md:flex max-md:justify-end max-md:px-4 max-md:pb-4">
      <div className="flex flex-col items-end gap-1.5 px-3 py-2 rounded-xl shadow-lg backdrop-blur-sm max-md:gap-1 max-md:px-2.5 max-md:py-1.5" style={{ backgroundColor: 'rgba(31, 31, 35, 0.86)', border: '1px solid var(--color-border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: authUser ? 'var(--color-success)' : 'var(--color-warning)' }} />
          <span className="text-[10px] font-medium max-md:text-[9px]" style={{ color: 'var(--color-text-muted)' }}>{authLabel}</span>
        </div>
        <div className="text-[11px] max-md:text-[10px]" style={{ color: 'var(--color-text-secondary)' }}>
          {displayName || 'Гость'} {displayName && displayId ? ' | ' : ''} {displayId || ''}
        </div>
      </div>
    </div>
  )
}

function repairMojibake(value) {
  if (!value || !/[РС][^\s]?/.test(value)) return value
  try {
    const decoder1251 = new TextDecoder('windows-1251')
    const reverse1251 = new Map()
    for (let byte = 0; byte < 256; byte += 1) {
      reverse1251.set(decoder1251.decode(Uint8Array.of(byte)), byte)
    }
    const bytes = Uint8Array.from(value, char => {
      const byte = reverse1251.get(char)
      if (byte === undefined) throw new Error('not cp1251')
      return byte
    })
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
    return (decoded.match(/[РС]/g) || []).length < (value.match(/[РС]/g) || []).length ? decoded : value
  } catch {
    return value
  }
}
