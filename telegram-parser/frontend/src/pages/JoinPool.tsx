import { useState, useEffect, useCallback } from 'react'
import api from '../services/api'
import {
  Play, ArrowsClockwise, CheckCircle, Warning, SpinnerGap,
  UserCircle, Shuffle, Clock,
} from '@phosphor-icons/react'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RunnerState {
  running: boolean
  started_at: string | null
  finished_at: string | null
  summary: string
  error: string | null
}

interface AccountSummary {
  account_id: number
  phone: string
  status: string
  assigned_count: number
  joined_count: number
  remaining: number
  join_session_count: number
  join_last_session_at: string | null
  next_batch_size: number
  join_day_target: number | null
  join_day_joined: number
  join_next_episode_at: string | null
}

interface Coverage {
  total_sources: number
  assigned_sources: number
  joined: number
  not_yet_joined: number
  orphaned: number
  coverage_percent: number
  accounts_summary: AccountSummary[]
}

interface DistributeResult {
  accounts?: number
  total_sources?: number
  error?: string
}

interface SourceGroup {
  id: number
  name: string
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    production: 'bg-emerald-500/15 text-emerald-600',
    warming: 'bg-yellow-500/15 text-yellow-600',
    new: 'bg-blue-500/15 text-blue-600',
    banned: 'bg-red-500/15 text-red-600',
    restricted: 'bg-orange-500/15 text-orange-600',
  }
  const lbl: Record<string, string> = {
    production: 'Актив', warming: 'Прогрев', new: 'Новый',
    banned: 'Забанен', restricted: 'Ограничен',
  }
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls[status] ?? 'bg-muted text-muted-foreground'}`}>
      {lbl[status] ?? status}
    </span>
  )
}

function fmt(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' }) +
    ' ' + d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
}

// Шкала прогресса
function ProgressBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min(100, Math.round(value / max * 100)) : 0
  const color = pct === 100 ? 'bg-emerald-500' : pct > 50 ? 'bg-primary' : 'bg-yellow-500'
  return (
    <div className="space-y-1">
      <div className="h-3 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full ${color} rounded-full transition-all duration-500`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span>{value} из {max}</span>
        <span className="font-medium">{pct}%</span>
      </div>
    </div>
  )
}

