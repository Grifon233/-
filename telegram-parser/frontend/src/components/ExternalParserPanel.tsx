import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Play,
  Stop,
  Trash,
  X,
  SpinnerGap,
  CheckCircle,
  XCircle,
  Clock,
  MagnifyingGlass,
} from '@phosphor-icons/react'
import api from '../services/api'

export type ParserKind = 'monitor' | 'keywords' | 'alert_bot'

interface AccountOption {
  id: number
  phone_number: string
  status: string
  has_session: boolean
}

interface ParserRun {
  id: number
  parser: ParserKind
  status: 'pending' | 'running' | 'stopped' | 'completed' | 'failed'
  result_count: number
  file_path: string | null
  last_error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  config?: Record<string, unknown>
}

export interface ParserPanelConfig {
  parser: ParserKind
  title: string
  subtitle: string
  /** realtime parsers show Stop instead of finishing on their own */
  realtime: boolean
  channelLabel: string
  channelPlaceholder: string
  channelsRequired: boolean
  keywordLabel: string
  keywordPlaceholder: string
  /** which numeric options to render */
  numericFields: { key: string; label: string; def: number; min: number; max: number; step: number }[]
  note?: string
}

const parseServerDate = (s: string): Date => {
  if (!s) return new Date(NaN)
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) return new Date(s)
  return new Date(s + 'Z')
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  pending: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Clock, label: 'Ожидание' },
  running: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: SpinnerGap, label: 'В процессе' },
  stopped: { color: 'text-amber-600', bg: 'bg-amber-500/10', icon: Stop, label: 'Остановлен' },
  completed: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: CheckCircle, label: 'Готово' },
  failed: { color: 'text-red-600', bg: 'bg-red-500/10', icon: XCircle, label: 'Ошибка' },
}

