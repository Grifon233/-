import { useState, useEffect, useCallback } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Play, X, Clock, CheckCircle, XCircle, SpinnerGap,
  ThermometerHot, Users, Lock, Globe, UserCircle,
  Funnel, Broadcast, ArrowRight, Warning,
} from '@phosphor-icons/react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PhaseAccount {
  id: number
  phone_number: string
  status: string
  warmup_phase: number | null
  phase_label: string
  warmup_language: string | null
  warmup_gender: string | null
  warmup_locked: boolean
  next_phase_at: string | null
  hours_remaining: number
  has_pool: boolean
  pool_count: number
  has_channel_template: boolean
  proxy_id: number | null
  proxy_country: string | null
  proxy_label: string | null
  has_session: boolean
  first_name: string | null
  username: string | null
  progress_percent: number
  days_elapsed: number
  total_days: number
}

interface AllAccount {
  id: number
  phone_number: string
  status: string
  has_session: boolean
  proxy_id: number | null
  proxy_country: string | null
  proxy_label: string | null
  warmup_phase: number | null
  warmup_locked: boolean
  first_name?: string | null
  username?: string | null
}

interface SourceGroup { id: number; name: string }
interface ChannelTemplate { id: number; name: string; channel_title: string }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PHASE_COLORS: Record<number, string> = {
  0: 'text-slate-500',
  1: 'text-blue-500',
  2: 'text-yellow-500',
  3: 'text-orange-500',
  4: 'text-emerald-500',
}

const PHASE_BG: Record<number, string> = {
  0: 'bg-slate-500/10',
  1: 'bg-blue-500/10',
  2: 'bg-yellow-500/10',
  3: 'bg-orange-500/10',
  4: 'bg-emerald-500/10',
}

const PHASE_STEPS = [
  { phase: 0, label: 'Ожидание', desc: '24 ч — ничего' },
  { phase: 1, label: 'Профиль', desc: '24 ч — имя, ник, аватар' },
  { phase: 2, label: 'Вступления', desc: '24 ч — 10 каналов + переписка' },
  { phase: 3, label: 'Канал', desc: '48 ч — личный канал + ещё 10' },
  { phase: 4, label: 'Готов', desc: 'production' },
]

function formatHours(h: number) {
  if (h <= 0) return 'скоро'
  if (h < 1) return `${Math.round(h * 60)} мин`
  return `${h} ч`
}

// ISO-3166 alpha-2 code → flag emoji (e.g. "us" → 🇺🇸).
function countryFlag(code: string | null | undefined): string {
  if (!code || code.length !== 2) return '🌐'
  const base = 0x1f1e6
  const cc = code.toUpperCase()
  return String.fromCodePoint(
    base + cc.charCodeAt(0) - 65,
    base + cc.charCodeAt(1) - 65,
  )
}

// Small reusable chip showing the account's country (from its proxy) and proxy host.
function ProxyChips({ country, label }: { country: string | null; label: string | null }) {
  if (!country && !label) {
    return <span className="text-xs text-red-500 flex items-center gap-0.5"><Globe size={10} /> нет прокси</span>
  }
  return (
    <div className="flex items-center gap-2 flex-wrap text-xs">
      {country && (
        <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-muted text-foreground/80 font-medium">
          <span>{countryFlag(country)}</span>{country}
        </span>
      )}
      {label && (
        <span className="inline-flex items-center gap-1 text-muted-foreground" title="Прокси аккаунта">
          <Globe size={10} /> {label}
        </span>
      )}
    </div>
  )
}

