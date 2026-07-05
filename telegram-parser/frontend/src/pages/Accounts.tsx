import { useState, useEffect, useRef, forwardRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  ArrowsClockwise,
  Trash,
  Upload,
  X,
  UserCircle,
  Phone,
  Key,
  CaretDown,
  Funnel,
  MagnifyingGlass,
  DotsThree,
  Power,
  Pulse,
  ShieldCheck,
  Warning,
  XCircle,
  GlobeHemisphereWest,
  Folder,
  FileArchive,
  CircleNotch,
  CheckCircle,
  GenderMale,
  GenderFemale,
  Question,
  Users,
  User,
  TextT,
  Image,
  Link,
  PaperPlaneTilt,
  Television,
  Lightning,
  Wallet
} from '@phosphor-icons/react'
import { ProfileEditor } from '../components/ProfileEditor'

interface Account {
  id: number
  phone_number: string
  status: string
  folder?: string
  gender?: 'male' | 'female' | 'unknown'
  warmup_level?: number
  warmup_phase?: number | null
  warmup_locked?: boolean
  daily_dm_count?: number
  proxy_id?: number
  proxy_country?: string | null
  note?: string | null
  has_session: boolean
  session_string?: string
  created_at: string
  first_name?: string | null
  last_name?: string | null
  bio?: string | null
  username?: string | null
  avatar_path?: string | null
  personal_channel_id?: number | null
  personal_channel_username?: string | null
  health_factors?: {
    restriction?: { reason?: string; at?: string }
    spambot?: { status: string; until?: string | null; permanent?: boolean; checked_at?: string }
  } | null
}

const genderConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  male: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: GenderMale, label: 'Мужской' },
  female: { color: 'text-pink-600', bg: 'bg-pink-500/10', icon: GenderFemale, label: 'Женский' },
  unknown: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Question, label: 'Неизвестно' },
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  production: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: Power, label: 'Активен' },
  warming: { color: 'text-amber-600', bg: 'bg-amber-500/10', icon: Pulse, label: 'Прогрев' },
  new: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: UserCircle, label: 'Новый' },
  restricted: { color: 'text-amber-700', bg: 'bg-amber-500/10', icon: Warning, label: 'Сбой сессии' },
  banned: { color: 'text-red-600', bg: 'bg-red-500/10', icon: XCircle, label: 'Заблокирован' },
  offline: { color: 'text-muted-foreground', bg: 'bg-muted', icon: ShieldCheck, label: 'Оффлайн' },
}

const StatusBadge = forwardRef<HTMLSpanElement, { status: string }>(({ status }, ref) => {
  const config = statusConfig[status] || statusConfig.offline
  const Icon = config.icon

  return (
    <span ref={ref} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      <Icon size={12} weight="bold" />
      {config.label}
    </span>
  )
})

const isInPhaseWarmup = (account: Account) =>
  account.warmup_phase !== null &&
  account.warmup_phase !== undefined &&
  account.warmup_phase < 4

const effectiveStatus = (account: Account) =>
  isInPhaseWarmup(account) ? 'warming' : account.status

// Live progress phases for the auto-registration job → icon + colour.
const autoPhaseUI: Record<string, { color: string; label: string }> = {
  starting:        { color: 'text-blue-600',    label: 'Запуск' },
  ordering:        { color: 'text-blue-600',    label: 'Заказ номера' },
  number_received: { color: 'text-blue-600',    label: 'Номер получен' },
  sending_code:    { color: 'text-blue-600',    label: 'Отправка кода' },
  waiting_code:    { color: 'text-amber-600',   label: 'Ожидание кода' },
  retrying:        { color: 'text-amber-600',   label: 'Повтор' },
  logging_in:      { color: 'text-blue-600',    label: 'Вход' },
  done:            { color: 'text-emerald-600', label: 'Готово' },
  failed:          { color: 'text-red-600',     label: 'Ошибка' },
  cancelled:       { color: 'text-muted-foreground', label: 'Остановлено' },
}

