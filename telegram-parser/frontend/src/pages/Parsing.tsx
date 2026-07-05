import { forwardRef, useState, useEffect } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  MagnifyingGlass,
  Download,
  Trash,
  Play,
  X,
  Users,
  ChatText,
  CheckCircle,
  XCircle,
  Clock,
  SpinnerGap,
  ChatCircleDots,
  Hash,
  Globe
} from '@phosphor-icons/react'

interface ParsingTask {
  id: number
  type: 'users' | 'messages' | 'comments' | 'chat_search' | 'tgstat_search'
  target: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  result_count: number
  file_path: string | null
  created_at: string
  params?: Record<string, unknown>
}

interface AccountOption {
  id: number
  phone_number: string
  status: string
  has_session: boolean
}

// Backend stores timestamps with datetime.utcnow() — they arrive WITHOUT a
// timezone designator (e.g. "2026-06-12T16:58:27"). `new Date()` would parse
// that as LOCAL time, shifting it by the user's UTC offset. That broke the
// auto-poll "recent active task" guard (tasks looked hours old → polling
// never started → UI froze on "ожидание") and skewed the displayed time.
// Appending 'Z' forces correct UTC interpretation.
const parseServerDate = (s: string): Date => {
  if (!s) return new Date(NaN)
  // Already has timezone info (Z or ±HH:MM)? Use as-is.
  if (/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)) return new Date(s)
  return new Date(s + 'Z')
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType }> = {
  pending: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Clock },
  running: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: SpinnerGap },
  completed: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: CheckCircle },
  failed: { color: 'text-red-600', bg: 'bg-red-500/10', icon: XCircle },
}

const typeConfig: Record<string, { icon: React.ElementType; label: string; hint: string }> = {
  members: { icon: Users, label: 'Авторы / Участники', hint: 'Группа → собирает участников. Канал → собирает авторов комментариев.' },
  messages: { icon: ChatText, label: 'Поиск по сообщениям', hint: 'Ищет сообщения с ключевыми словами внутри указанной группы/канала и собирает их авторов' },
  chat_search: { icon: Hash, label: 'Найти группы/каналы', hint: 'Поиск групп и каналов по ключевым словам через Telegram. Результат — ссылки на группы.' },
  tgstat_search: { icon: Globe, label: 'TGStat поиск', hint: 'Поиск через базу TGStat (нужен API-токен). Без аккаунта Telegram.' },
}

function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status] || statusConfig.pending
  const Icon = config.icon

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      <Icon size={12} weight="bold" className={status === 'running' ? 'animate-spin' : ''} />
      {status === 'completed' ? 'Готово' : status === 'failed' ? 'Ошибка' : status === 'running' ? 'В процессе' : 'Ожидание'}
    </span>
  )
}

function CreateTaskModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  // 'members' is a UI-only type that maps to 'users' or 'comments' based on membersMode
  const [type, setType] = useState<'members' | 'messages' | 'chat_search' | 'tgstat_search'>('members')
  const [membersMode, setMembersMode] = useState<'group' | 'channel'>('group')
  const [target, setTarget] = useState('')
  const [messagesGroup, setMessagesGroup] = useState('')
  const [limit, setLimit] = useState(1000)
  const [chatType, setChatType] = useState<'all' | 'channel' | 'group'>('all')
  const [onlyWithDiscussion, setOnlyWithDiscussion] = useState(true)
  const [minParticipants, setMinParticipants] = useState(150)
  const [tgstatCountry, setTgstatCountry] = useState('')
  const [tgstatLanguage, setTgstatLanguage] = useState('russian')
  const [tgstatCategory, setTgstatCategory] = useState('')
  const [accountId, setAccountId] = useState<number | ''>('')
  const [accounts, setAccounts] = useState<AccountOption[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (isOpen) {
      api.get('/api/v1/accounts').then(r => {
        setAccounts((r.data as AccountOption[]).filter(a => a.has_session))
      }).catch(() => {})
    }
  }, [isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setSubmitting(true)
    try {
      const params: Record<string, number | string | boolean> = { limit }
      // Resolve actual backend type from UI type
      let actualType: string = type
      if (type === 'members') {
        if (membersMode === 'channel') {
          actualType = 'comments'
          params.post_limit = 20
          params.per_post_limit = 200
        } else {
          actualType = 'users'
        }
      }
      if (type === 'messages' && messagesGroup) {
        params.sources = messagesGroup
      }
      if (type === 'chat_search') {
        params.chat_type = chatType
        params.only_with_discussion = onlyWithDiscussion
        params.per_keyword_limit = 200
        params.expand_queries = true
        params.min_participants = Math.max(150, minParticipants)
      }
      if (type === 'tgstat_search') {
        params.peer_type = chatType === 'group' ? 'chat' : chatType
        params.per_keyword_limit = 100
        params.min_participants = Math.max(150, minParticipants)
        if (tgstatCountry) params.country = tgstatCountry
        if (tgstatLanguage) params.language = tgstatLanguage
        if (tgstatCategory) params.category = tgstatCategory
      }
      const body: Record<string, unknown> = { type: actualType, target, params }
      if (accountId) body.account_id = accountId
      await api.post('/api/v1/parsing', body)
      onSuccess()
      onClose()
      setTarget('')
      setMessagesGroup('')
    } catch (err: any) {
      const detail = err.response?.data?.detail
      setError(typeof detail === 'string' ? detail : JSON.stringify(detail) || 'Ошибка при создании задачи')
    } finally {
      setSubmitting(false)
    }
  }

  const getTargetPlaceholder = () => {
    switch (type) {
      case 'members': return membersMode === 'group'
        ? '@group_name или ссылка на группу'
        : '@channel или ссылка на канал с открытыми комментариями'
      case 'messages': return 'ключевое слово 1, ключевое слово 2'
      case 'chat_search': return 'бьюти мастер, маникюр, тату, ногтевой, lash, brow'
      case 'tgstat_search': return 'бьюти мастер, маникюр, тату салон, ногтевая студия, lash maker, brow master'
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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50 shrink-0">
              <h2 className="text-xl font-semibold">Новая задача парсинга</h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="flex flex-col flex-1 overflow-hidden">
              <div className="overflow-y-auto flex-1 p-6 space-y-6">

              {/* Type selector */}
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(typeConfig).map(([key, config]) => {
                  const Icon = config.icon
                  return (
                    <button
                      key={key}
                      type="button"
                      onClick={() => setType(key as any)}
                      title={config.hint}
                      className={`p-3 rounded-2xl border transition-all flex flex-col items-center gap-1.5 text-center ${
                        type === key
                          ? 'bg-primary/10 border-primary/30 text-primary'
                          : 'bg-card border-border hover:border-border/80'
                      }`}
                    >
                      <Icon size={22} weight={type === key ? 'fill' : 'regular'} />
                      <span className="text-[11px] font-medium leading-tight">{config.label}</span>
                    </button>
                  )
                })}
              </div>

              {type && (
                <p className="text-xs text-muted-foreground bg-muted/40 px-3 py-2 rounded-lg">
                  {typeConfig[type].hint}
                </p>
              )}

              {/* Mode toggle for members type */}
              {type === 'members' && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Режим сбора</label>
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { v: 'group', l: 'Группа (участники)' },
                      { v: 'channel', l: 'Канал (авторы комментариев)' },
                    ].map(opt => (
                      <button
                        key={opt.v}
                        type="button"
                        onClick={() => setMembersMode(opt.v as any)}
                        className={`py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                          membersMode === opt.v
                            ? 'bg-primary/10 border border-primary/30 text-primary'
                            : 'bg-card border border-border hover:border-border/80'
                        }`}
                      >
                        {opt.l}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Target input */}
              <div className="space-y-2">
                <label className="text-sm font-medium">
                  {type === 'messages' ? 'Ключевые слова' : 'Цель'}
                </label>
                <input
                  type="text"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder={getTargetPlaceholder()}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  required
                />
              </div>

              {/* Group/channel selector for messages type */}
              {type === 'messages' && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Группа или канал (необязательно)</label>
                  <input
                    type="text"
                    value={messagesGroup}
                    onChange={(e) => setMessagesGroup(e.target.value)}
                    placeholder="@group_name или ссылка (оставьте пустым для глобального поиска)"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  />
                </div>
              )}

              {/* Account selector */}
              {type !== 'tgstat_search' && (
                <div className="space-y-2">
                  <label className="text-sm font-medium">Аккаунт-бот (необязательно)</label>
                  <select
                    value={accountId}
                    onChange={(e) => setAccountId(e.target.value ? parseInt(e.target.value) : '')}
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  >
                    <option value="">— авто (любой доступный) —</option>
                    {accounts.map(acc => (
                      <option key={acc.id} value={acc.id}>
                        {acc.phone_number} · {acc.status}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Limit slider */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center justify-between">
                  <span>Максимум результатов</span>
                  <span className="text-primary font-semibold">{limit.toLocaleString()}</span>
                </label>
                <input
                  type="range"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  min="100"
                  max="50000"
                  step="100"
                  className="w-full accent-primary"
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>100</span>
                  <span>50,000</span>
                </div>
                {type === 'chat_search' && (
                  <p className="text-xs text-muted-foreground">
                    Telegram обычно отдаёт только 8–10 результатов на один поисковый запрос.
                    Углублённый поиск автоматически проверит до 23 связанных формулировок
                    для каждого ключевого слова и объединит результаты.
                  </p>
                )}
              </div>

              {/* Error message */}
              {error && (
                <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 text-sm">
                  {error}
                </div>
              )}

              {type === 'chat_search' && (
                <div className="space-y-3 p-4 rounded-2xl bg-muted/40 border border-border/40">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Тип чата</label>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { v: 'all', l: 'Любой' },
                        { v: 'channel', l: 'Каналы' },
                        { v: 'group', l: 'Группы/чаты' },
                      ].map((opt) => (
                        <button
                          key={opt.v}
                          type="button"
                          onClick={() => setChatType(opt.v as any)}
                          className={`py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                            chatType === opt.v
                              ? 'bg-primary/10 border border-primary/30 text-primary'
                              : 'bg-card border border-border hover:border-border/80'
                          }`}
                        >
                          {opt.l}
                        </button>
                      ))}
                    </div>
                  </div>
                  <label className="flex items-start gap-2 cursor-pointer text-sm">
                    <input
                      type="checkbox"
                      checked={onlyWithDiscussion}
                      onChange={(e) => setOnlyWithDiscussion(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-border text-primary focus:ring-primary/20"
                    />
                    <span>
                      Только с открытыми комментариями
                      <span className="block text-xs text-muted-foreground mt-0.5">
                        Каналы останутся только с привязанной дискуссией. Обычные группы и чаты сохраняются,
                        потому что писать можно непосредственно в них.
                      </span>
                    </span>
                  </label>
                  <div className="space-y-1.5">
                    <label className="text-sm font-medium">
                      Минимум участников или подписчиков
                    </label>
                    <input
                      type="number"
                      min={150}
                      step={50}
                      value={minParticipants}
                      onChange={(e) => setMinParticipants(Math.max(150, Number(e.target.value) || 150))}
                      className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                    />
                    <p className="text-xs text-muted-foreground">
                      В итоговый отчёт не попадут каналы и группы меньше чем со 150 участниками.
                    </p>
                  </div>
                </div>
              )}

              {type === 'tgstat_search' && (
                <div className="space-y-3 p-4 rounded-2xl bg-muted/40 border border-border/40">
                  <div className="space-y-2">
                    <label className="text-sm font-medium">Тип чата</label>
                    <div className="grid grid-cols-3 gap-2">
                      {[
                        { v: 'all', l: 'Любой' },
                        { v: 'channel', l: 'Каналы' },
                        { v: 'group', l: 'Группы' },
                      ].map((opt) => (
                        <button
                          key={opt.v}
                          type="button"
                          onClick={() => setChatType(opt.v as any)}
                          className={`py-2 px-3 rounded-lg text-xs font-medium transition-all ${
                            chatType === opt.v
                              ? 'bg-primary/10 border border-primary/30 text-primary'
                              : 'bg-card border border-border hover:border-border/80'
                          }`}
                        >
                          {opt.l}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-muted-foreground">
                        Страна (ISO код)
                      </label>
                      <input
                        type="text"
                        value={tgstatCountry}
                        onChange={(e) => setTgstatCountry(e.target.value)}
                        placeholder="ru, ua, kz, by..."
                        className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <label className="text-xs font-medium text-muted-foreground">
                        Язык
                      </label>
                      <input
                        type="text"
                        value={tgstatLanguage}
                        onChange={(e) => setTgstatLanguage(e.target.value)}
                        placeholder="russian, english..."
                        className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Категория (необязательно)
                    </label>
                    <input
                      type="text"
                      value={tgstatCategory}
                      onChange={(e) => setTgstatCategory(e.target.value)}
                      placeholder="beauty, health, business..."
                      className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                    />
                    <p className="text-xs text-muted-foreground">
                      Полный список — <code className="px-1 py-0.5 rounded bg-muted">/database/categories</code>
                    </p>
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-muted-foreground">
                      Минимум участников или подписчиков
                    </label>
                    <input
                      type="number"
                      min={150}
                      step={50}
                      value={minParticipants}
                      onChange={(e) => setMinParticipants(Math.max(150, Number(e.target.value) || 150))}
                      className="w-full px-3 py-2 rounded-lg border border-border bg-card text-sm"
                    />
                  </div>
                  <p className="text-xs text-amber-600 bg-amber-500/10 px-3 py-2 rounded-lg border border-amber-500/20">
                    Нужен <code className="px-1 py-0.5 rounded bg-amber-500/20">TGSTAT_API_TOKEN</code> в
                    backend/.env. Получить бесплатно (план S) на{' '}
                    <a
                      href="https://tgstat.ru/my/profile"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline"
                    >
                      tgstat.ru/my/profile
                    </a>.
                  </p>
                </div>
              )}

              </div>{/* end scrollable */}
              <div className="flex gap-3 p-6 pt-4 border-t border-border/50 shrink-0">
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
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting ? 'Запуск...' : 'Запустить'}
                  <Play size={18} weight="fill" />
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const taskTypeDisplayConfig: Record<string, { icon: React.ElementType; label: string }> = {
  users: { icon: Users, label: 'Участники группы' },
  comments: { icon: ChatCircleDots, label: 'Авторы комментариев' },
  messages: { icon: ChatText, label: 'Поиск по сообщениям' },
  chat_search: { icon: Hash, label: 'Найти группы/каналы' },
  tgstat_search: { icon: Globe, label: 'TGStat поиск' },
}

// COLS: [checkbox 20px] [icon 44px] [info 1fr] [status 130px] [results 72px] [date 100px] [actions 96px]
// IMPORTANT: header and each TaskRow must use the SAME grid definition.
// Using "auto" for actions caused misalignment because different rows had
// different numbers of rendered buttons, changing the auto column width and
// shifting all preceding columns. Fixed width + invisible placeholders solve this.
const TABLE_COLS = 'grid-cols-[20px_44px_minmax(0,1fr)_130px_72px_100px_96px]'

interface TaskRowProps {
  task: ParsingTask
  onDelete: () => void
  onView: () => void
  selected?: boolean
  onToggleSelect?: (id: number) => void
}

const TaskRow = forwardRef<HTMLDivElement, TaskRowProps>(function TaskRow({
  task,
  onDelete,
  onView,
  selected,
  onToggleSelect,
}, ref) {
  const type = taskTypeDisplayConfig[task.type] || taskTypeDisplayConfig.users
  const TypeIcon = type.icon
  const isCompleted = task.status === 'completed'
  const hasFile = Boolean(task.file_path)

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className={`grid ${TABLE_COLS} items-center gap-3 px-5 py-3.5 hover:bg-muted/30 transition-colors group border-b border-border/30 last:border-0`}
    >
      {/* Checkbox */}
      <input
        type="checkbox"
        checked={!!selected}
        onChange={() => onToggleSelect?.(task.id)}
        className="h-4 w-4 rounded border-border cursor-pointer"
      />

      {/* Type Icon */}
      <div className="w-9 h-9 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
        <TypeIcon size={18} className="text-primary" weight="duotone" />
      </div>

      {/* Info */}
      <div className="min-w-0">
        <p className="font-medium truncate text-sm">{type?.label ?? task.type}</p>
        <p className="text-xs text-muted-foreground truncate">
          {task.target}
        </p>
        {(() => {
          // While running, show the live progress line in blue; otherwise
          // show any diagnostic (debug_info / last_error) in amber.
          if (task.status === 'running' && task.params?.progress) {
            const msg = String(task.params.progress)
            return (
              <p className="text-[10px] text-blue-600 truncate mt-0.5 flex items-center gap-1" title={msg}>
                <SpinnerGap size={10} className="animate-spin shrink-0" />
                {msg.slice(0, 90)}
              </p>
            )
          }
          const stats = task.params?.search_stats as Record<string, number> | undefined
          if (task.status === 'completed' && stats) {
            return (
              <p className="text-[10px] text-muted-foreground truncate mt-0.5">
                Telegram отдал {stats.telegram_candidates ?? 0} кандидатов за {stats.search_requests ?? 0} запросов
              </p>
            )
          }
          const raw = task.params?.debug_info ?? task.params?.last_error
          if (!raw) return null
          const msg = String(raw)
          return <p className="text-[10px] text-amber-600 truncate mt-0.5" title={msg}>⚠ {msg.slice(0, 90)}</p>
        })()}
      </div>

      {/* Status */}
      <div className="shrink-0">
        <StatusBadge status={task.status} />
      </div>

      {/* Results count */}
      <div className="text-right shrink-0">
        <p className="font-semibold text-sm tabular-nums">{task.result_count.toLocaleString()}</p>
      </div>

      {/* Date */}
      <div className="text-right shrink-0">
        <p className="text-xs text-muted-foreground tabular-nums">
          {parseServerDate(task.created_at).toLocaleDateString('ru', { day: '2-digit', month: '2-digit' })}
        </p>
        <p className="text-[10px] text-muted-foreground/60 tabular-nums">
          {parseServerDate(task.created_at).toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>

      {/* Actions — always 3 button slots, invisible when inapplicable.
          Fixed-width container ensures the column never varies in width. */}
      <div className="flex items-center justify-end gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={onView}
          className={`p-1.5 rounded-lg transition-colors ${isCompleted ? 'bg-blue-500/10 text-blue-600 hover:bg-blue-500/20' : 'invisible'}`}
          title="Просмотр результатов"
        >
          <MagnifyingGlass size={14} />
        </button>
        <button
          className={`p-1.5 rounded-lg transition-colors ${hasFile ? 'bg-primary/10 text-primary hover:bg-primary/20' : 'invisible'}`}
          title="Скачать CSV"
        >
          <Download size={14} />
        </button>
        <button
          onClick={onDelete}
          className="p-1.5 rounded-lg bg-red-500/10 text-red-600 hover:bg-red-500/20 transition-colors"
          title="Удалить"
        >
          <Trash size={14} />
        </button>
      </div>
    </motion.div>
  )
})

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-4"
    >
      <div className="w-20 h-20 rounded-3xl bg-primary/10 flex items-center justify-center mb-6">
        <MagnifyingGlass size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет задач парсинга</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Создайте задачу для сбора участников групп, поиска сообщений или каналов.
      </p>
      <button
        onClick={onAdd}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
      >
        <Plus size={18} weight="bold" />
        Создать задачу
      </button>
    </motion.div>
  )
}

function ResultsModal({ taskId, onClose }: { taskId: number; onClose: () => void }) {
  const [rows, setRows] = useState<Record<string, string>[]>([])
  const [searchStats, setSearchStats] = useState<Record<string, number> | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get(`/api/v1/parsing/${taskId}/results?limit=300`)
      .then(r => {
        setRows(r.data.rows || [])
        setSearchStats(r.data.search_stats || null)
      })
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [taskId])

  const linkField = rows[0]
    ? (Object.prototype.hasOwnProperty.call(rows[0], 'link')
        ? 'link'
        : Object.keys(rows[0]).find(k => k.includes('url') || k === 'username') ?? null)
    : null
  const titleField = rows[0]
    ? (Object.prototype.hasOwnProperty.call(rows[0], 'title')
        ? 'title'
        : Object.keys(rows[0]).find(k => k.includes('title') || k.includes('name')) ?? null)
    : null
  const membersField = rows[0] ? Object.keys(rows[0]).find(k => k.includes('member') || k.includes('participant') || k.includes('subscriber')) : null

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
      className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      onClick={onClose}>
      <motion.div initial={{ opacity: 0, scale: 0.95, y: 20 }} animate={{ opacity: 1, scale: 1, y: 0 }}
        className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-5 border-b border-border/50 shrink-0">
          <h2 className="text-lg font-semibold">Результаты задачи #{taskId}</h2>
          <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted"><X size={18} /></button>
        </div>
        {searchStats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 px-5 py-3 border-b border-border/50 bg-muted/20 text-xs">
            <div><span className="text-muted-foreground">Запросов:</span> <b>{searchStats.search_requests ?? 0}</b></div>
            <div><span className="text-muted-foreground">Telegram отдал:</span> <b>{searchStats.telegram_candidates ?? 0}</b></div>
            <div><span className="text-muted-foreground">Дубликатов:</span> <b>{searchStats.duplicates ?? 0}</b></div>
            <div><span className="text-muted-foreground">Без обсуждений:</span> <b>{searchStats.filtered_no_discussion ?? 0}</b></div>
          </div>
        )}
        <div className="overflow-y-auto flex-1 p-2">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <SpinnerGap size={32} className="animate-spin" />
            </div>
          ) : rows.length === 0 ? (
            <p className="text-center py-12 text-muted-foreground">Результатов нет</p>
          ) : (
            <div className="divide-y divide-border/40">
              {rows.map((row, i) => {
                const link = linkField ? row[linkField] : null
                const title = titleField ? row[titleField] : null
                const members = membersField ? row[membersField] : null
                const href = link ? (link.startsWith('http') ? link : `https://t.me/${link.replace('@', '')}`) : null
                return (
                  <div key={i} className="flex items-center gap-3 px-3 py-2.5 hover:bg-muted/30 rounded-xl">
                    <span className="text-xs text-muted-foreground w-6 shrink-0">{i + 1}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {title || 'Название не указано'}
                      </p>
                      {href ? (
                        <a href={href} target="_blank" rel="noopener noreferrer"
                          className="text-xs text-primary hover:underline truncate block">
                          {link}
                        </a>
                      ) : (
                        <p className="text-xs text-muted-foreground truncate">{JSON.stringify(row)}</p>
                      )}
                    </div>
                    {members && <span className="text-xs text-muted-foreground shrink-0">{Number(members).toLocaleString()} участников</span>}
                  </div>
                )
              })}
            </div>
          )}
        </div>
        <div className="p-4 border-t border-border/50 shrink-0 text-xs text-muted-foreground text-center">
          Показано до 300 строк · Полный файл доступен для скачивания
        </div>
      </motion.div>
    </motion.div>
  )
}

export default function Parsing() {
  const [tasks, setTasks] = useState<ParsingTask[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [viewTaskId, setViewTaskId] = useState<number | null>(null)
  const [selectedIds, setSelectedIds] = useState<number[]>([])

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  const selectAll = () => setSelectedIds(tasks.map(t => t.id))
  const clearSelection = () => setSelectedIds([])

  const fetchTasks = async (showSpinner = false) => {
    try {
      if (showSpinner) setLoading(true)
      const response = await api.get('/api/v1/parsing')
      setTasks(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
      if (showSpinner) setTasks([])
    } finally {
      if (showSpinner) setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks(true)
  }, [])

  // Автополлинг: обновляем каждые 3с только если есть СВЕЖИЕ задачи (< 1ч) в running/pending.
  // Частый опрос нужен, чтобы живой счётчик «найдено» обновлялся почти в реальном времени.
  useEffect(() => {
    // Poll while any pending/running task is reasonably fresh. The zombie
    // reaper on the backend cleans up tasks left over from a restart, so a
    // genuinely-stuck task won't keep us polling forever. 2h window gives
    // big member-parses plenty of room.
    const cutoff = Date.now() - 2 * 60 * 60 * 1000
    const hasRecentActive = tasks.some(t =>
      (t.status === 'pending' || t.status === 'running') &&
      parseServerDate(t.created_at).getTime() > cutoff
    )
    if (!hasRecentActive) return
    const id = setInterval(() => fetchTasks(false), 3000)
    return () => clearInterval(id)
  }, [tasks])

  const handleBulkDelete = async () => {
    if (selectedIds.length === 0) return
    for (const id of selectedIds) {
      try { await api.delete(`/api/v1/parsing/${id}`) } catch { /* skip */ }
    }
    clearSelection()
    fetchTasks(true)
  }

  const handleDelete = async (id: number) => {
    try {
      await api.delete(`/api/v1/parsing/${id}`)
      fetchTasks(true)
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const stats = {
    total: tasks.length,
    completed: tasks.filter(t => t.status === 'completed').length,
    totalResults: tasks.reduce((sum, t) => sum + t.result_count, 0),
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
          <h1 className="text-3xl font-bold tracking-tight">Парсинг</h1>
          <p className="text-muted-foreground mt-1">Сбор данных из Telegram</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus size={18} weight="bold" />
          Новая задача
        </button>
      </motion.div>

      {/* Stats Row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{stats.total}</p>
          <p className="text-sm text-muted-foreground">Всего задач</p>
        </div>
        <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
          <p className="text-3xl font-bold text-emerald-600">{stats.completed}</p>
          <p className="text-sm text-muted-foreground">Завершено</p>
        </div>
        <div className="p-5 rounded-2xl bg-primary/5 border border-primary/20">
          <p className="text-3xl font-bold text-primary">{stats.totalResults.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">Всего результатов</p>
        </div>
      </div>

      {/* Tasks List */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState onAdd={() => setIsModalOpen(true)} />
      ) : (
        <motion.div layout className="bg-card rounded-2xl border border-border/50 overflow-hidden">

          {/* Bulk selection bar */}
          <div className="flex flex-wrap items-center gap-3 px-5 py-3 border-b border-border/50 text-sm bg-muted/20">
            <input
              type="checkbox"
              checked={selectedIds.length === tasks.length && tasks.length > 0}
              onChange={() => selectedIds.length === tasks.length ? clearSelection() : selectAll()}
              className="h-4 w-4 rounded border-border cursor-pointer"
            />
            <span className="text-muted-foreground">
              {selectedIds.length > 0 ? `Выбрано: ${selectedIds.length}` : `Всего: ${tasks.length}`}
            </span>
            {selectedIds.length > 0 && (
              <>
                <button
                  onClick={handleBulkDelete}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-500/10 text-red-600 hover:bg-red-500/20 text-xs font-medium transition-colors"
                >
                  <Trash size={13} />
                  Удалить выбранные
                </button>
                <button
                  onClick={clearSelection}
                  className="text-xs text-muted-foreground hover:text-foreground"
                >
                  Снять выделение
                </button>
              </>
            )}
          </div>

          {/* Table Header — must match TABLE_COLS exactly */}
          <div className={`grid ${TABLE_COLS} gap-3 px-5 py-2.5 border-b border-border/50 text-xs font-medium text-muted-foreground bg-muted/20`}>
            <div></div>
            <div></div>
            <div>Задача</div>
            <div>Статус</div>
            <div className="text-right">Найдено</div>
            <div className="text-right">Дата</div>
            <div></div>
          </div>

          {/* Table Body */}
          <div>
            <AnimatePresence mode="popLayout">
              {tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  onDelete={() => handleDelete(task.id)}
                  onView={() => setViewTaskId(task.id)}
                  selected={selectedIds.includes(task.id)}
                  onToggleSelect={toggleSelect}
                />
              ))}
            </AnimatePresence>
          </div>
        </motion.div>
      )}

      <CreateTaskModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={() => fetchTasks(true)}
      />

      <AnimatePresence>
        {viewTaskId && (
          <ResultsModal taskId={viewTaskId} onClose={() => setViewTaskId(null)} />
        )}
      </AnimatePresence>
    </div>
  )
}
