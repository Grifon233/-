import { useState, useEffect, useRef, forwardRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Upload,
  ArrowsClockwise,
  Trash,
  X,
  Globe,
  ShieldCheck,
  XCircle,
  DotsThree,
  Check,
  MagnifyingGlass,
  Timer,
  Lock,
  Tag,
  ShoppingCart
} from '@phosphor-icons/react'
import { ProxyVendorPanel } from '../components/ProxyVendorPanel'

const COUNTRY_NAMES: Record<string, string> = {
  'US': 'США', 'RU': 'Россия', 'UA': 'Украина', 'KZ': 'Казахстан', 'BY': 'Беларусь',
  'DE': 'Германия', 'FR': 'Франция', 'GB': 'Великобритания', 'NL': 'Нидерланды',
  'LV': 'Латвия', 'LT': 'Литва', 'EE': 'Эстония', 'PL': 'Польша', 'TR': 'Турция',
  'CA': 'Канада', 'ID': 'Индонезия',
  'SE': 'Швеция', 'FI': 'Финляндия', 'NO': 'Норвегия', 'DK': 'Дания',
  'AT': 'Австрия', 'CH': 'Швейцария', 'IT': 'Италия', 'ES': 'Испания', 'PT': 'Португалия',
  'RO': 'Румыния', 'BG': 'Болгария', 'HU': 'Венгрия', 'CZ': 'Чехия', 'SK': 'Словакия',
  'HR': 'Хорватия', 'RS': 'Сербия', 'GR': 'Греция', 'SI': 'Словения',
  'MD': 'Молдова', 'GE': 'Грузия', 'AM': 'Армения', 'AZ': 'Азербайджан',
  'UZ': 'Узбекистан', 'TJ': 'Таджикистан', 'KG': 'Кыргызстан', 'TM': 'Туркменистан',
  'JP': 'Япония', 'KR': 'Юж. Корея', 'CN': 'Китай', 'SG': 'Сингапур', 'HK': 'Гонконг',
  'TH': 'Таиланд', 'VN': 'Вьетнам', 'MY': 'Малайзия', 'PH': 'Филиппины', 'IN': 'Индия',
  'AU': 'Австралия', 'NZ': 'Новая Зеландия',
  'BR': 'Бразилия', 'MX': 'Мексика', 'AR': 'Аргентина', 'CO': 'Колумбия',
  'ZA': 'ЮАР', 'NG': 'Нигерия', 'EG': 'Египет', 'MA': 'Марокко',
  'IL': 'Израиль', 'AE': 'ОАЭ', 'SA': 'Саудовская Аравия',
  'MN': 'Монголия',
}

const countryLabel = (countryCode?: string | null) => {
  if (!countryCode) return ''
  const normalized = countryCode.toUpperCase()
  return COUNTRY_NAMES[normalized] || normalized
}

const getFlagEmoji = (countryCode: string) => {
  try {
    return String.fromCodePoint(
      ...countryCode.toUpperCase().split('').map(c => 127397 + c.charCodeAt(0))
    )
  } catch {
    return ''
  }
}