const JOIN_PROG = [20, 30, 40, 50]
function daysToFinish(remaining: number, sessionCount: number): string {
  if (remaining <= 0) return '✓ Готово'
  let r = remaining, s = sessionCount, days = 0
  while (r > 0 && days < 60) { r -= JOIN_PROG[Math.min(s, JOIN_PROG.length - 1)]; s++; days++ }
  return `~${days} дн.`
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function JoinPool() {
  const projectId = localStorage.getItem('active_project_id') || '1'

  const [runner, setRunner] = useState<RunnerState | null>(null)
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [groups, setGroups] = useState<SourceGroup[]>([])
  const [selectedGroup, setSelectedGroup] = useState<string>('')
  const [loadingRun, setLoadingRun] = useState(false)
  const [loadingDist, setLoadingDist] = useState(false)
  const [loadingCoverage, setLoadingCoverage] = useState(false)
  const [distResult, setDistResult] = useState<DistributeResult | null>(null)

  const fetchRunner = useCallback(async () => {
    try { setRunner((await api.get('/api/v1/join-pool/status')).data) } catch { /* ignore */ }
  }, [])

  const fetchCoverage = useCallback(async () => {
    setLoadingCoverage(true)
    try { setCoverage((await api.get(`/api/v1/join-pool/coverage?project_id=${projectId}`)).data) }
    finally { setLoadingCoverage(false) }
  }, [projectId])

  const fetchGroups = useCallback(async () => {
    try { setGroups((await api.get(`/api/v1/telegram-sources/groups?project_id=${projectId}`)).data || []) }
    catch { /* ignore */ }
  }, [projectId])

  useEffect(() => {
    fetchRunner(); fetchCoverage(); fetchGroups()
    const id = setInterval(fetchRunner, 5000)
    return () => clearInterval(id)
  }, [fetchRunner, fetchCoverage, fetchGroups])

  const triggerRun = async () => {
    setLoadingRun(true)
    try { await api.post(`/api/v1/join-pool/run?project_id=${projectId}`); setTimeout(fetchRunner, 1000) }
    finally { setLoadingRun(false) }
  }

  const triggerDistribute = async () => {
    if (!window.confirm(
      'Перераспределить пул между аккаунтами?\n\nСчётчик сессий и история вступлений будут сброшены.'
    )) return
    setLoadingDist(true); setDistResult(null)
    try {
      const url = selectedGroup
        ? `/api/v1/join-pool/distribute?project_id=${projectId}&group_id=${selectedGroup}`
        : `/api/v1/join-pool/distribute?project_id=${projectId}`
      setDistResult((await api.post(url)).data)
      await fetchCoverage()
    } finally { setLoadingDist(false) }
  }

  // ETA: longest remaining account
  const maxDays = coverage
    ? Math.max(0, ...coverage.accounts_summary.map(a => {
        if (a.remaining <= 0) return 0
        let r = a.remaining, s = a.join_session_count, d = 0
        while (r > 0 && d < 60) { r -= JOIN_PROG[Math.min(s, JOIN_PROG.length - 1)]; s++; d++ }
        return d
      }))
    : 0

  return (
    <div className="space-y-6">

      {/* ── Global progress ── */}
      <div className="rounded-2xl border bg-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="font-semibold text-base">Общий прогресс вступлений</h3>
          <button onClick={fetchCoverage} disabled={loadingCoverage}
            className="p-2 rounded-lg bg-muted text-muted-foreground hover:bg-muted/80 transition-colors disabled:opacity-50">
            <ArrowsClockwise size={16} className={loadingCoverage ? 'animate-spin' : ''} />
          </button>
        </div>

        {loadingCoverage && !coverage
          ? <div className="flex justify-center py-6"><SpinnerGap size={28} className="animate-spin text-primary/50" /></div>
          : coverage ? (
            <>
              <ProgressBar value={coverage.joined} max={coverage.assigned_sources || coverage.total_sources} />

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-1">
                <div className="rounded-xl bg-muted/50 p-3">
                  <p className="text-xs text-muted-foreground">Всего в пуле</p>
                  <p className="text-xl font-bold">{coverage.total_sources}</p>
                </div>
                <div className="rounded-xl bg-emerald-500/10 p-3">
                  <p className="text-xs text-emerald-600">Вступили</p>
                  <p className="text-xl font-bold text-emerald-600">{coverage.joined}</p>
                </div>
                <div className="rounded-xl bg-yellow-500/10 p-3">
                  <p className="text-xs text-yellow-600">Осталось</p>
                  <p className="text-xl font-bold text-yellow-600">{coverage.not_yet_joined}</p>
                </div>
                <div className={`rounded-xl p-3 ${coverage.orphaned > 0 ? 'bg-red-500/10' : 'bg-muted/50'}`}>
                  <p className={`text-xs ${coverage.orphaned > 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                    Без бота
                  </p>
                  <p className={`text-xl font-bold ${coverage.orphaned > 0 ? 'text-red-500' : 'text-muted-foreground'}`}>
                    {coverage.orphaned}
                  </p>
                </div>
              </div>

              {coverage.not_yet_joined > 0 && (
                <div className="flex items-center gap-2 px-4 py-3 rounded-xl bg-primary/5 text-sm">
                  <Clock size={16} className="text-primary shrink-0" />
                  <span>
                    До полного охвата: <span className="font-bold text-primary">~{maxDays} дн.</span>
                    <span className="text-muted-foreground ml-2">(20→30→40→50 вступлений/день, эпизодами по 5-6 раз в полчаса)</span>
                  </span>
                </div>
              )}
            </>
          ) : null
        }
      </div>

      {/* ── Distribute + Run ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* Distribute */}
        <div className="rounded-2xl border bg-card p-5 space-y-4">
          <div>
            <h3 className="font-semibold text-base flex items-center gap-2">
              <Shuffle size={18} className="text-primary" />
              Распределить пул
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              Делит чаты поровну: каждый бот получает свой кусок.
              В итоге каждый чат закреплён за одним ботом.
            </p>
          </div>
          <div className="flex gap-2 flex-wrap">
            <select
              value={selectedGroup}
              onChange={e => setSelectedGroup(e.target.value)}
              className="px-3 py-2 rounded-xl border bg-background text-sm flex-1 min-w-0"
            >
              <option value="">Все источники</option>
              {groups.map(g => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
            <button
              onClick={triggerDistribute}
              disabled={loadingDist}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity shrink-0"
            >
              {loadingDist ? <SpinnerGap size={15} className="animate-spin" /> : <Shuffle size={15} />}
              Распределить
            </button>
          </div>
          {distResult && (
            <div className={`rounded-xl px-3 py-2 text-sm ${distResult.error ? 'bg-red-500/10 text-red-600' : 'bg-emerald-500/10 text-emerald-700'}`}>
              {distResult.error ? `Ошибка: ${distResult.error}` : `Готово: ${distResult.accounts} аккаунтов, ${distResult.total_sources} источников.`}
            </div>
          )}
        </div>

        {/* Runner */}
        <div className="rounded-2xl border bg-card p-5 space-y-4">
          <div>
            <h3 className="font-semibold text-base flex items-center gap-2">
              <Play size={18} weight="fill" className="text-primary" />
              Планировщик
            </h3>
            <p className="text-xs text-muted-foreground mt-1">
              Проверка раз в 10–20 мин. Каждый аккаунт вступает пачками по 5-6 групп примерно раз
              в полчаса (25–35 мин, чтобы не было идеально ровного интервала). Ночью, с 00:00 до 08:00
              по Екатеринбургу — полный сон, никто не вступает. Макс. 50 вступлений/день на аккаунт.
            </p>
          </div>
          <button
            onClick={triggerRun}
            disabled={loadingRun || runner?.running}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-medium disabled:opacity-50 hover:opacity-90 transition-opacity w-full justify-center"
          >
            {runner?.running ? <SpinnerGap size={15} className="animate-spin" /> : <Play size={15} weight="fill" />}
            {runner?.running ? 'Идёт сессия…' : 'Запустить сейчас'}
          </button>
          {runner && (
            <div className={`rounded-xl px-3 py-2 text-xs ${runner.error ? 'bg-red-500/10 text-red-600' : 'bg-muted/60 text-muted-foreground'}`}>
              {runner.running
                ? <span className="flex items-center gap-1.5"><SpinnerGap size={12} className="animate-spin" /> Запущена в {fmt(runner.started_at)}</span>
                : runner.error
                  ? <span className="flex items-center gap-1.5"><Warning size={12} /> {runner.error}</span>
                  : runner.summary
                    ? <span className="flex items-center gap-1.5"><CheckCircle size={12} className="text-emerald-500" /> {runner.summary}</span>
                    : 'Ожидание. Сначала нажмите «Распределить».'
              }
            </div>
          )}
        </div>
      </div>

      {/* ── Per-account progress ── */}
      {coverage && coverage.accounts_summary.length > 0 && (
        <div className="rounded-2xl border bg-card overflow-hidden">
          <div className="px-5 py-4 border-b">
            <h3 className="font-semibold text-base flex items-center gap-2">
              <UserCircle size={18} className="text-primary" />
              Прогресс по аккаунтам
            </h3>
          </div>
          <div className="p-5 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {coverage.accounts_summary.map(acc => {
              const pct = acc.assigned_count > 0
                ? Math.min(100, Math.round(acc.joined_count / acc.assigned_count * 100))
                : 0
              const barColor = pct === 100 ? 'bg-emerald-500' : pct > 50 ? 'bg-primary' : 'bg-yellow-500'
              return (
                <div key={acc.account_id} className="rounded-xl border bg-muted/30 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm">…{acc.phone.slice(-7)}</span>
                    <StatusBadge status={acc.status} />
                  </div>

                  {/* Шкала */}
                  <div className="space-y-1">
                    <div className="h-2.5 rounded-full bg-muted overflow-hidden">
                      <div className={`h-full ${barColor} rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
                    </div>
                    <div className="flex justify-between text-xs text-muted-foreground">
                      <span>{acc.joined_count} из {acc.assigned_count}</span>
                      <span className="font-semibold">{pct}%</span>
                    </div>
                  </div>

                  <div className="flex justify-between text-xs text-muted-foreground">
                    <span>Сегодня: {acc.join_day_joined}/{acc.join_day_target ?? acc.next_batch_size}</span>
                    <span className="font-medium">{daysToFinish(acc.remaining, acc.join_session_count)}</span>
                  </div>

                  {acc.join_last_session_at && (
                    <p className="text-xs text-muted-foreground">Последний эпизод: {fmt(acc.join_last_session_at)}</p>
                  )}
                  {acc.join_next_episode_at && (
                    <p className="text-xs text-muted-foreground">Следующий эпизод: {fmt(acc.join_next_episode_at)}</p>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

    </div>
  )
}