function AddAccountModal({ isOpen, onClose, onSuccess, resumeBatch, onBatchStarted }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  resumeBatch?: number[] | null
  onBatchStarted?: (ids: number[]) => void
}) {
  const [mode, setMode] = useState<'auto' | 'manual'>('auto')
  const [step, setStep] = useState<'form' | 'sms' | 'auto'>('form')
  const [formData, setFormData] = useState({ phone_number: '', api_id: '', api_hash: '' })
  const [proxyId, setProxyId] = useState<number | ''>('')
  const [proxies, setProxies] = useState<{id: number, host: string, port: number, country?: string | null, max_accounts?: number | null, account_count?: number}[]>([])
  const [createdAccountId, setCreatedAccountId] = useState<number | null>(null)
  const [phoneCodeHash, setPhoneCodeHash] = useState('')
  const [codeDigits, setCodeDigits] = useState(['', '', '', '', ''])
  const [password2FA, setPassword2FA] = useState('')
  const [need2FA, setNeed2FA] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const digitRefs = useRef<(HTMLInputElement | null)[]>([])
  const resumeBatchRef = useRef(resumeBatch)
  useEffect(() => { resumeBatchRef.current = resumeBatch }, [resumeBatch])

  // Auto-registration (SMSFAST) state
  const [smsBalance, setSmsBalance] = useState<number | null>(null)
  const [smsConfigured, setSmsConfigured] = useState(true)
  const [smsCountries, setSmsCountries] = useState<{id: number, name: string}[]>([])
  const [countryOverride, setCountryOverride] = useState<number | ''>('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [count, setCount] = useState(1)
  const [autoAccountIds, setAutoAccountIds] = useState<number[]>([])
  const [autoJobs, setAutoJobs] = useState<Record<number, any>>({})
  const [now, setNow] = useState(Date.now())

  // Remaining capacity of the selected proxy (max_accounts − used).
  // Unlimited proxies are softly capped at 10 per batch.
  const selectedProxy = proxies.find(p => p.id === proxyId)
  const proxyRemaining = selectedProxy
    ? (selectedProxy.max_accounts == null
        ? 10
        : Math.max(1, (selectedProxy.max_accounts) - (selectedProxy.account_count ?? 0)))
    : 1
  // Keep the chosen count within the selected proxy's capacity.
  useEffect(() => {
    setCount(c => Math.min(Math.max(1, c), proxyRemaining))
  }, [proxyRemaining])

  useEffect(() => {
    if (isOpen) {
      const rb = resumeBatchRef.current
      if (rb && rb.length > 0) {
        setAutoAccountIds(rb)
        setAutoJobs({})
        setStep('auto')
      } else {
        setMode('auto')
        setStep('form')
        setError('')
        setProxyId('')
        setCountryOverride('')
        setShowAdvanced(false)
        setCount(1)
        setAutoAccountIds([])
        setAutoJobs({})
        setCodeDigits(['', '', '', '', ''])
        setPassword2FA('')
        setNeed2FA(false)
        setFormData({ phone_number: '', api_id: '', api_hash: '' })
      }
      api.get('/api/v1/proxies').then(r => {
        setProxies(r.data
          .map((p: any) => ({ ...p, max_accounts: normalizeProxyMaxAccounts(p) }))
          .filter((p: any) =>
            p.use_for_accounts !== false &&
            p.is_active !== false &&
            proxyHasFreeSlot(p.account_count ?? 0, p.max_accounts)
          ))
      }).catch(() => {})
      api.get('/api/v1/accounts/sms-balance').then(r => {
        setSmsConfigured(r.data.configured !== false)
        setSmsBalance(r.data.balance ?? null)
      }).catch(() => { setSmsConfigured(false) })
      api.get('/api/v1/accounts/sms-countries').then(r => {
        setSmsCountries(r.data.countries || [])
      }).catch(() => {})
    }
  }, [isOpen])

  // Poll every auto-registration job while the batch runs.
  useEffect(() => {
    if (step !== 'auto' || autoAccountIds.length === 0) return
    let stop = false
    let sawDone = false
    const tick = async () => {
      const results = await Promise.all(autoAccountIds.map(async (id) => {
        try {
          const r = await api.get(`/api/v1/accounts/${id}/auto-register/job`)
          return r.data?.exists ? [id, r.data] as const : null
        } catch { return null }
      }))
      if (stop) return
      setAutoJobs(prev => {
        const next = { ...prev }
        for (const item of results) if (item) next[item[0]] = item[1]
        return next
      })
      // Refresh the account list once when any job first reaches "done".
      if (!sawDone && results.some(it => it && it[1].phase === 'done')) {
        sawDone = true
        onSuccess()
      }
    }
    tick()
    const id = setInterval(tick, 2000)
    return () => { stop = true; clearInterval(id) }
  }, [step, autoAccountIds])

  // 1-second ticker so the "осталось MM:SS" countdown updates smoothly.
  useEffect(() => {
    if (step !== 'auto') return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [step])

  const handleAutoStart = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (!proxyId) {
      setError('Выберите прокси — номер заказывается в стране прокси')
      return
    }
    setSubmitting(true)
    try {
      const body: Record<string, unknown> = { proxy_id: proxyId, count }
      if (countryOverride) body.country_id = countryOverride
      if (showAdvanced && formData.api_id.trim()) body.api_id = Number(formData.api_id)
      if (showAdvanced && formData.api_hash.trim()) body.api_hash = formData.api_hash.trim()
      const res = await api.post('/api/v1/accounts/auto-register', body)
      const ids: number[] = res.data.account_ids || (res.data.account_id ? [res.data.account_id] : [])
      const jobs: any[] = res.data.jobs || (res.data.job ? [res.data.job] : [])
      setAutoAccountIds(ids)
      const initial: Record<number, any> = {}
      ids.forEach((id, i) => { initial[id] = jobs[i] || {} })
      setAutoJobs(initial)
      setStep('auto')
    } catch (e: any) {
      const detail = e.response?.data?.detail
      if (typeof detail === 'string') setError(detail)
      else if (Array.isArray(detail) && detail.length > 0)
        setError(detail.map((d: any) => `${d.loc?.join('.') ?? ''}: ${d.msg}`).join('; '))
      else setError(e.message || 'Не удалось запустить авто-регистрацию')
    } finally {
      setSubmitting(false)
    }
  }

  const handleAutoStop = async () => {
    await Promise.all(autoAccountIds.map(id =>
      api.post(`/api/v1/accounts/${id}/auto-register/stop`).catch(() => {})
    ))
  }

  // Close a finished/failed batch: drop each job on the server and delete
  // leftover "pending_" shells so the floating process banner doesn't
  // resurrect from a failed registration. Then clear local batch state.
  const handleAutoFinish = async () => {
    await Promise.all(autoAccountIds.map(id =>
      api.post(`/api/v1/accounts/${id}/auto-register/dismiss`).catch(() => {})
    ))
    onBatchStarted?.([])
    onSuccess()
    onClose()
  }

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!proxyId) {
      setError('Выберите прокси — аккаунт без прокси создать нельзя')
      return
    }
    const phone = formData.phone_number.trim()
    if (!/^\+\d{7,15}$/.test(phone)) {
      setError('Номер телефона должен быть в формате E.164: + и 7-15 цифр')
      return
    }
    // api_id / api_hash are OPTIONAL now — when left blank the backend
    // uses the global Telegram app credentials. Validate only if filled.
    const apiIdRaw = formData.api_id.trim()
    const apiHashRaw = formData.api_hash.trim()
    let apiIdNum: number | undefined
    if (apiIdRaw) {
      apiIdNum = Number(apiIdRaw)
      if (!Number.isFinite(apiIdNum) || !Number.isInteger(apiIdNum) || apiIdNum <= 0) {
        setError('API ID должен быть положительным целым числом (или оставьте пустым)')
        return
      }
    }
    if (apiHashRaw && !/^[0-9a-fA-F]{32}$/.test(apiHashRaw)) {
      setError('API Hash должен состоять из 32 hex-символов (или оставьте пустым)')
      return
    }

    setSubmitting(true)
    try {
      const payload: Record<string, unknown> = { phone_number: phone, proxy_id: proxyId }
      if (apiIdNum) payload.api_id = apiIdNum
      if (apiHashRaw) payload.api_hash = apiHashRaw
      const createRes = await api.post('/api/v1/accounts', payload)
      const newId = createRes.data.id
      setCreatedAccountId(newId)

      // Immediately request SMS code via the new account+proxy
      const codeRes = await api.post(`/api/v1/accounts/${newId}/send-code`)
      setPhoneCodeHash(codeRes.data.phone_code_hash)
      setStep('sms')
    } catch (e: any) {
      const detail = e.response?.data?.detail
      if (typeof detail === 'string') setError(detail)
      else if (Array.isArray(detail) && detail.length > 0)
        setError(detail.map((d: any) => `${d.loc?.join('.') ?? ''}: ${d.msg}`).join('; '))
      else setError(e.message || 'Не удалось создать аккаунт')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDigit = (idx: number, val: string) => {
    if (!/^\d?$/.test(val)) return
    const newDigits = [...codeDigits]
    newDigits[idx] = val
    setCodeDigits(newDigits)
    if (val && idx < 4) digitRefs.current[idx + 1]?.focus()
  }

  const handleDigitKeyDown = (idx: number, e: React.KeyboardEvent) => {
    if (e.key === 'Backspace' && !codeDigits[idx] && idx > 0)
      digitRefs.current[idx - 1]?.focus()
  }

  const handleLogin = async () => {
    const code = codeDigits.join('')
    if (code.length < 5) { setError('Введите все 5 цифр кода'); return }
    if (!createdAccountId) return
    setError('')
    setSubmitting(true)
    try {
      await api.post(`/api/v1/accounts/${createdAccountId}/login`, {
        code,
        phone_code_hash: phoneCodeHash,
        ...(need2FA ? { password: password2FA } : {}),
      })
      setFormData({ phone_number: '', api_id: '', api_hash: '' })
      onSuccess()
      onClose()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      if (typeof detail === 'string' && detail.includes('SESSION_PASSWORD_NEEDED')) {
        setNeed2FA(true)
        setError('Требуется пароль двухфакторной аутентификации')
      } else {
        setError(typeof detail === 'string' ? detail : 'Не удалось войти — проверьте код')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: 'spring', stiffness: 300, damping: 30 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-lg"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <div>
                <h2 className="text-xl font-semibold">Добавить аккаунт</h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {step === 'auto'
                    ? 'Автоматическая регистрация номера'
                    : step === 'sms'
                    ? 'Шаг 2 из 2 — код из SMS'
                    : mode === 'auto'
                    ? 'Авто-заказ номера через SMSFAST'
                    : 'Ручной ввод данных аккаунта'}
                </p>
              </div>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
              >
                <X size={20} />
              </button>
            </div>

            {step === 'form' ? (
              <div className="p-6 space-y-5">
                {/* Mode toggle: auto (SMSFAST) vs manual */}
                <div className="grid grid-cols-2 gap-2 p-1 bg-muted/50 rounded-2xl">
                  <button
                    type="button"
                    onClick={() => { setMode('auto'); setError('') }}
                    className={`flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all ${
                      mode === 'auto' ? 'bg-card shadow-sm text-primary' : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    <Lightning size={16} weight={mode === 'auto' ? 'fill' : 'regular'} />
                    Автоматически
                  </button>
                  <button
                    type="button"
                    onClick={() => { setMode('manual'); setError('') }}
                    className={`flex items-center justify-center gap-2 py-2.5 rounded-xl text-sm font-medium transition-all ${
                      mode === 'manual' ? 'bg-card shadow-sm text-primary' : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    <Phone size={16} weight={mode === 'manual' ? 'fill' : 'regular'} />
                    Вручную
                  </button>
                </div>

                {error && (
                  <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">{error}</p>
                )}

                {mode === 'auto' ? (
                  /* ─── AUTO: order a number via SMSFAST ─── */
                  <form onSubmit={handleAutoStart} className="space-y-5">
                    {!smsConfigured && (
                      <p className="text-sm text-amber-600 bg-amber-500/10 px-4 py-2 rounded-lg">
                        SMS-сервис не настроен (нет SMSFAST_API_TOKEN). Авто-регистрация недоступна.
                      </p>
                    )}

                    {/* SMS balance */}
                    <div className="flex items-center justify-between px-4 py-3 rounded-xl bg-primary/5 border border-primary/15">
                      <span className="text-sm font-medium flex items-center gap-2">
                        <Wallet size={16} className="text-primary" />
                        Баланс SMSFAST
                      </span>
                      <span className="text-sm font-semibold tabular-nums">
                        {smsBalance != null ? `${smsBalance.toFixed(2)} ₽` : '—'}
                      </span>
                    </div>

                    {/* Proxy selector — required */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <GlobeHemisphereWest size={16} />
                        Прокси <span className="text-red-500">*</span>
                      </label>
                      {proxies.length === 0 ? (
                        <p className="text-sm text-amber-600 bg-amber-500/10 px-4 py-2 rounded-lg">
                          Нет доступных прокси. Сначала добавьте прокси на странице «Прокси».
                        </p>
                      ) : (
                        <select
                          value={proxyId}
                          onChange={(e) => setProxyId(e.target.value ? parseInt(e.target.value) : '')}
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                          required
                        >
                          <option value="">— выберите прокси —</option>
                          {proxies.map(p => (
                            <option key={p.id} value={p.id}>
                              #{p.id} · {p.host}:{p.port}{p.country ? ` · ${proxyCountryLabel(p.country)}` : ''} · {p.account_count ?? 0}/{proxyCapacityLabel(p.max_accounts ?? null)}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>

                    {/* Country: auto from proxy or override */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <GlobeHemisphereWest size={16} />
                        Страна номера
                      </label>
                      <select
                        value={countryOverride}
                        onChange={(e) => setCountryOverride(e.target.value ? parseInt(e.target.value) : '')}
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                      >
                        <option value="">— Авто (по стране прокси) —</option>
                        {smsCountries.map(c => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                      <p className="text-xs text-muted-foreground">
                        По умолчанию номер заказывается в той же стране, что и прокси.
                      </p>
                    </div>

                    {/* Count slider — accounts are queued, never purchased in parallel */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center justify-between">
                        <span className="flex items-center gap-2">
                          <Users size={16} />
                          Сколько аккаунтов создать
                        </span>
                        <span className="text-primary font-semibold tabular-nums">{count}</span>
                      </label>
                      <input
                        type="range"
                        value={count}
                        onChange={(e) => setCount(Number(e.target.value))}
                        min={1}
                        max={proxyRemaining}
                        step={1}
                        disabled={!proxyId || proxyRemaining <= 1}
                        className="w-full accent-primary disabled:opacity-50"
                      />
                      <div className="flex justify-between text-xs text-muted-foreground">
                        <span>1</span>
                        <span>
                          {!proxyId
                            ? 'выберите прокси'
                            : selectedProxy?.max_accounts == null
                            ? 'до 10 (лимит прокси не задан)'
                            : `макс ${proxyRemaining} (свободно на прокси)`}
                        </span>
                      </div>
                      <p className="text-xs text-emerald-700 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
                        Безопасная очередь: одновременно оплачивается только один номер.
                        Следующий будет заказан после успешной регистрации либо подтверждённого возврата предыдущего.
                      </p>
                    </div>

                    {/* Advanced: own api_id/api_hash */}
                    <button
                      type="button"
                      onClick={() => setShowAdvanced(v => !v)}
                      className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1"
                    >
                      <CaretDown size={12} className={showAdvanced ? 'rotate-180 transition-transform' : 'transition-transform'} />
                      Продвинутые настройки (свой API ID / Hash)
                    </button>
                    {showAdvanced && (
                      <div className="grid grid-cols-2 gap-4">
                        <input
                          type="number"
                          value={formData.api_id}
                          onChange={(e) => setFormData({ ...formData, api_id: e.target.value })}
                          placeholder="API ID (необяз.)"
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none text-sm"
                        />
                        <input
                          type="text"
                          value={formData.api_hash}
                          onChange={(e) => setFormData({ ...formData, api_hash: e.target.value })}
                          placeholder="API Hash (необяз.)"
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none font-mono text-sm"
                        />
                      </div>
                    )}

                    <div className="flex gap-3 pt-2">
                      <button
                        type="button"
                        onClick={onClose}
                        className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
                      >
                        Отмена
                      </button>
                      <button
                        type="submit"
                        disabled={submitting || proxies.length === 0 || !smsConfigured}
                        className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                      >
                        <Lightning size={18} weight="fill" />
                        {submitting ? 'Запуск...' : count > 1 ? `Поставить в очередь: ${count}` : 'Заказать один номер'}
                      </button>
                    </div>
                  </form>
                ) : (
                  /* ─── MANUAL: enter phone + (optional) api creds ─── */
                  <form onSubmit={handleCreate} className="space-y-5">
                    {/* Proxy selector — required */}
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <GlobeHemisphereWest size={16} />
                        Прокси <span className="text-red-500">*</span>
                      </label>
                      {proxies.length === 0 ? (
                        <p className="text-sm text-amber-600 bg-amber-500/10 px-4 py-2 rounded-lg">
                          Нет доступных прокси. Сначала добавьте прокси на странице «Прокси».
                        </p>
                      ) : (
                        <select
                          value={proxyId}
                          onChange={(e) => setProxyId(e.target.value ? parseInt(e.target.value) : '')}
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                          required
                        >
                          <option value="">— выберите прокси —</option>
                          {proxies.map(p => (
                            <option key={p.id} value={p.id}>
                              #{p.id} · {p.host}:{p.port}{p.country ? ` · ${proxyCountryLabel(p.country)}` : ''} · {p.account_count ?? 0}/{proxyCapacityLabel(p.max_accounts ?? null)}
                            </option>
                          ))}
                        </select>
                      )}
                    </div>

                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <Phone size={16} />
                        Номер телефона
                      </label>
                      <input
                        type="text"
                        value={formData.phone_number}
                        onChange={(e) => setFormData({ ...formData, phone_number: e.target.value })}
                        placeholder="+79001234567"
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                        required
                      />
                    </div>

                    <div className="grid grid-cols-2 gap-4">
                      <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                          <Key size={16} />
                          API ID
                        </label>
                        <input
                          type="number"
                          value={formData.api_id}
                          onChange={(e) => setFormData({ ...formData, api_id: e.target.value })}
                          placeholder="по умолчанию"
                          min="1"
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                        />
                      </div>
                      <div className="space-y-2">
                        <label className="text-sm font-medium flex items-center gap-2">
                          <Key size={16} />
                          API Hash
                        </label>
                        <input
                          type="text"
                          value={formData.api_hash}
                          onChange={(e) => setFormData({ ...formData, api_hash: e.target.value })}
                          placeholder="по умолчанию"
                          className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all font-mono text-sm"
                        />
                      </div>
                    </div>
                    <p className="text-xs text-muted-foreground -mt-3">
                      API ID и Hash можно оставить пустыми — подставятся стандартные. Свои — на <b>my.telegram.org</b>.
                    </p>

                    <div className="flex gap-3 pt-2">
                      <button
                        type="button"
                        onClick={onClose}
                        className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
                      >
                        Отмена
                      </button>
                      <button
                        type="submit"
                        disabled={submitting || proxies.length === 0}
                        className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50"
                      >
                        {submitting ? 'Создание...' : 'Создать и отправить SMS →'}
                      </button>
                    </div>
                  </form>
                )}
              </div>
            ) : step === 'sms' ? (
              <div className="p-6 space-y-6">
                {error && (
                  <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">{error}</p>
                )}

                <div className="text-center space-y-2">
                  <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto">
                    <Phone size={32} className="text-primary" weight="duotone" />
                  </div>
                  <p className="font-semibold">Код отправлен</p>
                  <p className="text-sm text-muted-foreground">
                    Введите 5-значный код из SMS на номер <b>{formData.phone_number}</b>
                  </p>
                </div>

                {/* Digit boxes */}
                <div className="flex justify-center gap-3">
                  {codeDigits.map((digit, idx) => (
                    <input
                      key={idx}
                      ref={(el) => { digitRefs.current[idx] = el }}
                      type="text"
                      inputMode="numeric"
                      maxLength={1}
                      value={digit}
                      onChange={(e) => handleDigit(idx, e.target.value)}
                      onKeyDown={(e) => handleDigitKeyDown(idx, e)}
                      className="w-12 h-14 text-center text-2xl font-bold rounded-xl border-2 border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                    />
                  ))}
                </div>

                {need2FA && (
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Пароль двухфакторной аутентификации</label>
                    <input
                      type="password"
                      value={password2FA}
                      onChange={(e) => setPassword2FA(e.target.value)}
                      placeholder="Пароль 2FA"
                      className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                    />
                  </div>
                )}

                <div className="flex gap-3">
                  <button
                    type="button"
                    onClick={onClose}
                    className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
                  >
                    Отмена
                  </button>
                  <button
                    onClick={handleLogin}
                    disabled={submitting || codeDigits.join('').length < 5}
                    className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50"
                  >
                    {submitting ? 'Вход...' : 'Войти'}
                  </button>
                </div>
              </div>
            ) : (
              /* ─── AUTO progress step (one row per account) ─── */
              (() => {
                const jobList = autoAccountIds.map(id => ({ id, job: autoJobs[id] || {} }))
                const doneCount = jobList.filter(j => j.job.phase === 'done').length
                const failedCount = jobList.filter(j => j.job.phase === 'failed' || j.job.phase === 'cancelled').length
                const activeCount = jobList.length - doneCount - failedCount
                const allFinished = activeCount === 0 && jobList.length > 0
                const countryName = jobList.find(j => j.job.country_name)?.job.country_name

                const fmtCountdown = (deadline?: string) => {
                  if (!deadline) return ''
                  const dl = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(deadline) ? deadline : deadline + 'Z').getTime()
                  const rem = Math.max(0, Math.floor((dl - now) / 1000))
                  return `${Math.floor(rem / 60)}:${String(rem % 60).padStart(2, '0')}`
                }

                return (
                  <div className="p-6 space-y-5">
                    {/* Aggregate header */}
                    <div className="text-center space-y-2">
                      <div className={`w-16 h-16 rounded-2xl flex items-center justify-center mx-auto ${
                        allFinished && failedCount === 0 ? 'bg-emerald-500/10'
                        : allFinished ? 'bg-amber-500/10' : 'bg-primary/10'
                      }`}>
                        {allFinished && failedCount === 0 ? (
                          <CheckCircle size={32} className="text-emerald-600" weight="duotone" />
                        ) : allFinished ? (
                          <Warning size={32} className="text-amber-600" weight="duotone" />
                        ) : (
                          <CircleNotch size={32} className="text-primary animate-spin" weight="bold" />
                        )}
                      </div>
                      <p className="font-semibold">
                        {allFinished
                          ? `Готово: ${doneCount} из ${jobList.length}${failedCount ? `, ошибок ${failedCount}` : ''}`
                          : `Регистрация ${jobList.length} аккаунт(ов)…`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {countryName ? `Страна: ${countryName} · ` : ''}
                        готово {doneCount} · в работе {activeCount}{failedCount ? ` · ошибок ${failedCount}` : ''}
                      </p>
                    </div>

                    {/* Per-account rows */}
                    <div className="space-y-2 max-h-72 overflow-y-auto">
                      {jobList.map(({ id, job }, idx) => {
                        const phase: string = job.phase || 'starting'
                        const ui = autoPhaseUI[phase] || autoPhaseUI.starting
                        const isDone = phase === 'done'
                        const isFailed = phase === 'failed' || phase === 'cancelled'
                        const countdown = phase === 'waiting_code' ? fmtCountdown(job.deadline) : ''
                        return (
                          <div key={id} className="px-3 py-2.5 rounded-xl bg-muted/30 border border-border/40">
                            <div className="flex items-center justify-between gap-2">
                              <span className="flex items-center gap-2 min-w-0">
                                {isDone ? (
                                  <CheckCircle size={16} className="text-emerald-600 shrink-0" weight="fill" />
                                ) : isFailed ? (
                                  <XCircle size={16} className="text-red-600 shrink-0" weight="fill" />
                                ) : (
                                  <CircleNotch size={16} className="text-primary animate-spin shrink-0" />
                                )}
                                <span className="text-sm font-mono truncate">
                                  {job.phone || `#${idx + 1}`}
                                </span>
                              </span>
                              <span className={`text-xs font-medium shrink-0 ${ui.color}`}>
                                {countdown ? `⏳ ${countdown}` : ui.label}
                              </span>
                            </div>
                            {job.message && (
                              <p className={`text-[11px] mt-1 truncate ${isFailed ? 'text-red-500' : 'text-muted-foreground'}`} title={job.message}>
                                {job.message}
                              </p>
                            )}
                          </div>
                        )
                      })}
                    </div>

                    <div className="flex gap-3">
                      {!allFinished ? (
                        <>
                          <button
                            type="button"
                            onClick={handleAutoStop}
                            className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
                          >
                            Остановить всё
                          </button>
                          <button
                            type="button"
                            onClick={() => { onBatchStarted?.(autoAccountIds); onClose() }}
                            className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium text-muted-foreground"
                          >
                            Свернуть
                          </button>
                        </>
                      ) : (
                        <button
                          type="button"
                          onClick={handleAutoFinish}
                          className={`flex-1 py-3 rounded-xl font-medium transition-colors ${
                            failedCount === 0 ? 'bg-primary text-primary-foreground hover:bg-primary/90' : 'border border-border hover:bg-muted'
                          }`}
                        >
                          {failedCount === 0 ? 'Готово' : 'Закрыть'}
                        </button>
                      )}
                    </div>
                    {!allFinished && (
                      <p className="text-[11px] text-muted-foreground text-center">
                        Можно свернуть — регистрация продолжится в фоне.
                      </p>
                    )}
                  </div>
                )
              })()
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function AssignProxyModal({ isOpen, onClose, accountId, phone, onSuccess, currentProxyId }: {
  isOpen: boolean
  onClose: () => void
  accountId: number
  phone: string
  onSuccess: () => void
  currentProxyId?: number | null
}) {
  const [proxies, setProxies] = useState<{id: number, host: string, port: number, country?: string | null, assignedCount: number, maxAccounts: number | null}[]>([])
  const [selectedProxyId, setSelectedProxyId] = useState<number | null>(currentProxyId ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const fetchProxies = async () => {
    try {
      const [proxyResponse, accountResponse] = await Promise.all([
        api.get('/api/v1/proxies'),
        api.get('/api/v1/accounts'),
      ])

      const accountUsage = (accountResponse.data as Account[]).reduce<Record<number, number>>((acc, item) => {
        if (item.proxy_id) acc[item.proxy_id] = (acc[item.proxy_id] || 0) + 1
        return acc
      }, {})

      const available = proxyResponse.data
        .filter((proxy: any) => {
          const assignedCount = accountUsage[proxy.id] || 0
          const maxAcc = normalizeProxyMaxAccounts(proxy)
          return proxy.id === currentProxyId || (
            proxy.use_for_accounts !== false &&
            proxy.is_active !== false &&
            proxyHasFreeSlot(assignedCount, maxAcc)
          )
        })
        .map((proxy: any) => ({
          id: proxy.id,
          host: proxy.host,
          port: proxy.port,
          country: proxy.country,
          assignedCount: accountUsage[proxy.id] || 0,
          maxAccounts: normalizeProxyMaxAccounts(proxy),
        }))

      setProxies(available)
    } catch (error) {
      console.error('Ошибка загрузки прокси:', error)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchProxies()
      setSelectedProxyId(currentProxyId ?? null)
      setError('')
    }
  }, [isOpen, currentProxyId])

  const handleAssign = async () => {
    if (!selectedProxyId) {
      setError('Прокси обязателен — выберите прокси из списка или добавьте новый на странице «Прокси».')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.put(`/api/v1/accounts/${accountId}`, {
        proxy_id: selectedProxyId
      })
      onSuccess()
      onClose()
    } catch (error: any) {
      const detail = error.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось назначить прокси')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold">Назначить прокси</h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <p className="text-sm text-muted-foreground">
                Аккаунт: <b>{phone}</b>
              </p>

              <div className="flex items-start gap-2 p-3 rounded-xl bg-amber-500/10 text-amber-700 text-xs">
                <ShieldCheck size={16} weight="bold" className="shrink-0 mt-0.5" />
                <span>
                  Прокси обязателен. Аккаунт невозможно авторизовать в Telegram без привязанного прокси —
                  это защита от случайного «слива» всех аккаунтов на один IP.
                </span>
              </div>

              {proxies.length === 0 ? (
                <div className="text-sm text-muted-foreground p-4 border border-dashed border-border rounded-xl text-center">
                  Нет доступных прокси. Сначала добавьте прокси на странице <b>«Прокси»</b>.
                </div>
              ) : (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Выберите прокси</label>
                  <select
                    value={selectedProxyId || ''}
                    onChange={(e) => setSelectedProxyId(e.target.value ? parseInt(e.target.value) : null)}
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  >
                    <option value="">— выберите прокси —</option>
                    {proxies.map(proxy => (
                      <option key={proxy.id} value={proxy.id}>
                        #{proxy.id} · {proxy.host}:{proxy.port}
                        {proxy.country ? ` · ${proxy.country}` : ''}
                        {` · ${proxy.assignedCount}/${proxyCapacityLabel(proxy.maxAccounts)}`}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-muted-foreground">
                    Показываются только живые прокси для аккаунтов. Прокси скрывается при достижении лимита аккаунтов.
                  </p>
                </div>
              )}

              {error && (
                <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">
                  {error}
                </p>
              )}

              <div className="flex gap-3 pt-2">
                <button onClick={onClose} className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors">
                  Отмена
                </button>
                <button
                  onClick={handleAssign}
                  disabled={loading || !selectedProxyId || proxies.length === 0}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {loading ? 'Сохранение...' : 'Сохранить'}
                </button>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function AuthorizeModal({ isOpen, onClose, accountId, phone, hasProxy }: {
  isOpen: boolean
  onClose: () => void
  accountId: number
  phone: string
  hasProxy: boolean
}) {
  const [step, setStep] = useState<'code' | 'password'>('code')
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [phoneCodeHash, setPhoneCodeHash] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  // Track whether we've already sent the code for this modal session.
  // Previously the ``useEffect`` re-fired every time ``isOpen`` flipped
  // and there was no flag, which caused duplicate ``send_code`` calls
  // and a confusing UX when the user re-opened the modal.
  const [codeSent, setCodeSent] = useState(false)

  const sendCode = async () => {
    setLoading(true)
    setError('')
    try {
      const res = await api.post(`/api/v1/accounts/${accountId}/send-code`)
      setPhoneCodeHash(res.data.phone_code_hash)
      setStep('code')
      setCodeSent(true)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Ошибка отправки кода')
    } finally {
      setLoading(false)
    }
  }

  const verifyCode = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      await api.post(`/api/v1/accounts/${accountId}/login`, {
        phone_code: code,
        phone_code_hash: phoneCodeHash,
        password: password || undefined,
      })
      onClose()
      window.location.reload()
    } catch (e: any) {
      const detail = e.response?.data?.detail || 'Ошибка проверки кода'
      // 2FA is required → switch the modal into "password" mode and
      // keep the code the user already typed so they don't have to
      // re-enter it.
      if (typeof detail === 'string' && detail.toLowerCase().includes('2fa')) {
        setStep('password')
      }
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (isOpen && !codeSent && !phoneCodeHash) {
      sendCode()
    }
    // Reset internal state when the modal closes so the next open
    // behaves like a fresh session.
    if (!isOpen) {
      setCode('')
      setPassword('')
      setPhoneCodeHash('')
      setError('')
      setStep('code')
      setCodeSent(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen])

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold">
                {step === 'code' ? 'Авторизация аккаунта' : 'Двухфакторная защита'}
              </h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={verifyCode} className="p-6 space-y-4">
              {!hasProxy && (
                <div className="flex items-start gap-2 p-3 rounded-xl bg-red-500/10 text-red-700 text-xs">
                  <XCircle size={16} weight="bold" className="shrink-0 mt-0.5" />
                  <span>
                    К аккаунту <b>не привязан прокси</b>. Сначала назначьте прокси через меню
                    «Назначить прокси», иначе бэкенд откажет в отправке кода.
                  </span>
                </div>
              )}

              {step === 'code' ? (
                <>
                  <p className="text-sm text-muted-foreground">
                    Код отправлен на номер <b>{phone}</b>
                  </p>

                  <input
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="Введите код из Telegram"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all text-center text-2xl tracking-widest font-mono"
                    maxLength={5}
                    required
                    disabled={!hasProxy}
                  />
                </>
              ) : (
                <>
                  <p className="text-sm text-muted-foreground">
                    На аккаунте включена двухфакторная авторизация. Введите пароль
                    облачного Telegram для <b>{phone}</b>.
                  </p>

                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Cloud password"
                    autoComplete="current-password"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all font-mono"
                    required
                    disabled={!hasProxy}
                  />
                </>
              )}

              {error && (
                <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">
                  {error}
                </p>
              )}

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors">
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={loading || !phoneCodeHash || !hasProxy}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  {loading ? 'Проверка...' : step === 'code' ? 'Подтвердить' : 'Войти'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const countryRu: Record<string, string> = {
  ru: 'Россия', us: 'США', ua: 'Украина', kz: 'Казахстан', by: 'Беларусь',
  de: 'Германия', fr: 'Франция', gb: 'Великобритания', nl: 'Нидерланды',
  lv: 'Латвия', lt: 'Литва', ee: 'Эстония', pl: 'Польша', tr: 'Турция',
  ca: 'Канада', id: 'Индонезия',
  se: 'Швеция', fi: 'Финляндия', no: 'Норвегия', dk: 'Дания',
  at: 'Австрия', ch: 'Швейцария', it: 'Италия', es: 'Испания', pt: 'Португалия',
  ro: 'Румыния', bg: 'Болгария', hu: 'Венгрия', cz: 'Чехия', sk: 'Словакия',
  hr: 'Хорватия', rs: 'Сербия', gr: 'Греция', si: 'Словения',
  md: 'Молдова', ge: 'Грузия', am: 'Армения', az: 'Азербайджан',
  uz: 'Узбекистан', tj: 'Таджикистан', kg: 'Кыргызстан', tm: 'Туркменистан',
  jp: 'Япония', kr: 'Юж. Корея', cn: 'Китай', sg: 'Сингапур', hk: 'Гонконг',
  th: 'Таиланд', vn: 'Вьетнам', my: 'Малайзия', ph: 'Филиппины', in: 'Индия',
  au: 'Австралия', nz: 'Новая Зеландия',
  br: 'Бразилия', mx: 'Мексика', ar: 'Аргентина', co: 'Колумбия',
  za: 'ЮАР', ng: 'Нигерия', eg: 'Египет', ma: 'Марокко',
  il: 'Израиль', ae: 'ОАЭ', sa: 'Саудовская Аравия',
  mn: 'Монголия',
}

function proxyCountryLabel(country?: string | null) {
  if (!country) return 'страна неизвестна'
  return countryRu[country.toLowerCase()] || country.toUpperCase()
}

function inferProxyCountry(host: string, country?: string | null) {
  if (country) return country
  if (host === '196.16.110.162' || host === '38.154.19.220') return 'us'
  if (host === '181.177.126.90') return 'lv'
  return null
}

const DEFAULT_PROXY_MAX_ACCOUNTS = 3

function normalizeProxyMaxAccounts(proxy: { max_accounts?: number | string | null }) {
  if (proxy.max_accounts === null) return null
  const value = Number(proxy.max_accounts ?? DEFAULT_PROXY_MAX_ACCOUNTS)
  return Number.isFinite(value) && value > 0 ? value : DEFAULT_PROXY_MAX_ACCOUNTS
}

function proxyHasFreeSlot(assignedCount: number, maxAccounts: number | null) {
  return maxAccounts === null || assignedCount < maxAccounts
}

function proxyCapacityLabel(maxAccounts: number | null) {
  return maxAccounts === null ? '∞' : String(maxAccounts)
}

function TDataImportModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [files, setFiles] = useState<File[]>([])
  const [apiId, setApiId] = useState('')
  const [apiHash, setApiHash] = useState('')
  const [showAdvancedApi, setShowAdvancedApi] = useState(false)
  const [passcode, setPasscode] = useState('')
  const [proxyId, setProxyId] = useState<number | null>(null)
  const [proxies, setProxies] = useState<{ id: number, host: string, port: number, country?: string | null, assignedCount: number, max_accounts: number | null }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [report, setReport] = useState<any>(null)

  const reportFiles = Array.isArray(report?.files) ? report.files : []
  const reportResults = reportFiles.flatMap((item: any) =>
    Array.isArray(item.results)
      ? item.results.map((result: any) => ({ ...result, file: item.file }))
      : []
  )
  const reportErrors = [
    ...(Array.isArray(report?.errors) ? report.errors.map((err: any) => ({ ...err, file: null })) : []),
    ...reportFiles.flatMap((item: any) =>
      Array.isArray(item.errors)
        ? item.errors.map((err: any) => ({ ...err, file: item.file }))
        : []
    ),
  ]

  const fetchProxies = async () => {
    try {
      const [proxyResponse, accountResponse] = await Promise.all([
        api.get('/api/v1/proxies'),
        api.get('/api/v1/accounts'),
      ])
      const usage = accountResponse.data.reduce((acc: Record<number, number>, item: Account) => {
        if (item.proxy_id) acc[item.proxy_id] = (acc[item.proxy_id] || 0) + 1
        return acc
      }, {})
      setProxies(proxyResponse.data
        .map((proxy: any) => ({
          id: proxy.id,
          host: proxy.host,
          port: proxy.port,
          country: inferProxyCountry(proxy.host, proxy.country),
          use_for_accounts: proxy.use_for_accounts,
          is_active: proxy.is_active,
          assignedCount: usage[proxy.id] || 0,
          max_accounts: normalizeProxyMaxAccounts(proxy),
        }))
        .filter((proxy: any) => proxyHasFreeSlot(proxy.assignedCount, proxy.max_accounts) && proxy.country && proxy.use_for_accounts !== false && proxy.is_active !== false)
      )
    } catch (e) {
      console.error('Не удалось загрузить прокси', e)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchProxies()
      setFiles([])
      setPasscode('')
      setShowAdvancedApi(false)
      setError('')
      setReport(null)
    }
  }, [isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (files.length === 0) {
      setError('Выберите один или несколько ZIP/RAR-архивов с tdata')
      return
    }
    const apiIdNum = Number(apiId)
    if (apiId.trim() && (!Number.isFinite(apiIdNum) || apiIdNum <= 0)) {
      setError('API ID должен быть положительным целым числом')
      return
    }
    if (apiHash.trim() && !/^[0-9a-fA-F]{32}$/.test(apiHash.trim())) {
      setError('API Hash — 32 hex-символа с my.telegram.org')
      return
    }
    if (!proxyId) {
      setError('Прокси обязателен — каждый импортированный аккаунт получит этот прокси. Без прокси импорт отклоняется.')
      return
    }

    setSubmitting(true)
    try {
      const reports = []
      for (const selectedFile of files) {
        const formData = new FormData()
        formData.append('file', selectedFile)
        if (apiId.trim()) formData.append('api_id', String(apiIdNum))
        if (apiHash.trim()) formData.append('api_hash', apiHash.trim())
        formData.append('default_proxy_id', String(proxyId))
        if (passcode.trim()) formData.append('passcode', passcode.trim())

        const res = await api.post('/api/v1/accounts/import-tdata', formData, {
          headers: { 'Content-Type': 'multipart/form-data' }
        })
        reports.push({ file: selectedFile.name, ...res.data })
      }
      const imported = reports.reduce((sum, item) => sum + Number(item.imported || 0), 0)
      setReport({ imported, files: reports })
      if (imported > 0) {
        onSuccess()
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось импортировать tdata')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <FileArchive size={22} />
                Импорт TData
              </h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-5">
              <div className="text-xs text-muted-foreground space-y-1">
                <p>
                  Загрузите ZIP/RAR-архив с папкой <code className="font-mono">tdata</code> из
                  <code className="font-mono"> %APPDATA%/Telegram Desktop/tdata</code> (Windows) или
                  <code className="font-mono"> ~/.local/share/Telegram Desktop/tdata</code> (Linux).
                </p>
                <p>
                  Можно выбрать несколько архивов. Один архив также может содержать несколько папок tdata.
                </p>
                <p>
                  Если Telegram Desktop защищён локальным паролем, укажите его ниже.
                  Без него зашифрованный <code className="font-mono">tdata</code> не импортируется.
                </p>
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Архив с tdata</label>
                <input
                  type="file"
                  accept=".zip,.ZIP,.rar,.RAR,application/zip,application/x-zip-compressed,application/vnd.rar"
                  multiple
                  onChange={(e) => setFiles(Array.from(e.target.files || []))}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-medium"
                />
                {files.length > 0 && (
                  <p className="text-xs text-muted-foreground">Выбрано архивов: {files.length}</p>
                )}
              </div>

              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => setShowAdvancedApi(!showAdvancedApi)}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  {showAdvancedApi ? 'Скрыть расширенные настройки' : 'Расширенные настройки API'}
                </button>
                {showAdvancedApi && (
                  <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <label className="text-sm font-medium">API ID</label>
                      <input
                        type="number"
                        value={apiId}
                        onChange={(e) => setApiId(e.target.value)}
                        placeholder="по умолчанию"
                        className="w-full px-3 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none"
                      />
                    </div>
                    <div className="space-y-1 col-span-2">
                      <label className="text-sm font-medium">API Hash</label>
                      <input
                        type="text"
                        value={apiHash}
                        onChange={(e) => setApiHash(e.target.value)}
                        placeholder="по умолчанию"
                        className="w-full px-3 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none font-mono text-sm"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Пароль Telegram Desktop</label>
                <input
                  type="password"
                  value={passcode}
                  onChange={(e) => setPasscode(e.target.value)}
                  placeholder="Если tdata запаролен"
                  className="w-full px-3 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none"
                />
              </div>

              <div className="space-y-1">
                <label className="text-sm font-medium">Прокси по умолчанию</label>
                <select
                  value={proxyId ?? ''}
                  onChange={(e) => setProxyId(e.target.value ? parseInt(e.target.value) : null)}
                  className="w-full px-3 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  required
                >
                  <option value="">— выберите прокси —</option>
                  {proxies.map(p => (
                    <option key={p.id} value={p.id}>
                      #{p.id} · {p.host}:{p.port} · {proxyCountryLabel(p.country)} · {p.assignedCount}/{proxyCapacityLabel(p.max_accounts)}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-muted-foreground">
                  Каждому импортированному аккаунту будет привязан этот прокси.
                </p>
              </div>

              {error && (
                <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">{error}</p>
              )}

              {report && (
                <div className="text-sm bg-emerald-500/10 text-emerald-700 p-3 rounded-xl space-y-1">
                  <p className="flex items-center gap-2 font-medium">
                    <CheckCircle size={16} weight="bold" />
                    Импортировано: {report.imported}
                  </p>
                  {reportResults.length > 0 && (
                    <ul className="text-xs space-y-0.5 list-disc list-inside">
                      {reportResults.slice(0, 10).map((r: any, i: number) => (
                        <li key={i}>
                          {r.file ? `${r.file}: ` : ''}{r.phone_number ?? '—'}{r.user_id ? ` (uid ${r.user_id})` : ''}
                        </li>
                      ))}
                      {reportResults.length > 10 && (
                        <li>и ещё {reportResults.length - 10}…</li>
                      )}
                    </ul>
                  )}
                  {reportErrors.length > 0 && (
                    <details className="text-xs text-amber-700">
                      <summary>Ошибки ({reportErrors.length})</summary>
                      <ul className="list-disc list-inside">
                        {reportErrors.slice(0, 8).map((e: any, i: number) => (
                          <li key={i}>
                            {e.file ? `${e.file}: ` : ''}{e.reason}
                          </li>
                        ))}
                      </ul>
                      {reportErrors.some((e: any) => String(e.reason || '').toLowerCase().includes('password-encrypted')) && (
                        <p className="mt-2">
                          Этот tdata защищён локальным паролем Telegram Desktop. Укажите его в поле “Пароль Telegram Desktop” и повторите импорт.
                        </p>
                      )}
                    </details>
                  )}
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors">
                  Закрыть
                </button>
                <button
                  type="submit"
                  disabled={submitting || files.length === 0 || !proxyId}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting ? <><CircleNotch size={16} className="animate-spin" /> Импорт…</> : 'Импортировать'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function SessionImportModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [sessionFiles, setSessionFiles] = useState<File[]>([])
  const [fileProxies, setFileProxies] = useState<Record<string, number | null>>({})
  const [proxies, setProxies] = useState<{ id: number, host: string, port: number, country?: string | null, assignedCount: number, max_accounts: number | null }[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [results, setResults] = useState<Array<{ file: string, ok: boolean, msg: string }>>([])

  const fetchProxies = async () => {
    try {
      const [proxyResponse, accountResponse] = await Promise.all([
        api.get('/api/v1/proxies'),
        api.get('/api/v1/accounts'),
      ])
      const usage = accountResponse.data.reduce((acc: Record<number, number>, item: Account) => {
        if (item.proxy_id) acc[item.proxy_id] = (acc[item.proxy_id] || 0) + 1
        return acc
      }, {})
      setProxies(proxyResponse.data
        .map((proxy: any) => ({
          id: proxy.id,
          host: proxy.host,
          port: proxy.port,
          country: inferProxyCountry(proxy.host, proxy.country),
          use_for_accounts: proxy.use_for_accounts,
          is_active: proxy.is_active,
          assignedCount: usage[proxy.id] || 0,
          max_accounts: normalizeProxyMaxAccounts(proxy),
        }))
        .filter((proxy: any) => proxyHasFreeSlot(proxy.assignedCount, proxy.max_accounts) && proxy.use_for_accounts !== false && proxy.is_active !== false)
      )
    } catch (e) {
      console.error('Не удалось загрузить прокси', e)
    }
  }

  useEffect(() => {
    if (isOpen) {
      fetchProxies()
      setSessionFiles([])
      setFileProxies({})
      setError('')
      setResults([])
    }
  }, [isOpen])

  const handleFilesChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = Array.from(e.target.files || [])
    setSessionFiles(picked)
    setFileProxies(prev => {
      const next: Record<string, number | null> = {}
      picked.forEach(f => { next[f.name] = prev[f.name] ?? null })
      return next
    })
    setResults([])
    setError('')
  }

  const setProxyForFile = (filename: string, id: number | null) => {
    setFileProxies(prev => ({ ...prev, [filename]: id }))
  }

  const applyToAll = (id: number | null) => {
    const next: Record<string, number | null> = {}
    sessionFiles.forEach(f => { next[f.name] = id })
    setFileProxies(next)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    if (sessionFiles.length === 0) {
      setError('Выберите один или несколько .session файлов')
      return
    }
    const unassigned = sessionFiles.filter(f => !fileProxies[f.name])
    if (unassigned.length > 0) {
      setError(`Назначьте прокси: ${unassigned.map(f => f.name).join(', ')}`)
      return
    }
    setSubmitting(true)
    setResults([])
    let importedTotal = 0
    for (const file of sessionFiles) {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('default_proxy_id', String(fileProxies[file.name]))
      try {
        const res = await api.post('/api/v1/accounts/import-session', fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        const phone = res.data?.results?.[0]?.phone_number || res.data?.phone_number || '—'
        setResults(prev => [...prev, { file: file.name, ok: true, msg: phone }])
        importedTotal++
      } catch (e: any) {
        const detail = e.response?.data?.detail
        setResults(prev => [...prev, { file: file.name, ok: false, msg: typeof detail === 'string' ? detail : 'ошибка импорта' }])
      }
    }
    if (importedTotal > 0) onSuccess()
    setSubmitting(false)
  }

  const allDone = results.length === sessionFiles.length && sessionFiles.length > 0

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[90vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50 shrink-0">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <Key size={22} weight="duotone" />
                Импорт Session
              </h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto flex-1">
              <p className="text-sm text-muted-foreground">
                Загрузите один или несколько Pyrogram / Telethon <code className="font-mono">.session</code> файлов.
                Каждому аккаунту назначьте прокси — импорт идёт офлайн.
              </p>

              <div className="space-y-2">
                <label className="text-sm font-medium">Session файлы</label>
                <input
                  type="file"
                  accept=".session"
                  multiple
                  onChange={handleFilesChange}
                  className="w-full px-3 py-2.5 rounded-xl border border-border bg-background file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-medium cursor-pointer"
                />
              </div>

              {sessionFiles.length > 0 && (
                <div className="space-y-2">
                  {sessionFiles.length >= 2 && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground shrink-0">Прокси для всех:</span>
                      <select
                        defaultValue=""
                        onChange={(e) => applyToAll(e.target.value ? parseInt(e.target.value) : null)}
                        className="flex-1 text-sm px-2 py-1.5 rounded-lg border border-border bg-background focus:border-primary outline-none"
                      >
                        <option value="">— выбрать и применить —</option>
                        {proxies.map(p => (
                          <option key={p.id} value={p.id}>
                            #{p.id} · {p.host}:{p.port} · {proxyCountryLabel(p.country)} · {p.assignedCount}/{proxyCapacityLabel(p.max_accounts)}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="border border-border rounded-xl overflow-hidden">
                    <div className="grid grid-cols-[1fr_auto] text-xs font-medium text-muted-foreground bg-muted/40 px-3 py-2">
                      <span>Файл</span>
                      <span>Прокси</span>
                    </div>
                    <div className="divide-y divide-border/50 max-h-56 overflow-y-auto">
                      {sessionFiles.map((file, idx) => {
                        const result = results.find(r => r.file === file.name)
                        return (
                          <div key={idx} className="grid grid-cols-[1fr_auto] items-center gap-3 px-3 py-2">
                            <div className="flex items-center gap-2 min-w-0">
                              {result ? (
                                result.ok
                                  ? <CheckCircle size={14} className="text-emerald-500 shrink-0" weight="fill" />
                                  : <XCircle size={14} className="text-red-500 shrink-0" weight="fill" />
                              ) : (
                                <div className="w-3.5 h-3.5 rounded-full border border-border shrink-0" />
                              )}
                              <span className="text-sm truncate font-mono" title={file.name}>{file.name}</span>
                              {result && (
                                <span className={`text-xs truncate ${result.ok ? 'text-emerald-600' : 'text-red-500'}`}>
                                  {result.msg}
                                </span>
                              )}
                            </div>
                            <select
                              value={fileProxies[file.name] ?? ''}
                              onChange={(e) => setProxyForFile(file.name, e.target.value ? parseInt(e.target.value) : null)}
                              disabled={submitting || !!result?.ok}
                              className="text-sm px-2 py-1.5 rounded-lg border border-border bg-background focus:border-primary outline-none disabled:opacity-50 min-w-[200px]"
                            >
                              <option value="">— прокси —</option>
                              {proxies.map(p => (
                                <option key={p.id} value={p.id}>
                                  #{p.id} · {p.host}:{p.port} · {proxyCountryLabel(p.country)} · {p.assignedCount}/{proxyCapacityLabel(p.max_accounts)}
                                </option>
                              ))}
                            </select>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                </div>
              )}

              {error && <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">{error}</p>}

              {allDone && (
                <div className="text-sm bg-emerald-500/10 text-emerald-700 px-4 py-3 rounded-xl flex items-center gap-2">
                  <CheckCircle size={16} weight="bold" />
                  Готово: {results.filter(r => r.ok).length} из {results.length} импортировано
                </div>
              )}

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border border-border hover:bg-muted">
                  Закрыть
                </button>
                <button
                  type="submit"
                  disabled={submitting || sessionFiles.length === 0 || allDone}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting
                    ? <><CircleNotch size={16} className="animate-spin" /> Импорт {results.length + 1}/{sessionFiles.length}…</>
                    : `Импортировать${sessionFiles.length > 1 ? ` (${sessionFiles.length})` : ''}`}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function EditProfileModal({ isOpen, onClose, accountId, phone, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  accountId: number
  phone: string
  onSuccess: () => void
}) {
  const [formData, setFormData] = useState({
    first_name: '',
    about: '',
    personal_channel: '',
    channel_content: ''
  })
  const [avatar, setAvatar] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (isOpen) {
      setError('')
      // In a real app, we'd fetch current profile data here
    }
  }, [isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')

    try {
      const data = new FormData()
      data.append('first_name', formData.first_name)
      data.append('about', formData.about)
      data.append('personal_channel', formData.personal_channel)
      data.append('channel_content', formData.channel_content)
      if (avatar) data.append('avatar', avatar)

      await api.post(`/api/v1/accounts/${accountId}/profile`, data)
      onSuccess()
      onClose()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Ошибка сохранения профиля')
    } finally {
      setLoading(false)
    }
  }

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          onClick={onClose}
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold">Редактирование профиля</h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-5 overflow-y-auto">
              <p className="text-sm text-muted-foreground mb-2">Аккаунт: <b>{phone}</b></p>

              <div className="space-y-4">
                <div className="space-y-1">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <User size={16} /> Имя
                  </label>
                  <input
                    type="text"
                    value={formData.first_name}
                    onChange={(e) => setFormData({ ...formData, first_name: e.target.value })}
                    placeholder="John"
                    className="w-full px-4 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <TextT size={16} /> О себе (Bio)
                  </label>
                  <textarea
                    value={formData.about}
                    onChange={(e) => setFormData({ ...formData, about: e.target.value })}
                    placeholder="Расскажите о себе..."
                    rows={3}
                    className="w-full px-4 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <Image size={16} /> Аватар
                  </label>
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => setAvatar(e.target.files?.[0] || null)}
                    className="w-full px-4 py-2.5 rounded-xl border border-border bg-background file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:text-xs file:font-medium"
                  />
                </div>

                <div className="space-y-1 pt-2 border-t border-border/50">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <Link size={16} /> Личный канал (URL)
                  </label>
                  <input
                    type="text"
                    value={formData.personal_channel}
                    onChange={(e) => setFormData({ ...formData, personal_channel: e.target.value })}
                    placeholder="https://t.me/your_channel"
                    className="w-full px-4 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none font-mono text-sm"
                  />
                </div>

                <div className="space-y-1">
                  <label className="text-sm font-medium">Содержание канала / Пост</label>
                  <textarea
                    value={formData.channel_content}
                    onChange={(e) => setFormData({ ...formData, channel_content: e.target.value })}
                    placeholder="Текст первого сообщения в канале..."
                    rows={3}
                    className="w-full px-4 py-2.5 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none"
                  />
                </div>
              </div>

              {error && (
                <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">{error}</p>
              )}

              <div className="flex gap-3 pt-4 border-t border-border/50">
                <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border border-border hover:bg-muted transition-colors">
                  Отмена
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {loading ? <CircleNotch size={18} className="animate-spin" /> : 'Сохранить'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-4"
    >
      <div className="w-20 h-20 rounded-3xl bg-primary/10 flex items-center justify-center mb-6">
        <UserCircle size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет аккаунтов</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Добавьте свой первый Telegram аккаунт для начала работы с рассылками и парсингом.
      </p>
      <button
        onClick={onAdd}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
      >
        <Plus size={18} weight="bold" />
        Добавить аккаунт
      </button>
    </motion.div>
  )
}

// Shows the account's real avatar (once a photo has been set) instead of
// the generic status icon. Falls back to the status icon while there's no
// avatar (e.g. a freshly-added account).
function AccountAvatar({ account, config }: { account: Account, config: { color: string; bg: string; icon: React.ElementType } }) {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    let objUrl: string | null = null
    if (account.avatar_path) {
      api.get(`/api/v1/accounts/${account.id}/avatar`, { responseType: 'blob' })
        .then(res => {
          if (cancelled) return
          objUrl = URL.createObjectURL(res.data)
          setUrl(objUrl)
        })
        .catch(() => { /* no avatar served — keep the status icon */ })
    } else {
      setUrl(null)
    }
    return () => { cancelled = true; if (objUrl) URL.revokeObjectURL(objUrl) }
  }, [account.id, account.avatar_path])

  if (url) {
    return <img src={url} alt="avatar" className="w-12 h-12 rounded-2xl object-cover border border-border/50" />
  }
  return (
    <div className={`w-12 h-12 rounded-2xl ${config.bg} flex items-center justify-center`}>
      <config.icon size={24} className={config.color} weight="duotone" />
    </div>
  )
}

const AccountCard = forwardRef<HTMLDivElement, { account: Account, onDelete: (id: number) => void, onRefresh: (id: number) => void, onAuthorize?: (id: number) => void, onAssignProxy?: (id: number) => void, onEditProfile?: (id: number) => void, onSendSelf?: (id: number) => void, onEditNote?: (id: number) => void, selected?: boolean, onToggleSelect?: (id: number) => void }>(({ account, onDelete, onRefresh, onAuthorize, onAssignProxy, onEditProfile, onSendSelf, onEditNote, selected, onToggleSelect }, ref) => {
  const [showMenu, setShowMenu] = useState(false)
  // Направление раскрытия меню: если карточка внизу экрана и снизу мало
  // места, открываем меню вверх, чтобы пункты не уезжали за нижний край.
  const [openUp, setOpenUp] = useState(false)
  const menuBtnRef = useRef<HTMLButtonElement>(null)
  const displayStatus = effectiveStatus(account)
  const config = statusConfig[displayStatus] || statusConfig.offline
  const gender = account.gender ? genderConfig[account.gender] : null

  const toggleMenu = () => {
    if (!showMenu && menuBtnRef.current) {
      const rect = menuBtnRef.current.getBoundingClientRect()
      const spaceBelow = window.innerHeight - rect.bottom
      // Меню высокое (до ~380px с учётом всех пунктов). Не хватает места
      // снизу — раскрываем вверх.
      setOpenUp(spaceBelow < 380)
    }
    setShowMenu(v => !v)
  }

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="bg-card rounded-2xl border border-border/50 p-5 hover:border-border transition-colors group min-w-0"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-start gap-3 min-w-0 flex-1">
          {onToggleSelect && (
            <input
              type="checkbox"
              checked={!!selected}
              onChange={() => onToggleSelect(account.id)}
              title="Выделить аккаунт для массовых действий"
              className="mt-3.5 h-5 w-5 rounded border-border shrink-0 cursor-pointer"
            />
          )}
          <AccountAvatar account={account} config={config} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-semibold break-all">{account.phone_number}</p>
              {gender && (
                <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${gender.bg} ${gender.color}`}>
                  <gender.icon size={10} weight="bold" />
                  {gender.label}
                </span>
              )}
              {account.health_factors?.restriction && (
                <span
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-red-500/10 text-red-600"
                  title={`Telegram ограничил аккаунт (${account.health_factors.restriction.reason || 'restricted'}). Проверьте через @SpamBot и дайте прогреться.`}
                >
                  <Warning size={10} weight="bold" />
                  Ограничен
                </span>
              )}
              {account.health_factors?.spambot?.status === 'spam' && (() => {
                const sb = account.health_factors!.spambot!
                const isPermanent = sb.permanent === true
                return (
                  <span
                    className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase ${
                      isPermanent
                        ? 'bg-red-600/15 text-red-600'
                        : 'bg-orange-500/10 text-orange-600'
                    }`}
                    title={
                      isPermanent
                        ? 'SpamBot: бессрочная блокировка (навсегда). Аккаунт не восстановить.'
                        : `SpamBot: временная блокировка${sb.until ? `, до ${sb.until}` : ''}. Дайте прогреться.`
                    }
                  >
                    <Warning size={10} weight="bold" />
                    {isPermanent ? 'Спам навсегда' : sb.until ? `Спам до ${sb.until}` : 'Спам (врем.)'}
                  </span>
                )
              })()}
              {account.health_factors?.spambot?.status === 'clean' && (
                <span
                  className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-600"
                  title="SpamBot: аккаунт чист, ограничений нет"
                >
                  SpamBot: чисто
                </span>
              )}
            </div>
            {/* Личный канал: явная пометка для ОБОИХ состояний, чтобы сразу
                видеть — привязан канал или нет. */}
            {account.personal_channel_id ? (
              <span
                className="inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/10 text-emerald-600 max-w-full"
                title={account.personal_channel_username ? `Личный канал: @${account.personal_channel_username}` : 'Личный канал привязан'}
              >
                <Television size={12} weight="fill" className="shrink-0" />
                <span className="truncate">
                  {account.personal_channel_username ? `@${account.personal_channel_username}` : 'Канал привязан'}
                </span>
              </span>
            ) : (
              <span
                className="inline-flex items-center gap-1 mt-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-muted text-muted-foreground"
                title="Личный канал не привязан"
              >
                <Television size={12} className="shrink-0" />
                Без канала
              </span>
            )}
            <p className="text-sm text-muted-foreground truncate mt-1">
              {account.note?.trim() || 'Заметка не задана'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={displayStatus} />
          <div className="relative">
            <button
              ref={menuBtnRef}
              onClick={toggleMenu}
              className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
            >
              <DotsThree size={20} weight="bold" />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className={`absolute right-0 w-56 bg-card rounded-xl border border-border shadow-xl z-20 py-2 ${openUp ? 'bottom-full mb-2' : 'top-full mt-2'}`}>
                  <button
                    onClick={() => { onRefresh(account.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <ArrowsClockwise size={16} />
                    Проверить статус
                  </button>
                  <button
                    onClick={() => { onAssignProxy && onAssignProxy(account.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <GlobeHemisphereWest size={16} />
                    Назначить прокси
                  </button>
                  <button
                    onClick={() => { onEditNote && onEditNote(account.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <TextT size={16} />
                    Изменить заметку
                  </button>
                  <button
                    onClick={() => { onSendSelf && onSendSelf(account.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <PaperPlaneTilt size={16} />
                    Написать в диалог
                  </button>
                  {(account.status === 'production' || account.status === 'new' || account.status === 'warming') && (
                    <button
                      onClick={() => { onEditProfile && onEditProfile(account.id); setShowMenu(false); }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm text-primary"
                    >
                      <User size={16} />
                      Профиль и канал
                    </button>
                  )}
                  {!account.has_session && !account.session_string && (
                    <button
                      onClick={() => { onAuthorize && onAuthorize(account.id); setShowMenu(false); }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm text-primary"
                    >
                      <Key size={16} />
                      Авторизовать
                    </button>
                  )}
                  <div className="h-px bg-border/50 my-1" />
                  <button
                    onClick={() => { onDelete(account.id); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm text-red-600"
                  >
                    <Trash size={16} />
                    Удалить
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 pt-4 border-t border-border/30 sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Страна</p>
          <p className="font-semibold text-sm">
            {account.proxy_country ? proxyCountryLabel(account.proxy_country) : '—'}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Добавлен</p>
          <p className="font-semibold text-sm">
            {new Date(account.created_at).toLocaleDateString('ru')}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Прокси</p>
          {account.proxy_id ? (
            <p className="font-semibold text-sm flex items-center gap-1">
              <GlobeHemisphereWest size={14} className="text-emerald-600" />
              #{account.proxy_id}
            </p>
          ) : (
            <p className="font-semibold text-sm flex items-center gap-1 text-red-600" title="Без прокси аккаунт нельзя авторизовать">
              <Warning size={14} weight="bold" />
              Не задан
            </p>
          )}
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-1">Прогрев</p>
          <p className="font-semibold text-sm">{account.warmup_level || 0}/30</p>
        </div>
      </div>
    </motion.div>
  )
})

// Decode a base64 payload (from the random-preset endpoint) into a File so
// it can be uploaded as the account's avatar via multipart/form-data.
function base64ToFile(base64: string, filename: string, mimeType: string) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return new File([bytes], filename, { type: mimeType || 'image/jpeg' })
}

const BATCH_LS_KEY = 'autoRegBatchIds'

export default function Accounts() {
  const [accounts, setAccounts] = useState<Account[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [activeBatchIds, setActiveBatchIds] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem(BATCH_LS_KEY) || '[]') } catch { return [] }
  })
  const [editProfileOpen, setEditProfileOpen] = useState(false)
  const [editingAccountId, setEditProfileAccountId] = useState<number | null>(null)
  const [editingAccountPhone, setEditProfileAccountPhone] = useState('')
  const [authModalOpen, setAuthModalOpen] = useState(false)
  const [authAccountId, setAuthAccountId] = useState<number | null>(null)
  const [authPhone, setAuthPhone] = useState('')
  const [authHasProxy, setAuthHasProxy] = useState(true)
  const [proxyModalOpen, setProxyModalOpen] = useState(false)
  const [proxyAccountId, setProxyAccountId] = useState<number | null>(null)
  const [proxyAccountPhone, setProxyAccountPhone] = useState('')
  const [proxyAccountCurrentId, setProxyAccountCurrentId] = useState<number | null>(null)
  const [tdataModalOpen, setTdataModalOpen] = useState(false)
  const [sessionModalOpen, setSessionModalOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [genderFilter, setGenderFilter] = useState<string>('all')
  const [checkingAll, setCheckingAll] = useState(false)
  const [checkAllMessage, setCheckAllMessage] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  // ── Массовые операции над выделенными аккаунтами ────────────────────────
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [bulkGender, setBulkGender] = useState<'male' | 'female'>('male')
  const [bulkLocale, setBulkLocale] = useState<'ru' | 'en'>('ru')
  const [bulkTemplateId, setBulkTemplateId] = useState<number | null>(null)
  const [bulkTemplates, setBulkTemplates] = useState<{ id: number; name: string; posts: any[] }[]>([])
  const [bulkRunning, setBulkRunning] = useState(false)
  const [bulkReport, setBulkReport] = useState('')
  const [spambotRunning, setSpambotRunning] = useState(false)
  const [spambotMessage, setSpambotMessage] = useState('')

  const handleBatchStarted = (ids: number[]) => {
    setActiveBatchIds(ids)
    if (ids.length > 0) localStorage.setItem(BATCH_LS_KEY, JSON.stringify(ids))
    else localStorage.removeItem(BATCH_LS_KEY)
  }

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const clearSelection = () => { setSelectedIds([]); setBulkReport('') }

  const handleEditProfile = (accountId: number) => {
    const acc = accounts.find(a => a.id === accountId)
    if (acc) {
      setEditProfileAccountId(accountId)
      setEditProfileAccountPhone(acc.phone_number)
      setEditProfileOpen(true)
    }
  }

  const handleAuthorize = (accountId: number) => {
    const acc = accounts.find(a => a.id === accountId)
    if (acc) {
      setAuthAccountId(accountId)
      setAuthPhone(acc.phone_number)
      setAuthHasProxy(Boolean(acc.proxy_id))
      setAuthModalOpen(true)
    }
  }

  const handleAssignProxy = (accountId: number) => {
    const acc = accounts.find(a => a.id === accountId)
    if (acc) {
      setProxyAccountId(accountId)
      setProxyAccountPhone(acc.phone_number)
      setProxyAccountCurrentId(acc.proxy_id ?? null)
      setProxyModalOpen(true)
    }
  }

  const fetchAccounts = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/accounts')
      const all: Account[] = response.data
      setAccounts(all)
      // Sync activeBatchIds with pending_ accounts from the server.
      // This restores the banner after a page reload without relying solely
      // on localStorage (localStorage is still a fallback for session state).
      const pendingIds = all
        .filter(a => a.phone_number?.startsWith('pending_'))
        .map(a => a.id)
      if (pendingIds.length > 0) {
        setActiveBatchIds(pendingIds)
        localStorage.setItem(BATCH_LS_KEY, JSON.stringify(pendingIds))
      } else if (all.length > 0) {
        // Only clear once we've confirmed the server has no pending accounts
        setActiveBatchIds([])
        localStorage.removeItem(BATCH_LS_KEY)
      }
    } catch (error) {
      console.error('Ошибка при загрузке аккаунтов:', error)
      setAccounts([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAccounts()
    api.get('/api/v1/personal-channel-templates')
      .then(res => setBulkTemplates(res.data))
      .catch(() => { /* шаблоны не критичны для страницы аккаунтов */ })
  }, [])

  useEffect(() => {
    if (!spambotRunning) return
    const interval = setInterval(async () => {
      try {
        const res = await api.get('/api/v1/accounts/spambot-job')
        const state = res.data
        if (state.progress) setSpambotMessage(state.progress)
        if (!state.running) {
          setSpambotRunning(false)
          if (state.report) setSpambotMessage(state.report)
          await fetchAccounts()
        }
      } catch {
        // ignore polling errors
      }
    }, 5000)
    return () => clearInterval(interval)
  }, [spambotRunning])

  // Массово назначить пол выбранным аккаунтам (быстрая операция, без Telegram).
  const bulkSetGender = async (gender: 'male' | 'female' | 'unknown') => {
    if (selectedIds.length === 0) return
    setBulkRunning(true)
    setBulkReport(`Назначаю пол «${gender}» для ${selectedIds.length} аккаунтов…`)
    let ok = 0; const errors: string[] = []
    for (const id of selectedIds) {
      try { await api.put(`/api/v1/accounts/${id}`, { gender }); ok += 1 }
      catch (e: any) { errors.push(`#${id}: ${e.response?.data?.detail || 'ошибка'}`) }
    }
    await fetchAccounts()
    setBulkReport(`Пол назначен: ${ok} из ${selectedIds.length}.${errors.length ? ` Ошибки: ${errors.slice(0, 3).join('; ')}` : ''}`)
    setBulkRunning(false)
  }

  // Массово: для каждого выбранного аккаунта сгенерировать случайный профиль
  // (имя, username, аватар) по выбранному полу и сразу применить в Telegram.
  const bulkRandomizeAndSave = async () => {
    if (selectedIds.length === 0) return
    setBulkRunning(true)
    let ok = 0; const errors: string[] = []
    for (let i = 0; i < selectedIds.length; i += 1) {
      const id = selectedIds[i]
      setBulkReport(`Генерирую и применяю профиль ${i + 1} из ${selectedIds.length} (аккаунт #${id})…`)
      try {
        const preset = await api.post(`/api/v1/accounts/${id}/profile/random-preset`, { gender: bulkGender, locale: bulkLocale })
        const d = preset.data || {}
        await api.put(`/api/v1/accounts/${id}`, { gender: bulkGender })
        await api.post(`/api/v1/accounts/${id}/profile`, {
          first_name: d.first_name || '',
          last_name: d.last_name || '',
          username: d.username || undefined,
        })
        if (d.avatar_base64) {
          const fd = new FormData()
          fd.append('file', base64ToFile(d.avatar_base64, d.avatar_filename || 'avatar.jpg', d.avatar_mime_type || 'image/jpeg'))
          await api.post(`/api/v1/accounts/${id}/profile/avatar`, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
        }
        ok += 1
      } catch (e: any) {
        errors.push(`#${id}: ${e.response?.data?.detail || e.message || 'ошибка'}`)
      }
    }
    await fetchAccounts()
    setBulkReport(`Профили применены: ${ok} из ${selectedIds.length}.${errors.length ? ` Ошибки (${errors.length}): ${errors.slice(0, 4).join('; ')}` : ''}`)
    setBulkRunning(false)
  }

  // Массово применить шаблон личного канала к выбранным аккаунтам.
  const bulkApplyChannel = async () => {
    if (selectedIds.length === 0 || !bulkTemplateId) return
    setBulkRunning(true)
    setBulkReport(`Применяю шаблон канала к ${selectedIds.length} аккаунтам… это может занять время.`)
    try {
      const res = await api.post(`/api/v1/personal-channel-templates/${bulkTemplateId}/apply`,
        { account_ids: selectedIds, create_if_missing: true },
        { timeout: 600000 })
      const applied = res.data?.applied ?? 0
      const failed = (res.data?.results || []).filter((r: any) => r.status === 'failed')
      const reasons = failed.slice(0, 4).map((r: any) => `#${r.account_id}: ${r.reason}`).join('; ')
      setBulkReport(`Канал применён к ${applied} из ${selectedIds.length}.${failed.length ? ` Ошибки (${failed.length}): ${reasons}` : ''}`)
      await fetchAccounts()
    } catch (e: any) {
      setBulkReport(`Не удалось применить шаблон: ${e.response?.data?.detail || e.message || 'ошибка'}`)
    } finally {
      setBulkRunning(false)
    }
  }

  const handleBulkUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      setLoading(true)
      await api.post('/api/v1/accounts/bulk-upload', formData)
      fetchAccounts()
    } catch (error) {
      console.error('Ошибка при массовой загрузке:', error)
    } finally {
      setLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const checkHealth = async (id: number) => {
    try {
      await api.post(`/api/v1/accounts/${id}/check`)
      fetchAccounts()
    } catch (error) {
      console.error('Ошибка при проверке:', error)
    }
  }

  const checkAllAccounts = async () => {
    setCheckingAll(true)
    setCheckAllMessage('')
    setSpambotMessage('')
    try {
      const response = await api.post('/api/v1/accounts/check-all', undefined, { timeout: 180000 })
      const results = response.data.results || []
      const healthy = results.filter((item: any) => item.is_healthy).length
      const skipped = results.filter((item: any) => ['no_session', 'no_proxy'].includes(item.message)).length
      const failed = results.length - healthy - skipped
      setCheckAllMessage(`Проверено: ${results.length}. Живые: ${healthy}. Пропущено без сессии/прокси: ${skipped}. Ошибки: ${failed}.`)
      await fetchAccounts()
      // SpamBot-проверка уже запущена бэкендом вместе с check-all — начинаем поллить
      if (response.data.spambot_check === 'started') {
        setSpambotRunning(true)
        setSpambotMessage('Запрашиваю @SpamBot для каждого аккаунта…')
      }
    } catch (error: any) {
      const detail = error.response?.data?.detail || error.message || 'Не удалось проверить аккаунты'
      setCheckAllMessage(detail)
    } finally {
      setCheckingAll(false)
    }
  }

  const sendMessageToSelf = async (id: number) => {
    const target = window.prompt('Кому написать: @username, username, номер или t.me/username')
    if (!target?.trim()) return
    const text = window.prompt('Текст сообщения', 'Привет, это тестовое сообщение из сервиса')
    if (!text?.trim()) return
    try {
      const response = await api.post(`/api/v1/accounts/${id}/send-direct-message`, { target: target.trim(), text: text.trim() })
      const account = accounts.find(item => item.id === id)
      const accountLabel = account?.note?.trim() || account?.username || account?.phone_number || 'Аккаунт'
      const finalTarget = response.data?.target || target.trim()
      const messageId = response.data?.message_id
      const successText = `Сообщение отправлено: ${accountLabel} -> ${finalTarget}${messageId ? ` (id ${messageId})` : ''}.`
      setCheckAllMessage(successText)
      window.alert(successText)
    } catch (error: any) {
      const detail = error.response?.data?.detail || 'Не удалось отправить сообщение в диалог.'
      setCheckAllMessage(detail)
      window.alert(detail)
    }
  }

  const editAccountNote = async (id: number) => {
    const account = accounts.find(item => item.id === id)
    const note = window.prompt('Заметка аккаунта', account?.note || '')
    if (note === null) return
    try {
      await api.put(`/api/v1/accounts/${id}`, { note: note.trim() || null })
      await fetchAccounts()
    } catch (error: any) {
      setCheckAllMessage(error.response?.data?.detail || 'Не удалось сохранить заметку.')
    }
  }

  const deleteAccount = async (id: number) => {
    try {
      await api.delete(`/api/v1/accounts/${id}`)
      fetchAccounts()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  // Accounts still in auto-registration (pending_ phone) are tracked via the
  // floating banner; exclude them from the main list to avoid confusing rows.
  const realAccounts = accounts.filter(a => !a.phone_number?.startsWith('pending_'))

  const filteredAccounts = realAccounts.filter(account => {
    const matchesSearch = account.phone_number.includes(searchQuery)
    const matchesStatus = statusFilter === 'all' || effectiveStatus(account) === statusFilter
    const matchesGender = genderFilter === 'all' || account.gender === genderFilter
    return matchesSearch && matchesStatus && matchesGender
  })

  const statusCounts = {
    all: realAccounts.length,
    production: realAccounts.filter(a => effectiveStatus(a) === 'production').length,
    warming: realAccounts.filter(a => effectiveStatus(a) === 'warming').length,
    new: realAccounts.filter(a => effectiveStatus(a) === 'new').length,
    banned: realAccounts.filter(a => effectiveStatus(a) === 'banned').length,
    male: realAccounts.filter(a => a.gender === 'male').length,
    female: realAccounts.filter(a => a.gender === 'female').length,
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-4"
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Аккаунты</h1>
          <p className="text-muted-foreground mt-1">Управление Telegram аккаунтами</p>
        </div>
        <div className="flex items-center gap-3">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleBulkUpload}
            className="hidden"
            accept=".csv"
          />
          <button
            onClick={checkAllAccounts}
            disabled={checkingAll}
            title="Проверить, что аккаунты подключаются к Telegram через свои прокси"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium disabled:opacity-50"
          >
            {checkingAll ? <CircleNotch size={18} className="animate-spin" /> : <ShieldCheck size={18} />}
            Проверить всё
          </button>
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Импорт CSV: phone,api_id,api_hash,proxy_ref,session_string"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
          >
            <Upload size={18} />
            CSV
          </button>
          <button
            onClick={() => setTdataModalOpen(true)}
            title="Импорт из Telegram Desktop tdata"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
          >
            <FileArchive size={18} />
            TData
          </button>
          <button
            onClick={() => setSessionModalOpen(true)}
            title="Импорт Pyrogram/Telethon .session"
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
          >
            <Key size={18} />
            Session
          </button>
          <button
            onClick={() => setIsModalOpen(true)}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus size={18} weight="bold" />
            Добавить
          </button>
        </div>
      </motion.div>

      {checkAllMessage && (
        <div className="rounded-2xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          {checkAllMessage}
        </div>
      )}
      {spambotMessage && (
        <div className="rounded-2xl border border-orange-200 bg-orange-50 dark:bg-orange-500/5 dark:border-orange-500/20 px-4 py-3 text-sm text-orange-700 dark:text-orange-400">
          {spambotRunning && <span className="mr-2 animate-pulse">⏳</span>}
          {spambotMessage}
        </div>
      )}

      {/* Панель массовых действий — появляется при выделении аккаунтов */}
      <div className="rounded-2xl border border-border bg-card px-4 py-3 space-y-3">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-medium">Массовые действия</span>
          <span className="text-muted-foreground">Выбрано: {selectedIds.length}</span>
          <button
            onClick={() => setSelectedIds(filteredAccounts.map(a => a.id))}
            className="px-3 py-1.5 rounded-lg border border-border hover:bg-muted text-xs font-medium"
          >
            Выделить все ({filteredAccounts.length})
          </button>
          <button
            onClick={clearSelection}
            disabled={selectedIds.length === 0}
            className="px-3 py-1.5 rounded-lg border border-border hover:bg-muted text-xs font-medium disabled:opacity-40"
          >
            Снять выделение
          </button>
        </div>

        {selectedIds.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border/50">
            {/* Пол */}
            <div className="inline-flex rounded-lg border border-border bg-muted p-1">
              <button
                onClick={() => setBulkGender('male')}
                className={`px-3 py-1 rounded-md text-xs font-medium ${bulkGender === 'male' ? 'bg-card shadow-sm text-blue-600' : 'text-muted-foreground'}`}
              >Мужской</button>
              <button
                onClick={() => setBulkGender('female')}
                className={`px-3 py-1 rounded-md text-xs font-medium ${bulkGender === 'female' ? 'bg-card shadow-sm text-pink-600' : 'text-muted-foreground'}`}
              >Женский</button>
            </div>
            {/* Язык имени */}
            <div className="inline-flex rounded-lg border border-border bg-muted p-1">
              <button onClick={() => setBulkLocale('ru')} className={`px-2.5 py-1 rounded-md text-xs font-medium ${bulkLocale === 'ru' ? 'bg-card shadow-sm' : 'text-muted-foreground'}`}>рус</button>
              <button onClick={() => setBulkLocale('en')} className={`px-2.5 py-1 rounded-md text-xs font-medium ${bulkLocale === 'en' ? 'bg-card shadow-sm' : 'text-muted-foreground'}`}>англ</button>
            </div>
            <button
              onClick={() => bulkSetGender(bulkGender)}
              disabled={bulkRunning}
              title="Назначить выбранный пол всем выделенным (без обращения к Telegram)"
              className="px-3 py-1.5 rounded-lg border border-border hover:bg-muted text-xs font-medium disabled:opacity-50"
            >
              Назначить пол
            </button>
            <button
              onClick={bulkRandomizeAndSave}
              disabled={bulkRunning}
              title="Для каждого выделенного: сгенерировать случайные имя, username и аватар по выбранному полу и применить в Telegram"
              className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-medium disabled:opacity-50 inline-flex items-center gap-1"
            >
              {bulkRunning ? <CircleNotch size={14} className="animate-spin" /> : <UserCircle size={14} />}
              Случайный профиль + сохранить
            </button>

            {/* Личный канал */}
            <div className="inline-flex items-center gap-1 ml-auto">
              <select
                value={bulkTemplateId ?? ''}
                onChange={e => setBulkTemplateId(e.target.value ? Number(e.target.value) : null)}
                className="px-2 py-1.5 rounded-lg border border-border bg-background text-xs"
              >
                <option value="">— шаблон канала —</option>
                {bulkTemplates.map(t => (
                  <option key={t.id} value={t.id}>{t.name} · {t.posts?.length ?? 0} пост(ов)</option>
                ))}
              </select>
              <button
                onClick={bulkApplyChannel}
                disabled={bulkRunning || !bulkTemplateId}
                title="Создать/обновить личный канал по шаблону у всех выделенных аккаунтов"
                className="px-3 py-1.5 rounded-lg border border-primary/30 text-primary hover:bg-primary/10 text-xs font-medium disabled:opacity-50 inline-flex items-center gap-1"
              >
                {bulkRunning ? <CircleNotch size={14} className="animate-spin" /> : <Television size={14} />}
                Добавить канал
              </button>
            </div>
          </div>
        )}

        {bulkReport && (
          <p className="text-xs text-muted-foreground pt-1">{bulkReport}</p>
        )}
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-4">
        {[
          { key: 'all', label: 'Всего' },
          { key: 'production', label: 'Активны' },
          { key: 'warming', label: 'Прогрев' },
          { key: 'new', label: 'Новые' },
          { key: 'banned', label: 'Заблокир.' },
        ].map((item) => (
          <button
            key={item.key}
            onClick={() => setStatusFilter(item.key)}
            className={`
              p-4 rounded-2xl border transition-all text-left
              ${statusFilter === item.key
                ? 'bg-primary/10 border-primary/30 text-primary'
                : 'bg-card border-border hover:border-border/80'
              }
            `}
          >
            <p className="text-2xl font-bold">{statusCounts[item.key as keyof typeof statusCounts]}</p>
            <p className="text-sm text-muted-foreground">{item.label}</p>
          </button>
        ))}
      </div>

      {/* Gender Filter */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-muted-foreground mr-2">Фильтр по полу:</span>
        <div className="flex bg-muted p-1 rounded-xl">
          {[
            { key: 'all', label: 'Все', icon: Users },
            { key: 'male', label: 'Мужской', icon: GenderMale },
            { key: 'female', label: 'Женский', icon: GenderFemale },
            { key: 'unknown', label: 'Неизвестно', icon: Question },
          ].map((item) => (
            <button
              key={item.key}
              onClick={() => setGenderFilter(item.key)}
              className={`
                flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-all
                ${genderFilter === item.key
                  ? 'bg-card text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
                }
              `}
            >
              <item.icon size={16} />
              {item.label}
              {item.key !== 'all' && (
                <span className="ml-1 opacity-50">
                  {accounts.filter(a => a.gender === item.key).length}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <MagnifyingGlass size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Поиск по номеру..."
          className="w-full pl-12 pr-4 py-3.5 rounded-2xl border border-border bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
        />
      </div>

      {/* Accounts Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-48 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : filteredAccounts.length === 0 ? (
        <EmptyState onAdd={() => setIsModalOpen(true)} />
      ) : (
        <motion.div
          layout
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6"
        >
          <AnimatePresence mode="popLayout">
            {filteredAccounts.map((account) => (
              <AccountCard
                key={account.id}
                account={account}
                onDelete={deleteAccount}
                onRefresh={checkHealth}
                onAuthorize={handleAuthorize}
                onAssignProxy={handleAssignProxy}
                onEditProfile={handleEditProfile}
                onSendSelf={sendMessageToSelf}
                onEditNote={editAccountNote}
                selected={selectedIds.includes(account.id)}
                onToggleSelect={toggleSelect}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      {/* Modal */}
      <AddAccountModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchAccounts}
        resumeBatch={activeBatchIds.length > 0 ? activeBatchIds : null}
        onBatchStarted={handleBatchStarted}
      />

      {/* Floating banner — visible when a batch is running and modal is closed */}
      <AnimatePresence>
        {activeBatchIds.length > 0 && !isModalOpen && (
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 40 }}
            className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 flex items-center gap-3 bg-primary text-primary-foreground px-5 py-3 rounded-2xl shadow-2xl shadow-primary/25"
          >
            <CircleNotch size={16} className="animate-spin shrink-0" weight="bold" />
            <span className="text-sm font-medium">Регистрация {activeBatchIds.length} аккаунт(ов)…</span>
            <button
              onClick={() => setIsModalOpen(true)}
              className="ml-2 px-3 py-1.5 rounded-lg bg-white/20 hover:bg-white/30 text-xs font-semibold transition-colors"
            >
              Открыть
            </button>
          </motion.div>
        )}
      </AnimatePresence>
      <ProfileEditor
        isOpen={editProfileOpen}
        onClose={() => setEditProfileOpen(false)}
        account={accounts.find(a => a.id === editingAccountId) || null}
        accounts={accounts}
        onSuccess={fetchAccounts}
      />
      <AuthorizeModal
        isOpen={authModalOpen}
        onClose={() => setAuthModalOpen(false)}
        accountId={authAccountId!}
        phone={authPhone}
        hasProxy={authHasProxy}
      />
      <AssignProxyModal
        isOpen={proxyModalOpen}
        onClose={() => setProxyModalOpen(false)}
        accountId={proxyAccountId!}
        phone={proxyAccountPhone}
        currentProxyId={proxyAccountCurrentId}
        onSuccess={fetchAccounts}
      />
      <TDataImportModal
        isOpen={tdataModalOpen}
        onClose={() => setTdataModalOpen(false)}
        onSuccess={fetchAccounts}
      />
      <SessionImportModal
        isOpen={sessionModalOpen}
        onClose={() => setSessionModalOpen(false)}
        onSuccess={fetchAccounts}
      />
    </div>
  )
}