function PhaseBadge({ phase }: { phase: number | null }) {
  if (phase === null) return <span className="text-xs text-muted-foreground">Не в прогреве</span>
  const step = PHASE_STEPS[phase] ?? PHASE_STEPS[4]
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${PHASE_COLORS[phase] ?? ''} ${PHASE_BG[phase] ?? ''}`}>
      {step.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Settings panel (shown when accounts are selected)
// ---------------------------------------------------------------------------

interface WarmupSettings {
  language: 'ru' | 'en'
  gender: 'male' | 'female'
  pool_ids: number[]
  channel_template_id: number | null
}

function SettingsPanel({
  selectedCount,
  settings,
  onChange,
  sourceGroups,
  templates,
  onStart,
  starting,
}: {
  selectedCount: number
  settings: WarmupSettings
  onChange: (s: WarmupSettings) => void
  sourceGroups: SourceGroup[]
  templates: ChannelTemplate[]
  onStart: () => void
  starting: boolean
}) {
  const set = (patch: Partial<WarmupSettings>) => onChange({ ...settings, ...patch })

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="rounded-2xl border border-primary/30 bg-primary/5 p-5 space-y-4"
    >
      <div className="flex items-center justify-between">
        <p className="font-semibold text-sm">
          Настройки прогрева — {selectedCount} аккаунтов
        </p>
        <button
          onClick={onStart}
          disabled={starting}
          className="px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium flex items-center gap-2 disabled:opacity-50"
        >
          {starting ? <SpinnerGap size={16} className="animate-spin" /> : <Play size={16} weight="fill" />}
          Начать прогрев
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {/* Language */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
            <Globe size={11} /> Язык профиля
          </label>
          <div className="flex gap-2">
            {(['ru', 'en'] as const).map(l => (
              <button
                key={l}
                onClick={() => set({ language: l })}
                className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                  settings.language === l
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'border-border hover:bg-muted'
                }`}
              >
                {l === 'ru' ? '🇷🇺 Русский' : '🇬🇧 English'}
              </button>
            ))}
          </div>
        </div>

        {/* Gender */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
            <UserCircle size={11} /> Пол
          </label>
          <div className="flex gap-2">
            {(['male', 'female'] as const).map(g => (
              <button
                key={g}
                onClick={() => set({ gender: g })}
                className={`flex-1 py-2 rounded-xl text-sm font-medium border transition-colors ${
                  settings.gender === g
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'border-border hover:bg-muted'
                }`}
              >
                {g === 'male' ? '👨 Мужской' : '👩 Женский'}
              </button>
            ))}
          </div>
        </div>

        {/* Pool */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
            <Funnel size={11} /> Пул каналов (необязательно)
          </label>
          <select
            value={settings.pool_ids[0] ?? ''}
            onChange={e => set({ pool_ids: e.target.value ? [Number(e.target.value)] : [] })}
            className="w-full px-3 py-2 rounded-xl border border-border bg-background text-sm focus:border-primary outline-none"
          >
            <option value="">— без пула —</option>
            {sourceGroups.map(g => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </div>

        {/* Channel template */}
        <div className="space-y-1.5">
          <label className="text-xs text-muted-foreground uppercase tracking-wide flex items-center gap-1">
            <Broadcast size={11} /> Шаблон канала (необязательно)
          </label>
          <select
            value={settings.channel_template_id ?? ''}
            onChange={e => set({ channel_template_id: e.target.value ? Number(e.target.value) : null })}
            className="w-full px-3 py-2 rounded-xl border border-border bg-background text-sm focus:border-primary outline-none"
          >
            <option value="">— без личного канала —</option>
            {templates.map(t => (
              <option key={t.id} value={t.id}>{t.name} — {t.channel_title}</option>
            ))}
          </select>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Аккаунты будут заблокированы от других задач до завершения прогрева (~5 суток).
        Имена и юзернеймы генерируются автоматически под выбранный язык и пол.
      </p>
    </motion.div>
  )
}

// ---------------------------------------------------------------------------
// Account card
// ---------------------------------------------------------------------------

function AccountCard({
  account,
  selected,
  onToggle,
  onCancel,
}: {
  account: AllAccount
  selected: boolean
  onToggle: () => void
  onCancel: () => void
}) {
  const inWarmup = account.warmup_phase !== null && account.warmup_phase < 4
  const done = account.warmup_phase === 4
  const canSelect = account.has_session && account.proxy_id && !inWarmup && !done

  return (
    <div className={`bg-card p-4 rounded-2xl border transition-colors ${
      selected ? 'border-primary/60 bg-primary/5' : 'border-border/50'
    } ${account.warmup_locked ? 'opacity-80' : ''}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <input
            type="checkbox"
            checked={selected}
            disabled={!canSelect}
            onChange={onToggle}
            className="mt-1 h-4 w-4 rounded border-border shrink-0"
            title={canSelect ? 'Выбрать' : inWarmup ? 'Уже в прогреве' : 'Нужны сессия и прокси'}
          />
          <div className="min-w-0">
            <p className="font-medium text-sm truncate">{account.phone_number}</p>
            {(account.first_name || account.username) && (
              <p className="text-xs text-muted-foreground truncate">
                {account.first_name}{account.username ? ` @${account.username}` : ''}
              </p>
            )}
            <div className="flex items-center gap-2 mt-1">
              <PhaseBadge phase={account.warmup_phase} />
              {account.warmup_locked && (
                <span className="text-xs text-amber-500 flex items-center gap-0.5">
                  <Lock size={10} /> заблокирован
                </span>
              )}
              {done && <span className="text-xs text-emerald-600 flex items-center gap-0.5"><CheckCircle size={10} /> готов</span>}
            </div>
            <div className="mt-1.5">
              <ProxyChips country={account.proxy_country} label={account.proxy_label} />
            </div>
            {!account.has_session && <p className="text-xs text-red-500 mt-1">нет сессии</p>}
          </div>
        </div>
        {inWarmup && (
          <button
            onClick={onCancel}
            title="Отменить прогрев"
            className="p-1.5 rounded-lg text-muted-foreground hover:text-red-500 hover:bg-red-500/10 transition-colors shrink-0"
          >
            <X size={14} />
          </button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Phase progress bar (for accounts in warmup)
// ---------------------------------------------------------------------------

function PhaseProgressCard({ account }: { account: PhaseAccount }) {
  const phase = account.warmup_phase ?? 0

  return (
    <div className="bg-card rounded-2xl border border-border/50 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="font-medium text-sm">{account.phone_number}</p>
        <PhaseBadge phase={phase} />
      </div>

      <ProxyChips country={account.proxy_country} label={account.proxy_label} />

      {/* Overall progress scale */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">
            Прогрет на <span className="font-semibold text-foreground">{account.progress_percent}%</span>
          </span>
          <span className="text-muted-foreground">
            день <span className="font-semibold text-foreground">{account.days_elapsed}</span> из {account.total_days}
          </span>
        </div>
        <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${
              account.progress_percent >= 100 ? 'bg-emerald-500' : 'bg-primary'
            }`}
            style={{ width: `${Math.max(2, account.progress_percent)}%` }}
          />
        </div>
      </div>

      {account.hours_remaining > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Clock size={12} />
          Следующий этап через <span className="font-semibold">{formatHours(account.hours_remaining)}</span>
        </div>
      )}

      {/* Step dots */}
      <div className="flex items-center gap-1">
        {PHASE_STEPS.map((step, i) => (
          <div key={i} className="flex items-center gap-1 flex-1">
            <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 transition-colors ${
              i < phase ? 'bg-emerald-500 text-white'
              : i === phase ? 'bg-primary text-primary-foreground ring-2 ring-primary/30'
              : 'bg-muted text-muted-foreground'
            }`}>
              {i < phase ? '✓' : i + 1}
            </div>
            {i < PHASE_STEPS.length - 1 && (
              <div className={`h-0.5 flex-1 rounded ${i < phase ? 'bg-emerald-500' : 'bg-muted'}`} />
            )}
          </div>
        ))}
      </div>

      <div className="flex gap-3 text-xs text-muted-foreground">
        {account.has_pool && <span className="flex items-center gap-1"><Funnel size={10} /> пул {account.pool_count} каналов</span>}
        {account.has_channel_template && <span className="flex items-center gap-1"><Broadcast size={10} /> шаблон канала</span>}
        {account.warmup_language && <span>{account.warmup_language.toUpperCase()} / {account.warmup_gender === 'male' ? '👨' : '👩'}</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function Warmup() {
  const [allAccounts, setAllAccounts] = useState<AllAccount[]>([])
  const [phaseAccounts, setPhaseAccounts] = useState<PhaseAccount[]>([])
  const [sourceGroups, setSourceGroups] = useState<SourceGroup[]>([])
  const [templates, setTemplates] = useState<ChannelTemplate[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedIds, setSelectedIds] = useState<number[]>([])
  const [settings, setSettings] = useState<WarmupSettings>({
    language: 'ru',
    gender: 'male',
    pool_ids: [],
    channel_template_id: null,
  })
  const [starting, setStarting] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const fetchData = useCallback(async () => {
    try {
      const [accRes, phaseRes] = await Promise.all([
        api.get('/api/v1/accounts/warmup-status'),
        api.get('/api/v1/phase-warmup/status'),
      ])
      const raw: any[] = accRes.data?.accounts ?? []
      setAllAccounts(raw.map(a => ({
        id: a.id,
        phone_number: a.phone_number,
        status: a.status,
        has_session: Boolean(a.has_session),
        proxy_id: a.proxy_id ?? null,
        proxy_country: a.proxy_country ?? null,
        proxy_label: a.proxy_label ?? null,
        warmup_phase: a.warmup_phase ?? null,
        warmup_locked: Boolean(a.warmup_locked),
        first_name: a.first_name ?? null,
        username: a.username ?? null,
      })))
      setPhaseAccounts(phaseRes.data?.accounts ?? [])
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Ошибка загрузки')
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchMeta = useCallback(async () => {
    try {
      const [sgRes, tmplRes] = await Promise.all([
        api.get('/api/v1/telegram-sources/groups'),
        api.get('/api/v1/personal-channel-templates/'),
      ])
      setSourceGroups(sgRes.data || [])
      setTemplates(tmplRes.data || [])
    } catch { /* not critical */ }
  }, [])

  // Tick on page load + every 30 min
  const runTick = useCallback(async () => {
    try {
      const res = await api.post('/api/v1/phase-warmup/tick')
      if (res.data?.advanced > 0) {
        await fetchData()
      }
    } catch { /* silent */ }
  }, [fetchData])

  useEffect(() => {
    fetchData()
    fetchMeta()
    runTick()
    const tickInterval = setInterval(runTick, 30 * 60 * 1000)
    return () => clearInterval(tickInterval)
  }, [fetchData, fetchMeta, runTick])

  const toggle = (id: number) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const selectAll = () => {
    const eligible = allAccounts
      .filter(a => a.has_session && a.proxy_id && a.warmup_phase === null)
      .map(a => a.id)
    setSelectedIds(eligible)
  }

  const startWarmup = async () => {
    if (selectedIds.length === 0) return
    setStarting(true)
    setError('')
    setMessage('')
    try {
      const sourceGroupId = settings.pool_ids[0]
      let poolIds: number[] = []
      if (sourceGroupId) {
        // resolve group → source ids
        const sg = sourceGroups.find(g => g.id === sourceGroupId)
        // If the backend returns pool_ids directly — otherwise just pass group id
        poolIds = [sourceGroupId]
      }
      const res = await api.post('/api/v1/phase-warmup/start', {
        account_ids: selectedIds,
        language: settings.language,
        gender: settings.gender,
        pool_ids: settings.pool_ids,
        channel_template_id: settings.channel_template_id,
      })
      setMessage(`Прогрев запущен: ${res.data.started} аккаунтов. Пропущено (уже в прогреве): ${res.data.skipped}.`)
      setSelectedIds([])
      await fetchData()
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Ошибка запуска')
    } finally {
      setStarting(false)
    }
  }

  const cancelWarmup = async (accountId: number) => {
    try {
      await api.post(`/api/v1/phase-warmup/cancel/${accountId}`)
      await fetchData()
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || 'Ошибка отмены')
    }
  }

  const activePhaseAccounts = phaseAccounts.filter(a => (a.warmup_phase ?? 0) < 4)
  const inWarmupIds = new Set(allAccounts.filter(a => a.warmup_phase !== null && a.warmup_phase < 4).map(a => a.id))
  const notInWarmup = allAccounts.filter(a => a.warmup_phase === null || a.warmup_phase === 4)

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <SpinnerGap size={40} className="animate-spin text-primary/50" />
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-10">
      {/* Header */}
      <div className="flex justify-between items-end flex-wrap gap-4">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight">Прогрев аккаунтов</h1>
          <p className="text-muted-foreground mt-1">Пошаговый прогрев: 5 суток, 4 этапа</p>
        </div>
        <div className="flex gap-3">
          <button
            onClick={selectAll}
            className="px-4 py-2 rounded-xl bg-card border border-border text-sm font-medium hover:bg-muted transition-colors"
          >
            Выделить все новые
          </button>
        </div>
      </div>

      {/* Timeline explanation */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1">
        {PHASE_STEPS.map((step, i) => (
          <div key={i} className="flex items-center gap-2 shrink-0">
            <div className="text-center">
              <div className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold mx-auto ${PHASE_BG[step.phase]} ${PHASE_COLORS[step.phase]}`}>
                {i + 1}
              </div>
              <p className="text-[11px] font-medium mt-1">{step.label}</p>
              <p className="text-[10px] text-muted-foreground">{step.desc}</p>
            </div>
            {i < PHASE_STEPS.length - 1 && <ArrowRight size={14} className="text-muted-foreground shrink-0" />}
          </div>
        ))}
      </div>

      {/* Notifications */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600 flex items-start gap-2">
          <Warning size={16} className="shrink-0 mt-0.5" /> {error}
        </div>
      )}
      {message && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-700">
          {message}
        </div>
      )}

      {/* Settings panel — shown when accounts are selected */}
      <AnimatePresence>
        {selectedIds.length > 0 && (
          <SettingsPanel
            selectedCount={selectedIds.length}
            settings={settings}
            onChange={setSettings}
            sourceGroups={sourceGroups}
            templates={templates}
            onStart={startWarmup}
            starting={starting}
          />
        )}
      </AnimatePresence>

      {/* Active warmup progress */}
      {activePhaseAccounts.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <ThermometerHot size={20} className="text-orange-500" />
            В прогреве ({activePhaseAccounts.length})
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {activePhaseAccounts.map(a => (
              <PhaseProgressCard key={a.id} account={a} />
            ))}
          </div>
        </section>
      )}

      {/* All accounts list */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <Users size={20} />
          Все аккаунты ({allAccounts.length})
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          {allAccounts.map(account => (
            <AccountCard
              key={account.id}
              account={account}
              selected={selectedIds.includes(account.id)}
              onToggle={() => toggle(account.id)}
              onCancel={() => cancelWarmup(account.id)}
            />
          ))}
        </div>
        {allAccounts.length === 0 && (
          <div className="text-center py-16 text-muted-foreground">
            <Users size={48} className="mx-auto mb-3 opacity-30" />
            <p>Нет аккаунтов. Добавьте их в разделе «Аккаунты».</p>
          </div>
        )}
      </section>
    </div>
  )
}