const StatusBadge = forwardRef<HTMLSpanElement, { active: boolean | null }>(({ active }, ref) => {
  return (
    <span ref={ref} className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${
      active === true
        ? 'bg-emerald-500/10 text-emerald-600'
        : active === false
        ? 'bg-red-500/10 text-red-600'
        : 'bg-muted text-muted-foreground'
    }`}>
      {active === true ? (
        <>
          <ShieldCheck size={12} weight="bold" />
          В сети
        </>
      ) : active === false ? (
        <>
          <XCircle size={12} weight="bold" />
          Недоступен
        </>
      ) : (
        <>
          <ArrowsClockwise size={12} weight="bold" />
          Не проверен
        </>
      )}
    </span>
  )
})

function AddProxyModal({ isOpen, onClose, onSuccess, initialMode = 'single' }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  initialMode?: 'single' | 'bulk'
}) {
  const [mode, setMode] = useState<'single' | 'bulk'>(initialMode)

  useEffect(() => {
    if (isOpen) setMode(initialMode)
  }, [isOpen, initialMode])
  const [formData, setFormData] = useState({
    scheme: 'socks5',
    host: '',
    port: '',
    username: '',
    password: ''
  })
  const [bulkText, setBulkText] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [useForAccounts, setUseForAccounts] = useState(true)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      if (mode === 'single') {
        await api.post('/api/v1/proxies', {
          ...formData,
          port: parseInt(formData.port),
          use_for_accounts: useForAccounts
        })
      } else {
        await api.post('/api/v1/proxies/bulk-paste', {
          text: bulkText,
          use_for_accounts: useForAccounts
        })
      }
      setFormData({ scheme: 'socks5', host: '', port: '', username: '', password: '' })
      setBulkText('')
      onSuccess()
      onClose()
    } catch (err: any) {
      console.error('Ошибка при добавлении прокси:', err)
      setError(err.response?.data?.detail?.[0]?.msg || err.response?.data?.detail || 'Ошибка при добавлении прокси')
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
              <h2 className="text-xl font-semibold">Добавить прокси</h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <div className="p-6 pb-0">
              <div className="flex bg-muted rounded-xl p-1">
                <button
                  onClick={() => setMode('single')}
                  className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${
                    mode === 'single' ? 'bg-card shadow-sm text-foreground' : 'text-muted-foreground'
                  }`}
                >
                  Вручную
                </button>
                <button
                  onClick={() => setMode('bulk')}
                  className={`flex-1 py-2 text-sm font-medium rounded-lg transition-all ${
                    mode === 'bulk' ? 'bg-card shadow-sm text-foreground' : 'text-muted-foreground'
                  }`}
                >
                  Массово
                </button>
              </div>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-6">
              {error && (
                <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-500 text-sm">
                  {error}
                </div>
              )}

              <div className="flex items-center gap-3 p-4 bg-primary/5 border border-primary/20 rounded-2xl">
                <input
                  id="use_for_accounts_modal"
                  type="checkbox"
                  checked={useForAccounts}
                  onChange={(e) => setUseForAccounts(e.target.checked)}
                  className="w-5 h-5 rounded border-border text-primary focus:ring-primary"
                />
                <label htmlFor="use_for_accounts_modal" className="text-sm font-medium cursor-pointer">
                  Использовать для работы с аккаунтами
                </label>
              </div>

              {mode === 'single' ? (
                <>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <Tag size={14} />
                        Протокол
                      </label>
                      <select
                        value={formData.scheme}
                        onChange={(e) => setFormData({ ...formData, scheme: e.target.value })}
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                      >
                        <option value="socks5">SOCKS5</option>
                        <option value="http">HTTP</option>
                      </select>
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <Globe size={14} />
                        Порт
                      </label>
                      <input
                        type="number"
                        value={formData.port}
                        onChange={(e) => setFormData({ ...formData, port: e.target.value })}
                        placeholder="1080"
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                        required
                      />
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium">Хост (IP адрес)</label>
                    <input
                      type="text"
                      value={formData.host}
                      onChange={(e) => setFormData({ ...formData, host: e.target.value })}
                      placeholder="1.2.3.4"
                      className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none font-mono"
                      required
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <Lock size={14} />
                        Логин
                      </label>
                      <input
                        type="text"
                        value={formData.username}
                        onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                        placeholder="Необязательно"
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                      />
                    </div>
                    <div className="space-y-2">
                      <label className="text-sm font-medium flex items-center gap-2">
                        <Lock size={14} />
                        Пароль
                      </label>
                      <input
                        type="password"
                        value={formData.password}
                        onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                        placeholder="Необязательно"
                        className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                      />
                    </div>
                  </div>
                </>
              ) : (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Список прокси (один в строке)</label>
                  <textarea
                    value={bulkText}
                    onChange={(e) => setBulkText(e.target.value)}
                    placeholder="host:port:user:pass&#10;user:pass@host:port&#10;host:port"
                    className="w-full h-48 px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none font-mono text-sm resize-none"
                    required
                  />
                  <p className="text-xs text-muted-foreground">
                    Поддерживаются форматы IP:PORT, IP:PORT:USER:PASS и USER:PASS@IP:PORT
                  </p>
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
                  disabled={submitting}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50"
                >
                  {submitting ? 'Сохранение...' : 'Сохранить'}
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

interface Proxy {
  id: number
  scheme: string
  host: string
  port: number
  username?: string
  password?: string
  is_active: boolean | null
  response_time_ms?: number
  last_checked_at?: string
  expires_at?: string
  country?: string
  vendor_name?: string
  vendor_proxy_id?: string
  use_for_accounts: boolean
  account_count: number
  max_accounts: number | null
}

const ProxyCard = forwardRef<HTMLDivElement, { proxy: Proxy, onCheck: (id: number) => void, onDelete: (id: number) => void, onRenew: (proxy: Proxy) => void, onUpdate: (proxy: Proxy) => void }>(({ proxy, onCheck, onDelete, onRenew, onUpdate }, ref) => {
  const [showMenu, setShowMenu] = useState(false)
  const [editingMax, setEditingMax] = useState(false)
  const [maxInput, setMaxInput] = useState(String(proxy.max_accounts ?? ''))

  const toggleUsage = async () => {
    try {
      const response = await api.put(`/api/v1/proxies/${proxy.id}`, {
        use_for_accounts: !proxy.use_for_accounts
      })
      onUpdate(response.data)
    } catch (err) {
      console.error('Error toggling proxy usage:', err)
    }
  }

  const saveMaxAccounts = async () => {
    const num = maxInput.trim() === '' ? null : parseInt(maxInput)
    try {
      const response = await api.put(`/api/v1/proxies/${proxy.id}`, { max_accounts: num })
      onUpdate({ ...response.data, account_count: proxy.account_count })
    } catch (err) {
      console.error('Error updating max accounts:', err)
    }
    setEditingMax(false)
  }

  const isExpired = proxy.expires_at && new Date(proxy.expires_at) < new Date()
  const accountsFull = proxy.max_accounts !== null && (proxy.account_count ?? 0) >= proxy.max_accounts

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className={`bg-card rounded-2xl border ${proxy.use_for_accounts ? 'border-border/50' : 'border-dashed border-red-500/30 opacity-70'} p-5 hover:border-border/80 transition-colors min-w-0`}
    >
      {/* ── Header ── */}
      <div className="flex items-start gap-3 mb-4">
        {/* Status-coloured icon */}
        <div className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${
          proxy.is_active === true ? 'bg-emerald-500/10'
          : proxy.is_active === false ? 'bg-red-500/10'
          : 'bg-muted'
        }`}>
          <Globe
            size={22}
            weight="duotone"
            className={
              proxy.is_active === true ? 'text-emerald-600'
              : proxy.is_active === false ? 'text-red-600'
              : 'text-muted-foreground'
            }
          />
        </div>

        {/* IP : PORT  +  always-second-line badges */}
        <div className="flex-1 min-w-0">
          <p className="font-semibold font-mono text-sm leading-snug break-all">
            {proxy.host}:{proxy.port}
          </p>
          {/* Row 2 — scheme · country · expiry · disabled flag — always same row */}
          <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
            <span className="text-[11px] text-muted-foreground uppercase font-semibold tracking-wide">
              {proxy.scheme}
            </span>
            {proxy.country && (
              <span className="inline-flex items-center gap-1 text-[11px] bg-primary/10 text-primary px-2 py-0.5 rounded-full font-semibold">
                {getFlagEmoji(proxy.country)}&nbsp;{countryLabel(proxy.country)}
              </span>
            )}
            {proxy.expires_at && (
              <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${
                isExpired ? 'bg-red-500/15 text-red-500' : 'bg-orange-500/15 text-orange-500'
              }`}>
                до {new Date(proxy.expires_at).toLocaleDateString('ru')}
              </span>
            )}
            {!proxy.use_for_accounts && (
              <span className="text-[10px] bg-red-500/10 text-red-500 px-2 py-0.5 rounded-full font-bold">
                Откл.
              </span>
            )}
          </div>
        </div>

        {/* Status badge + menu — always top-right */}
        <div className="flex items-center gap-1.5 shrink-0">
          <StatusBadge active={proxy.is_active} />
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-1.5 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
            >
              <DotsThree size={20} weight="bold" />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className="absolute right-0 top-full mt-2 w-56 bg-card rounded-xl border border-border shadow-xl z-20 py-2">
                  <button
                    onClick={() => { onCheck(proxy.id); setShowMenu(false) }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <ArrowsClockwise size={16} />
                    Проверить
                  </button>
                  <button
                    onClick={() => { toggleUsage(); setShowMenu(false) }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    <ShieldCheck size={16} className={proxy.use_for_accounts ? 'text-emerald-600' : 'text-muted-foreground'} />
                    {proxy.use_for_accounts ? 'Отключить для аккаунтов' : 'Включить для аккаунтов'}
                  </button>
                  {proxy.vendor_name === 'proxy6' && proxy.vendor_proxy_id && (
                    <button
                      onClick={() => { onRenew(proxy); setShowMenu(false) }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                    >
                      <Timer size={16} />
                      Продлить
                    </button>
                  )}
                  <div className="h-px bg-border/50 my-1" />
                  <button
                    onClick={() => { onDelete(proxy.id); setShowMenu(false) }}
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

      {/* ── Footer stats — 3 equal columns ── */}
      <div className="grid grid-cols-3 gap-2 pt-4 border-t border-border/30">
        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Отклик</p>
          <p className="font-semibold text-sm tabular-nums">
            {proxy.response_time_ms ? `${proxy.response_time_ms} ms` : '—'}
          </p>
        </div>

        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Аккаунты</p>
          {editingMax ? (
            <input
              type="number"
              autoFocus
              value={maxInput}
              onChange={(e) => setMaxInput(e.target.value)}
              onBlur={saveMaxAccounts}
              onKeyDown={(e) => { if (e.key === 'Enter') saveMaxAccounts() }}
              className="w-16 px-2 py-0.5 rounded-lg border border-primary text-sm font-mono outline-none"
              min="1"
              placeholder="∞"
            />
          ) : (
            <p
              className={`font-semibold text-sm tabular-nums cursor-pointer hover:text-primary transition-colors ${accountsFull ? 'text-amber-600' : ''}`}
              onClick={() => { setEditingMax(true); setMaxInput(String(proxy.max_accounts ?? '')) }}
              title="Нажмите чтобы изменить лимит"
            >
              {proxy.account_count ?? 0}&thinsp;/&thinsp;{proxy.max_accounts ?? '∞'}
            </p>
          )}
        </div>

        <div>
          <p className="text-[10px] text-muted-foreground uppercase tracking-wide mb-1">Проверка</p>
          <p className="font-semibold text-sm">
            {proxy.last_checked_at
              ? new Date(proxy.last_checked_at).toLocaleString('ru', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
              : '—'
            }
          </p>
        </div>
      </div>
    </motion.div>
  )
})

function ProxyServiceSection({ onSync }: { onSync: () => void }) {
  const [info, setInfo] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  const fetchInfo = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/proxy-vendor/balance')
      setInfo(response.data)
    } catch (err) {
      console.error('Error fetching proxy service info:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchInfo()
  }, [])

  const handleSync = async () => {
    try {
      setLoading(true)
      await api.post('/api/v1/proxy-vendor/import-all')
      onSync()
      fetchInfo()
    } catch (err: any) {
      console.error('Error syncing proxies:', err)
      alert(err.response?.data?.detail || 'Ошибка при синхронизации с сервисом')
    } finally {
      setLoading(false)
    }
  }

  if (!info || info.error) return null

  return (
    <motion.div
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-primary/5 border border-primary/20 rounded-3xl p-6 mb-8 flex flex-col md:flex-row items-start md:items-center justify-between gap-6"
    >
      <div className="flex items-center gap-4">
        <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center">
          <Globe size={32} className="text-primary" weight="duotone" />
        </div>
        <div>
          <h3 className="text-lg font-bold">Интеграция Proxy6.net</h3>
          <p className="text-sm text-muted-foreground">
            Баланс: <span className="text-foreground font-medium">{info.balance || 0} {info.currency || 'RUB'}</span> • 
            Пользователь: <span className="text-foreground font-medium">{info.email || info.user_id || '—'}</span>
          </p>
        </div>
      </div>
      <div className="flex items-center gap-4 w-full md:w-auto">
        <a
          href="https://proxy6.net/?r=991430"
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 md:flex-none inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl border border-primary/20 bg-background text-primary font-bold hover:bg-primary/5 transition-all"
        >
          <ShoppingCart size={20} weight="bold" />
          Купить прокси
        </a>
        <button
          onClick={handleSync}
          disabled={loading}
          className="flex-1 md:flex-none inline-flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl bg-primary text-primary-foreground font-bold hover:bg-primary/90 transition-all shadow-lg shadow-primary/20 disabled:opacity-50"
        >
          <ArrowsClockwise size={20} className={loading ? 'animate-spin' : ''} weight="bold" />
          Синхронизировать
        </button>
      </div>
    </motion.div>
  )
}

export default function Proxies() {
  const [proxies, setProxies] = useState<Proxy[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [modalMode, setModalMode] = useState<'single' | 'bulk'>('single')
  const [searchQuery, setSearchQuery] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchProxies = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/proxies')
      setProxies(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке прокси:', error)
      setProxies([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchProxies()
  }, [])

  const handleProxyUpdate = (updatedProxy: Proxy) => {
    setProxies(prev => prev.map(p => p.id === updatedProxy.id ? updatedProxy : p))
  }

  const handleBulkUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    try {
      setLoading(true)
      await api.post('/api/v1/proxies/bulk-upload', formData)
      fetchProxies()
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
    } finally {
      setLoading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const checkProxy = async (id: number) => {
    try {
      await api.post(`/api/v1/proxies/${id}/check`)
      fetchProxies()
    } catch (error) {
      console.error('Ошибка при проверке:', error)
    }
  }

  const deleteProxy = async (id: number) => {
    try {
      await api.delete(`/api/v1/proxies/${id}`)
      fetchProxies()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const renewProxy = async (proxy: Proxy) => {
    if (!proxy.vendor_proxy_id) {
      alert('Этот прокси не связан с proxy6.net, поэтому продление через API недоступно.')
      return
    }
    const value = prompt(`На сколько дней продлить ${proxy.host}:${proxy.port}?`, '30')
    if (!value) return
    const period = Number(value)
    if (!Number.isFinite(period) || period < 1 || period > 365) {
      alert('Период должен быть числом от 1 до 365 дней.')
      return
    }
    if (!confirm(`Продлить прокси на ${period} дней? С баланса proxy6.net будут списаны деньги.`)) return
    try {
      await api.post('/api/v1/proxy-vendor/renew', {
        proxy_id: proxy.vendor_proxy_id,
        period,
        confirm: true,
      })
      fetchProxies()
    } catch (error: any) {
      console.error('Ошибка при продлении:', error)
      alert(error.response?.data?.detail || 'Не удалось продлить прокси')
    }
  }

  const filteredProxies = proxies.filter(proxy =>
    proxy.host.includes(searchQuery) || proxy.scheme.includes(searchQuery)
  )

  const activeCount = proxies.filter(p => p.is_active === true).length
  const avgResponse = Math.round(
    proxies.filter(p => p.response_time_ms)
      .reduce((sum, p) => sum + (p.response_time_ms || 0), 0) /
    (proxies.filter(p => p.response_time_ms).length || 1)
  )

  return (
    <div className="space-y-8">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex flex-col sm:flex-row sm:items-center justify-between gap-4"
      >
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Прокси</h1>
          <p className="text-muted-foreground mt-1">Управление прокси-серверами</p>
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
            onClick={() => { setModalMode('bulk'); setIsModalOpen(true); }}
            className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
          >
            <Upload size={18} />
            Импорт
          </button>
          <ProxyVendorPanel onAfterImport={fetchProxies} />
          <button
            onClick={() => { setModalMode('single'); setIsModalOpen(true); }}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
          >
            <Plus size={18} weight="bold" />
            Добавить
          </button>
        </div>
      </motion.div>

      <ProxyServiceSection onSync={fetchProxies} />

      {/* Stats Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{proxies.length}</p>
          <p className="text-sm text-muted-foreground">Всего прокси</p>
        </div>
        <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
          <p className="text-3xl font-bold text-emerald-600">{activeCount}</p>
          <p className="text-sm text-muted-foreground">Активных</p>
        </div>
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{isNaN(avgResponse) ? '—' : `${avgResponse}ms`}</p>
          <p className="text-sm text-muted-foreground">Средний отклик</p>
        </div>
      </div>

      {/* Search */}
      <div className="relative">
        <MagnifyingGlass size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Поиск по хосту..."
          className="w-full pl-12 pr-4 py-3.5 rounded-2xl border border-border bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
        />
      </div>

      {/* Proxies Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-44 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : filteredProxies.length === 0 ? (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex flex-col items-center justify-center py-20"
        >
          <div className="w-20 h-20 rounded-3xl bg-muted flex items-center justify-center mb-6">
            <Globe size={40} className="text-muted-foreground" weight="duotone" />
          </div>
          <h3 className="text-xl font-semibold mb-2">Прокси не найдены</h3>
          <p className="text-muted-foreground text-center mb-8 max-w-md">
            Добавьте прокси-серверы для подключения Telegram аккаунтов.
          </p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium"
          >
            <Plus size={18} weight="bold" />
            Добавить прокси
          </button>
        </motion.div>
      ) : (
        <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          <AnimatePresence mode="popLayout">
            {filteredProxies.map((proxy) => (
              <ProxyCard
                key={proxy.id}
                proxy={proxy}
                onCheck={checkProxy}
                onDelete={deleteProxy}
                onRenew={renewProxy}
                onUpdate={handleProxyUpdate}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      <AddProxyModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchProxies}
        initialMode={modalMode}
      />
    </div>
  )
}