function StatusBadge({ status }: { status: string }) {
  const c = statusConfig[status] || statusConfig.pending
  const Icon = c.icon
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${c.color} ${c.bg}`}>
      <Icon size={12} weight="bold" className={status === 'running' ? 'animate-spin' : ''} />
      {c.label}
    </span>
  )
}

// Split a textarea into a clean list. Commas are separators, except inside
// JS-style regex literals such as /foo,bar/i on the alert-bot tab.
function parseList(raw: string, preserveRegexCommas = false): string[] {
  if (!preserveRegexCommas) {
    return raw
      .split(/[\n,]/)
      .map(s => s.trim())
      .filter(Boolean)
  }

  const parts: string[] = []
  let buf = ''
  let inRegex = false
  let escaped = false
  let atItemStart = true

  for (const ch of raw) {
    if (ch === '\n' || ch === '\r') {
      parts.push(buf)
      buf = ''
      inRegex = false
      escaped = false
      atItemStart = true
      continue
    }

    if (ch === ',' && !inRegex) {
      parts.push(buf)
      buf = ''
      escaped = false
      atItemStart = true
      continue
    }

    if (ch === '/') {
      if (inRegex && !escaped) inRegex = false
      else if (atItemStart) inRegex = true
    }

    buf += ch
    if (!/\s/.test(ch)) atItemStart = false
    escaped = ch === '\\' && !escaped
    if (ch !== '\\') escaped = false
  }

  parts.push(buf)
  return parts.map(s => s.trim()).filter(Boolean)
}

function ResultsModal({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [rows, setRows] = useState<Record<string, string>[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/api/v1/external-parsers/${runId}/results?limit=500`)
      .then(r => setRows(r.data.rows || []))
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [runId])

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-5 border-b border-border/50 shrink-0">
          <h2 className="text-lg font-semibold">Совпадения запуска #{runId}</h2>
          <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted"><X size={18} /></button>
        </div>
        <div className="overflow-y-auto flex-1 p-2">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <SpinnerGap size={32} className="animate-spin" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-center py-12 text-muted-foreground">Совпадений нет</p>
          ) : (
            <div className="divide-y divide-border/40">
              {rows.map((row, i) => {
                const link = row.link
                return (
                  <div key={i} className="px-3 py-2.5 hover:bg-muted/30 rounded-xl">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground w-6 shrink-0">{i + 1}</span>
                      <span className="text-sm font-medium truncate">
                        {row.channel_title || row.channel || '—'}
                      </span>
                      {row.keyword && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-primary/10 text-primary shrink-0">
                          {row.keyword}
                        </span>
                      )}
                    </div>
                    {row.text && <p className="text-xs text-muted-foreground mt-1 line-clamp-2 pl-8">{row.text}</p>}
                    {link && (
                      <a href={link} target="_blank" rel="noopener noreferrer"
                        className="text-xs text-primary hover:underline truncate block pl-8 mt-0.5">
                        {link}
                      </a>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
        <div className="p-4 border-t border-border/50 shrink-0 text-xs text-muted-foreground text-center">
          Показано до 500 строк
        </div>
      </motion.div>
    </motion.div>
  )
}

export default function ExternalParserPanel({ cfg }: { cfg: ParserPanelConfig }) {
  const [accounts, setAccounts] = useState<AccountOption[]>([])
  const [accountId, setAccountId] = useState<number | ''>('')
  const [channelsRaw, setChannelsRaw] = useState('')
  const [keywordsRaw, setKeywordsRaw] = useState('')
  const [numeric, setNumeric] = useState<Record<string, number>>(
    () => Object.fromEntries(cfg.numericFields.map(f => [f.key, f.def]))
  )
  const [runs, setRuns] = useState<ParserRun[]>([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [viewRunId, setViewRunId] = useState<number | null>(null)

  useEffect(() => {
    api.get('/api/v1/accounts')
      .then(r => setAccounts((r.data as AccountOption[]).filter(a => a.has_session)))
      .catch(() => {})
  }, [])

  const fetchRuns = async (showSpinner = false) => {
    try {
      if (showSpinner) setLoading(true)
      const r = await api.get(`/api/v1/external-parsers?parser=${cfg.parser}`)
      setRuns(r.data)
    } catch {
      if (showSpinner) setRuns([])
    } finally {
      if (showSpinner) setLoading(false)
    }
  }

  useEffect(() => { fetchRuns(true) }, [cfg.parser])

  // Poll while a run is active (realtime runs stay active until stopped).
  useEffect(() => {
    const active = runs.some(r => r.status === 'running' || r.status === 'pending')
    if (!active) return
    const id = setInterval(() => fetchRuns(false), 3000)
    return () => clearInterval(id)
  }, [runs])

  const handleRun = async () => {
    setError('')
    const channels = parseList(channelsRaw)
    const keywords = parseList(keywordsRaw, cfg.parser === 'alert_bot')
    if (cfg.channelsRequired && channels.length === 0) {
      setError(`Укажите ${cfg.channelLabel.toLowerCase()}`)
      return
    }
    if (keywords.length === 0) {
      setError('Укажите хотя бы одно ключевое слово')
      return
    }
    if (!accountId) {
      setError('Выберите аккаунт')
      return
    }
    setSubmitting(true)
    try {
      await api.post('/api/v1/external-parsers', {
        parser: cfg.parser,
        account_id: accountId,
        config: { channels, keywords, ...numeric },
      })
      fetchRuns(true)
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось запустить парсер')
    } finally {
      setSubmitting(false)
    }
  }

  const handleStop = async (id: number) => {
    try { await api.post(`/api/v1/external-parsers/${id}/stop`) } catch { /* ignore */ }
    fetchRuns(true)
  }

  const handleDelete = async (id: number) => {
    try { await api.delete(`/api/v1/external-parsers/${id}`) } catch { /* ignore */ }
    fetchRuns(true)
  }

  return (
    <div className="space-y-8">
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-3xl font-bold tracking-tight">{cfg.title}</h1>
        <p className="text-muted-foreground mt-1">{cfg.subtitle}</p>
      </motion.div>

      {/* Config form */}
      <div className="bg-card rounded-2xl border border-border/50 p-6 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <div className="space-y-2">
            <label className="text-sm font-medium">{cfg.channelLabel}</label>
            <textarea
              value={channelsRaw}
              onChange={e => setChannelsRaw(e.target.value)}
              placeholder={cfg.channelPlaceholder}
              rows={4}
              className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none text-sm resize-y"
            />
            <p className="text-[11px] text-muted-foreground">По одному на строку или через запятую.</p>
          </div>
          <div className="space-y-2">
            <label className="text-sm font-medium">{cfg.keywordLabel}</label>
            <textarea
              value={keywordsRaw}
              onChange={e => setKeywordsRaw(e.target.value)}
              placeholder={cfg.keywordPlaceholder}
              rows={4}
              className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none text-sm resize-y"
            />
            <p className="text-[11px] text-muted-foreground">По одному на строку или через запятую.</p>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Аккаунт</label>
            <select
              value={accountId}
              onChange={e => setAccountId(e.target.value ? parseInt(e.target.value) : '')}
              className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none text-sm"
            >
              <option value="">— выберите аккаунт —</option>
              {accounts.map(a => (
                <option key={a.id} value={a.id}>{a.phone_number} · {a.status}</option>
              ))}
            </select>
          </div>
          {cfg.numericFields.map(f => (
            <div key={f.key} className="space-y-2">
              <label className="text-sm font-medium">{f.label}</label>
              <input
                type="number"
                value={numeric[f.key]}
                min={f.min}
                max={f.max}
                step={f.step}
                onChange={e => setNumeric(prev => ({ ...prev, [f.key]: Number(e.target.value) }))}
                className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none text-sm"
              />
            </div>
          ))}
        </div>

        {cfg.note && (
          <p className="text-xs text-muted-foreground bg-muted/40 px-3 py-2 rounded-lg">{cfg.note}</p>
        )}
        {error && (
          <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 text-sm">{error}</div>
        )}

        <button
          onClick={handleRun}
          disabled={submitting}
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
        >
          {submitting ? 'Запуск…' : 'Запустить'}
          <Play size={18} weight="fill" />
        </button>
      </div>

      {/* Runs list */}
      <div>
        <h2 className="text-lg font-semibold mb-3">Запуски</h2>
        {loading ? (
          <div className="space-y-3">{[...Array(3)].map((_, i) => <div key={i} className="h-16 bg-muted rounded-2xl animate-pulse" />)}</div>
        ) : runs.length === 0 ? (
          <p className="text-muted-foreground text-sm py-8 text-center">Запусков ещё не было</p>
        ) : (
          <div className="bg-card rounded-2xl border border-border/50 divide-y divide-border/30">
            {runs.map(run => (
              <div key={run.id} className="flex items-center gap-3 px-5 py-3.5 hover:bg-muted/30 transition-colors">
                <span className="text-xs text-muted-foreground w-10 shrink-0">#{run.id}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={run.status} />
                    <span className="text-sm font-semibold tabular-nums">{run.result_count.toLocaleString()} совпадений</span>
                  </div>
                  {run.last_error && (
                    <p className="text-[11px] text-amber-600 truncate mt-1" title={run.last_error}>⚠ {run.last_error}</p>
                  )}
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {parseServerDate(run.created_at).toLocaleString('ru')}
                  </p>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  {(run.status === 'running' || run.status === 'pending') && cfg.realtime && (
                    <button onClick={() => handleStop(run.id)} title="Остановить"
                      className="p-2 rounded-lg bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors">
                      <Stop size={15} weight="fill" />
                    </button>
                  )}
                  {run.result_count > 0 && (
                    <button onClick={() => setViewRunId(run.id)} title="Совпадения"
                      className="p-2 rounded-lg bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors">
                      <MagnifyingGlass size={15} />
                    </button>
                  )}
                  <button onClick={() => handleDelete(run.id)} title="Удалить"
                    className="p-2 rounded-lg bg-red-500/10 text-red-600 hover:bg-red-500/20 transition-colors">
                    <Trash size={15} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <AnimatePresence>
        {viewRunId && <ResultsModal runId={viewRunId} onClose={() => setViewRunId(null)} />}
      </AnimatePresence>
    </div>
  )
}
