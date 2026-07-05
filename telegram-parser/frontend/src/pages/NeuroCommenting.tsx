import { useEffect, useState } from 'react'
import {
  Play,
  Pause,
  Stop,
  Plus,
  Trash,
  Check,
  X,
  SpinnerGap,
  ChatCircle,
  Brain,
  Clock,
  CheckCircle,
  Warning,
  Eye
} from '@phosphor-icons/react'
import api from '../services/api'
import { emitApiError } from '../services/apiEvents'

type TaskStatus = 'draft' | 'running' | 'paused' | 'completed' | 'failed' | 'stopped'
type DraftStatus = 'pending' | 'approved' | 'rejected' | 'published' | 'skipped'
type CommentPolicy = 'draft_only' | 'auto_publish'
type CommentTargetMode = 'channel_posts' | 'group_context'
type SourceType = 'unknown' | 'chat' | 'group' | 'channel' | 'closed'

interface CommentTask {
  id: number
  name: string
  project_id: number
  status: TaskStatus
  policy: CommentPolicy
  source_ids: number[]
  target_mode: CommentTargetMode
  target_modes: CommentTargetMode[]
  account_ids: number[]
  comments_per_account: number
  comments_per_source: number
  model: string
  provider: string
  topic: string | null
  min_delay: number
  max_delay: number
  moderation_enabled: boolean
  posts_checked: number
  drafts_created: number
  comments_posted: number
  errors_count: number
  created_at: string
  started_at: string | null
  finished_at: string | null
}

interface CommentDraft {
  id: number
  task_id: number
  source_id: number
  account_id: number
  post_id: number
  post_text: string
  draft_text: string
  moderation_flagged: boolean
  moderation_reason: string | null
  status: DraftStatus
  approved_by: string | null
  published_message_id: number | null
  published_at: string | null
  error_message: string | null
  created_at: string
}

interface Account {
  id: number
  phone_number: string
  status: string
  has_session?: boolean
  proxy_id?: number | null
  proxy_country?: string | null
  note?: string | null
  username?: string | null
  warmup_level?: number | null
  personal_channel_id?: number | null
  personal_channel_username?: string | null
  health_factors?: {
    restriction?: { reason?: string; at?: string }
    spambot?: { status: string; until?: string | null }
  } | null
}

interface TelegramSource {
  id: number
  group_id: number | null
  normalized_link: string
  source_type: SourceType
  title: string | null
  is_enabled?: boolean
}

interface TelegramSourceGroup {
  id: number
  name: string
}

interface AIProvider {
  id: string
  name: string
  models: string[]
  configured: boolean
}

const statusLabels: Record<TaskStatus, string> = {
  draft: 'Черновик',
  running: 'Запущен',
  paused: 'Приостановлен',
  completed: 'Завершен',
  failed: 'Ошибка',
  stopped: 'Остановлен',
}

const statusColors: Record<TaskStatus, string> = {
  draft: 'bg-muted text-muted-foreground',
  running: 'bg-blue-500/10 text-blue-600',
  paused: 'bg-yellow-500/10 text-yellow-600',
  completed: 'bg-green-500/10 text-green-600',
  failed: 'bg-red-500/10 text-red-600',
  stopped: 'bg-gray-500/10 text-gray-600',
}

const draftStatusLabels: Record<DraftStatus, string> = {
  pending: 'Ожидает',
  approved: 'Одобрен',
  rejected: 'Отклонен',
  published: 'Опубликован',
  skipped: 'Пропущен',
}

export default function NeuroCommenting() {
  const [tasks, setTasks] = useState<CommentTask[]>([])
  const [drafts, setDrafts] = useState<CommentDraft[]>([])
  const [accounts, setAccounts] = useState<Account[]>([])
  const [sources, setSources] = useState<TelegramSource[]>([])
  const [sourceGroups, setSourceGroups] = useState<TelegramSourceGroup[]>([])
  const [providers, setProviders] = useState<AIProvider[]>([])
  const [loading, setLoading] = useState(true)
  const [selectedTask, setSelectedTask] = useState<CommentTask | null>(null)
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [showDrafts, setShowDrafts] = useState(false)
  const [editingTaskId, setEditingTaskId] = useState<number | null>(null)
  const [startingTaskId, setStartingTaskId] = useState<number | null>(null)

  // Form state
  const [formData, setFormData] = useState({
    name: '',
    source_ids: [] as number[],
    source_group_id: '' as number | '',
    target_mode: 'channel_posts' as CommentTargetMode,
    target_modes: ['channel_posts'] as CommentTargetMode[],
    account_ids: [] as number[],
    comments_per_account: 10,
    comments_per_source: 3,
    model: 'deepseek-v4-flash',
    provider: 'deepseek',
    topic: '',
    min_delay: 60,
    max_delay: 180,
    policy: 'draft_only' as CommentPolicy,
    moderation_enabled: false,
  })

  const fetchTasks = async () => {
    try {
      const response = await api.get('/api/v1/comment-tasks')
      setTasks(response.data)
    } catch (error) {
      console.error('Ошибка загрузки задач:', error)
    }
  }

  const fetchAccounts = async () => {
    try {
      const response = await api.get('/api/v1/accounts')
      setAccounts(
        response.data.filter(
          (a: Account) =>
            Boolean(a.has_session) &&
            Boolean(a.proxy_id) &&
            ['new', 'warming', 'production'].includes(a.status)
        )
      )
    } catch (error) {
      console.error('Ошибка загрузки аккаунтов:', error)
    }
  }

  const fetchSources = async () => {
    try {
      const [sourcesResponse, groupsResponse] = await Promise.all([
        api.get('/api/v1/telegram-sources'),
        api.get('/api/v1/telegram-sources/groups'),
      ])
      setSources(sourcesResponse.data)
      setSourceGroups(groupsResponse.data)
    } catch (error) {
      console.error('Ошибка загрузки источников:', error)
    }
  }

  const fetchProviders = async () => {
    try {
      const response = await api.get('/api/v1/ai/providers/catalog')
      setProviders(response.data)
    } catch (error) {
      console.error('Ошибка загрузки AI-провайдеров:', error)
    }
  }

  const fetchDrafts = async (taskId: number) => {
    try {
      const response = await api.get(`/api/v1/comment-tasks/${taskId}/drafts`)
      setDrafts(response.data)
    } catch (error) {
      console.error('Ошибка загрузки черновиков:', error)
    }
  }

  const loadData = async () => {
    setLoading(true)
    await Promise.all([fetchTasks(), fetchAccounts(), fetchSources(), fetchProviders()])
    setLoading(false)
  }

  useEffect(() => {
    loadData()
  }, [])

  const handleCreateTask = async () => {
    if (!formData.name.trim()) return
    try {
      const { source_group_id, ...payload } = formData
      let response
      if (editingTaskId) {
        // Edit an existing task: change settings and the account pool.
        response = await api.patch(`/api/v1/comment-tasks/${editingTaskId}`, payload)
      } else {
        response = await api.post('/api/v1/comment-tasks', payload)
      }
      await fetchTasks()
      setSelectedTask(response.data)
      setShowCreateForm(false)
      resetForm()
    } catch (error) {
      console.error('Ошибка сохранения задачи:', error)
    }
  }

  const startEditTask = (task: CommentTask) => {
    const t = task as any
    setEditingTaskId(task.id)
    setFormData({
      name: t.name || '',
      source_ids: t.source_ids || [],
      source_group_id: '',
      target_mode: t.target_mode || 'channel_posts',
      target_modes: t.target_modes || [t.target_mode || 'channel_posts'],
      account_ids: t.account_ids || [],
      comments_per_account: t.comments_per_account ?? 10,
      comments_per_source: t.comments_per_source ?? 3,
      model: t.model || 'deepseek-v4-flash',
      provider: t.provider || 'deepseek',
      topic: t.topic || '',
      min_delay: t.min_delay ?? 60,
      max_delay: t.max_delay ?? 180,
      policy: t.policy || 'draft_only',
      moderation_enabled: t.moderation_enabled ?? false,
    })
    setShowCreateForm(true)
  }

  const resetForm = () => {
    setFormData({
      name: '',
      source_ids: [],
      source_group_id: '',
      target_mode: 'channel_posts',
      target_modes: ['channel_posts'],
      account_ids: [],
      comments_per_account: 10,
      comments_per_source: 3,
      model: 'deepseek-v4-flash',
      provider: 'deepseek',
      topic: '',
      min_delay: 60,
      max_delay: 180,
      policy: 'draft_only',
      moderation_enabled: false,
    })
    setEditingTaskId(null)
  }

  const handleStartTask = async (taskId: number) => {
    // Guard against double-submit: ignore repeat clicks while the request
    // is in flight (the backend also 409s a second start, but this keeps
    // the UI from firing a duplicate request in the first place).
    if (startingTaskId === taskId) return
    setStartingTaskId(taskId)
    try {
      const response = await api.post(`/api/v1/comment-tasks/${taskId}/start`)
      const warnings: string[] = response.data?.warnings ?? []
      if (warnings.length > 0) {
        emitApiError({
          title: 'Задача запущена, но часть прокси не работает',
          detail: warnings.join('\n'),
          level: 'warning',
        })
      }
      await fetchTasks()
    } catch (error: any) {
      const detail = error.response?.data?.detail
      emitApiError({
        title: 'Задача не запущена — все прокси недоступны',
        detail: typeof detail === 'string' ? detail : 'Проверьте прокси аккаунтов в разделе Прокси',
        level: 'error',
      })
      console.error('Ошибка запуска задачи:', error)
    } finally {
      setStartingTaskId(null)
    }
  }

  const handleStopTask = async (taskId: number) => {
    try {
      await api.post(`/api/v1/comment-tasks/${taskId}/stop`)
      await fetchTasks()
    } catch (error) {
      console.error('Ошибка остановки задачи:', error)
    }
  }

  const handleDeleteTask = async (taskId: number) => {
    if (!confirm('Удалить задачу и все связанные данные?')) return
    try {
      await api.delete(`/api/v1/comment-tasks/${taskId}`)
      await fetchTasks()
      if (selectedTask?.id === taskId) setSelectedTask(null)
    } catch (error) {
      console.error('Ошибка удаления задачи:', error)
    }
  }

  const handleApproveDraft = async (taskId: number, draftId: number) => {
    try {
      await api.post(`/api/v1/comment-tasks/${taskId}/drafts/${draftId}/approve`)
      await fetchDrafts(taskId)
    } catch (error) {
      console.error('Ошибка одобрения черновика:', error)
    }
  }

  const handleRejectDraft = async (taskId: number, draftId: number) => {
    try {
      await api.post(`/api/v1/comment-tasks/${taskId}/drafts/${draftId}/reject`)
      await fetchDrafts(taskId)
    } catch (error) {
      console.error('Ошибка отклонения черновика:', error)
    }
  }

  const openTaskDetails = async (task: CommentTask) => {
    setSelectedTask(task)
    await fetchDrafts(task.id)
    setShowDrafts(true)
  }

  const pendingDrafts = drafts.filter(d => d.status === 'pending')
  const providerModels = providers.find(provider => provider.id === formData.provider)?.models || []
  const selectedSourceTypes: SourceType[] = [
    ...(formData.target_modes.includes('channel_posts') ? ['channel' as SourceType] : []),
    ...(formData.target_modes.includes('group_context') ? ['group' as SourceType] : []),
  ]
  const filteredSources = sources.filter(source => {
    if (formData.source_group_id && source.group_id !== formData.source_group_id) return false
    if (source.is_enabled === false) return false
    return selectedSourceTypes.includes(source.source_type) || source.source_type === 'unknown'
  })
  const countryLabels: Record<string, string> = {
    us: 'США',
    usa: 'США',
    ru: 'Россия',
    lv: 'Латвия',
    nl: 'Нидерланды',
    de: 'Германия',
    fr: 'Франция',
    gb: 'Великобритания',
    uk: 'Великобритания',
  }
  const countryName = (value?: string | null) => {
    const key = (value || 'unknown').toLowerCase()
    return countryLabels[key] || (value ? value.toUpperCase() : 'Страна не указана')
  }
  const accountCountries = Array.from(new Set(accounts.map(a => countryName(a.proxy_country)))).sort()
  const [selectedCountry, setSelectedCountry] = useState('')
  const visibleAccounts = accounts.filter(a => !selectedCountry || countryName(a.proxy_country) === selectedCountry)
  const selectedAccounts = accounts.filter(account => formData.account_ids.includes(account.id))
  const toggleTargetMode = (mode: CommentTargetMode) => {
    const next = formData.target_modes.includes(mode)
      ? formData.target_modes.filter(item => item !== mode)
      : [...formData.target_modes, mode]
    const safeNext = next.length ? next : [mode]
    setFormData({
      ...formData,
      target_modes: safeNext,
      target_mode: safeNext[0],
      source_ids: [],
    })
  }

  useEffect(() => {
    setFormData(prev => {
      const ids = filteredSources.map(source => source.id)
      const nextSourceIds = prev.source_ids.filter(id => ids.includes(id))
      return nextSourceIds.length === prev.source_ids.length ? prev : { ...prev, source_ids: nextSourceIds }
    })
  }, [formData.source_group_id, formData.target_mode, sources.length])

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <SpinnerGap size={32} className="animate-spin text-primary" />
      </div>
    )
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Нейрокомментинг</h1>
          <p className="text-muted-foreground mt-1">AI-черновики для каналов и групп текущего проекта</p>
        </div>
        <button
          onClick={() => {
            if (showCreateForm) { setShowCreateForm(false); resetForm() }
            else { resetForm(); setShowCreateForm(true) }
          }}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus size={18} />
          Новая задача
        </button>
      </div>

      {/* Create Form */}
      {showCreateForm && (
        <div className="bg-card border border-border rounded-3xl p-6 space-y-6">
          <div className="flex items-center gap-3">
            <Brain size={24} className="text-primary" />
            <h2 className="text-lg font-semibold">{editingTaskId ? 'Редактирование задачи нейрокомментинга' : 'Создание задачи нейрокомментинга'}</h2>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">Название задачи</label>
              <input
                type="text"
                value={formData.name}
                onChange={e => setFormData({ ...formData, name: e.target.value })}
                placeholder="Мой нейрокомментарий"
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Тема комментариев</label>
              <input
                type="text"
                value={formData.topic}
                onChange={e => setFormData({ ...formData, topic: e.target.value })}
                placeholder="Оставьте пустым для общего стиля"
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Режим задачи</label>
              <div className="space-y-2 rounded-xl border border-border bg-background p-3">
                <label className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    checked={formData.target_modes.includes('channel_posts')}
                    onChange={() => toggleTargetMode('channel_posts')}
                    className="h-4 w-4"
                  />
                  Каналы: анализ последнего поста и комментарий в обсуждении
                </label>
                <label className="flex items-center gap-3 text-sm">
                  <input
                    type="checkbox"
                    checked={formData.target_modes.includes('group_context')}
                    onChange={() => toggleTargetMode('group_context')}
                    className="h-4 w-4"
                  />
                  Группы/чаты: анализ последних 5 сообщений и ответ по контексту
                </label>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">AI-провайдер</label>
              <select
                value={formData.provider}
                onChange={e => {
                  const provider = providers.find(item => item.id === e.target.value)
                  setFormData({
                    ...formData,
                    provider: e.target.value,
                    model: provider?.models[0] || formData.model,
                  })
                }}
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
              >
                {(providers.length ? providers : [
                  { id: 'openai', name: 'OpenAI', configured: false, models: ['gpt-4o-mini'] },
                  { id: 'deepseek', name: 'DeepSeek', configured: true, models: ['deepseek-v4-flash'] },
                  { id: 'openrouter', name: 'OpenRouter', configured: false, models: ['openrouter/auto'] },
                ]).map(provider => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}{provider.configured ? '' : ' · ключ не настроен'}
                  </option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Модель</label>
              <select
                value={formData.model}
                onChange={e => setFormData({ ...formData, model: e.target.value })}
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
              >
                {(providerModels.length ? providerModels : [formData.model]).map(model => (
                  <option key={model} value={model}>{model}</option>
                ))}
              </select>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">Политика публикации</label>
              <select
                value={formData.policy}
                onChange={e => setFormData({
                  ...formData,
                  policy: e.target.value as CommentPolicy,
                  moderation_enabled: e.target.value === 'auto_publish' ? formData.moderation_enabled : false,
                })}
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
              >
                <option value="draft_only">Сначала черновики, публикация только вручную</option>
                <option value="auto_publish">Публиковать автоматически без ручного шага</option>
              </select>
              <p className="text-xs text-muted-foreground">
                {formData.policy === 'draft_only'
                  ? 'Сервис только готовит варианты текста. Ты сам просматриваешь их и решаешь, что публиковать.'
                  : 'Сервис сам публикует комментарий после всех внутренних проверок. Использовать только для своих и контролируемых источников.'}
              </p>
            </div>

            <div className="flex items-center gap-3">
              <input
                type="checkbox"
                id="moderation"
                checked={formData.moderation_enabled}
                onChange={e => setFormData({ ...formData, moderation_enabled: e.target.checked })}
                disabled={formData.policy === 'draft_only'}
                className="w-5 h-5 rounded border-border"
              />
              <label htmlFor="moderation" className="text-sm font-medium">
                Проверять текст перед автопубликацией
              </label>
            </div>
            <p className="text-xs text-muted-foreground -mt-4">
              {formData.policy === 'draft_only'
                ? 'При ручной публикации отдельная автопроверка не нужна, потому что ты и так видишь каждый черновик.'
                : 'Если включено, сервис сначала отсеивает сомнительные тексты и только потом публикует их автоматически.'}
            </p>
          </div>

          <div className="rounded-2xl border border-primary/20 bg-primary/5 p-4 text-sm text-muted-foreground">
            Безопасные лимиты применяются автоматически: один источник за проход берёт один аккаунт,
            задержки и дневные лимиты проверяются общим rate limiter. Эти настройки скрыты, чтобы случайно
            не превратить аккуратную задачу в шумную.
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Аккаунты ({formData.account_ids.length} выбрано)</label>
            <select
              value={selectedCountry}
              onChange={e => setSelectedCountry(e.target.value)}
              className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
            >
              <option value="">Сначала выбери страну прокси</option>
              {accountCountries.map(country => (
                <option key={country} value={country}>{country}</option>
              ))}
            </select>
            <div className="flex max-h-48 flex-wrap gap-2 overflow-y-auto rounded-2xl border border-border/60 bg-muted/20 p-3">
              {visibleAccounts.map(account => {
                const isSelected = formData.account_ids.includes(account.id)
                const hasRestriction = !!account.health_factors?.restriction
                const isSpam = account.health_factors?.spambot?.status === 'spam'
                const noUsername = !account.username
                const warmup = account.warmup_level ?? 0
                const hasChannel = !!account.personal_channel_id
                return (
                  <button
                    key={account.id}
                    onClick={() => {
                      const ids = isSelected
                        ? formData.account_ids.filter(id => id !== account.id)
                        : [...formData.account_ids, account.id]
                      setFormData({ ...formData, account_ids: ids })
                    }}
                    title={[
                      hasRestriction ? `⚠ Ограничен (${account.health_factors?.restriction?.reason})` : '',
                      isSpam ? `🔴 SpamBot: спам` : '',
                      noUsername ? '⚠ Нет username' : `@${account.username}`,
                      `Прогрев: ${warmup}/30`,
                      hasChannel
                        ? `📺 Личный канал: ${account.personal_channel_username || account.personal_channel_id}`
                        : '📺 Нет личного канала',
                    ].filter(Boolean).join(' · ')}
                    className={`flex flex-col items-start gap-0.5 px-3 py-2 rounded-lg text-sm transition-colors text-left ${
                      isSelected ? 'bg-primary text-primary-foreground' : 'bg-muted hover:bg-muted/70'
                    } ${hasRestriction || isSpam ? 'ring-1 ring-red-400' : ''}`}
                  >
                    <span className="font-medium leading-tight">
                      {account.note || account.username || account.phone_number}
                    </span>
                    <span className={`text-[10px] leading-tight flex items-center gap-1 ${isSelected ? 'text-primary-foreground/70' : 'text-muted-foreground'}`}>
                      {countryName(account.proxy_country)}
                      {' · '}{warmup}/30
                      {hasChannel
                        ? <span className="text-blue-400 font-bold">📺 канал</span>
                        : <span className="text-muted-foreground/60">нет канала</span>}
                      {hasRestriction && <span className="text-red-400 font-bold">⚠ огр.</span>}
                      {isSpam && <span className="text-red-400 font-bold">spam</span>}
                      {noUsername && <span className="text-amber-500 font-bold">no @</span>}
                    </span>
                  </button>
                )
              })}
              {selectedCountry && visibleAccounts.length === 0 && (
                <span className="text-sm text-muted-foreground">
                  В этой стране нет доступных аккаунтов.
                </span>
              )}
              {accounts.length === 0 && (
                <span className="text-sm text-muted-foreground">
                  Нет доступных аккаунтов. Нужен аккаунт с сессией, прокси и статусом `new` / `warming` / `production`.
                </span>
              )}
            </div>
            {selectedAccounts.length > 0 && (
              <div className="rounded-2xl border border-border/60 bg-background p-3">
                <p className="text-xs text-muted-foreground mb-2">Выбраны для задачи:</p>
                <div className="flex flex-wrap gap-2">
                  {selectedAccounts.map(account => (
                    <span key={account.id} className="px-3 py-2 rounded-lg bg-primary/10 text-sm text-primary">
                      {(account.note || account.username || account.phone_number)} · {countryName(account.proxy_country)}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium">Пул источников</label>
            <select
              value={formData.source_group_id}
              onChange={e => setFormData({
                ...formData,
                source_group_id: e.target.value ? Number(e.target.value) : '',
                source_ids: [],
              })}
              className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
            >
              <option value="">Все источники проекта</option>
              {sourceGroups.map(group => (
                <option key={group.id} value={group.id}>{group.name}</option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <label className="text-sm font-medium">Источники ({formData.source_ids.length} выбрано)</label>
              <div className="flex gap-2">
                {filteredSources.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, source_ids: filteredSources.map(s => s.id) })}
                    className="px-2.5 py-1 rounded-lg border border-border hover:bg-muted text-xs font-medium"
                  >
                    Выбрать все ({filteredSources.length})
                  </button>
                )}
                {formData.source_ids.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setFormData({ ...formData, source_ids: [] })}
                    className="px-2.5 py-1 rounded-lg border border-border hover:bg-muted text-xs font-medium text-muted-foreground"
                  >
                    Снять
                  </button>
                )}
              </div>
            </div>
            <p className="text-xs text-muted-foreground">
              Показаны источники под выбранные режимы. Неопределённые ссылки лучше сначала проверить на странице «Источники».
            </p>
            <div className="flex flex-wrap gap-2 max-h-40 overflow-y-auto">
              {filteredSources.map(source => (
                <button
                  key={source.id}
                  onClick={() => {
                    const ids = formData.source_ids.includes(source.id)
                      ? formData.source_ids.filter(id => id !== source.id)
                      : [...formData.source_ids, source.id]
                    setFormData({ ...formData, source_ids: ids })
                  }}
                  className={`px-3 py-2 rounded-lg text-sm transition-colors ${
                    formData.source_ids.includes(source.id)
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted hover:bg-muted/70'
                  }`}
                >
                  {source.normalized_link}
                </button>
              ))}
              {filteredSources.length === 0 && (
                <span className="text-sm text-muted-foreground">Нет доступных источников</span>
              )}
            </div>
          </div>

          <div className="flex justify-end gap-3">
            <button
              onClick={() => { setShowCreateForm(false); resetForm() }}
              className="px-4 py-2 rounded-xl border border-border hover:bg-muted transition-colors"
            >
              Отмена
            </button>
            <button
              onClick={handleCreateTask}
              disabled={!formData.name.trim() || formData.account_ids.length === 0 || formData.source_ids.length === 0}
              className="px-4 py-2 rounded-xl bg-primary text-primary-foreground font-medium disabled:opacity-50 hover:bg-primary/90 transition-colors"
            >
              {editingTaskId ? 'Сохранить изменения' : 'Создать задачу'}
            </button>
          </div>
        </div>
      )}

      {/* Tasks List */}
      {!showDrafts && (
        <div className="grid gap-4">
          {tasks.length === 0 ? (
            <div className="text-center py-16 text-muted-foreground bg-card border border-border rounded-3xl">
              <ChatCircle size={48} className="mx-auto mb-4 opacity-50" />
              <p>Нет задач нейрокомментинга</p>
              <p className="text-sm mt-1">Создайте первую задачу для начала работы</p>
            </div>
          ) : (
            tasks.map(task => (
              <div key={task.id} className="bg-card border border-border rounded-3xl p-6">
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <h3 className="text-lg font-semibold truncate">{task.name}</h3>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${statusColors[task.status]}`}>
                        {statusLabels[task.status]}
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center gap-4 mt-2 text-sm text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Brain size={16} />
                        {task.model}
                      </span>
                      <span>{task.source_ids.length} источников</span>
                      <span>{task.account_ids.length} аккаунтов</span>
                      <span>{task.policy === 'draft_only' ? 'Ручная публикация' : 'Автопубликация'}</span>
                      <span>
                        {task.target_modes?.includes('channel_posts') && task.target_modes?.includes('group_context')
                          ? 'Каналы и группы'
                          : task.target_modes?.includes('channel_posts')
                            ? 'Только каналы'
                            : 'Только группы'}
                      </span>
                      {task.topic && <span>Тема: {task.topic}</span>}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => openTaskDetails(task)}
                      className="p-2 rounded-lg hover:bg-muted transition-colors"
                      title="Черновики"
                    >
                      <Eye size={20} />
                    </button>
                    {task.status === 'draft' && (
                      <button
                        onClick={() => handleStartTask(task.id)}
                        disabled={startingTaskId === task.id}
                        className="p-2 rounded-lg bg-green-500/10 text-green-600 hover:bg-green-500/20 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Запустить"
                      >
                        <Play size={20} weight="fill" />
                      </button>
                    )}
                    {task.status === 'running' && (
                      <button
                        onClick={() => handleStopTask(task.id)}
                        className="p-2 rounded-lg bg-red-500/10 text-red-600 hover:bg-red-500/20 transition-colors"
                        title="Остановить"
                      >
                        <Stop size={20} weight="fill" />
                      </button>
                    )}
                    {task.status !== 'running' && (
                      <button
                        onClick={() => startEditTask(task)}
                        className="px-2 py-2 rounded-lg bg-blue-500/10 text-blue-600 hover:bg-blue-500/20 transition-colors text-xs font-medium"
                        title="Изменить настройки и пул аккаунтов"
                      >
                        Изменить
                      </button>
                    )}
                    <button
                      onClick={() => handleDeleteTask(task.id)}
                      className="p-2 rounded-lg hover:bg-red-500/10 text-muted-foreground hover:text-red-600 transition-colors"
                      title="Удалить"
                    >
                      <Trash size={20} />
                    </button>
                  </div>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-4 gap-4 mt-4 pt-4 border-t border-border">
                  <div className="text-center">
                    <div className="text-2xl font-bold">{task.posts_checked}</div>
                    <div className="text-xs text-muted-foreground">Постов проверено</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold">{task.drafts_created}</div>
                    <div className="text-xs text-muted-foreground">Черновиков создано</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold">{task.comments_posted}</div>
                    <div className="text-xs text-muted-foreground">Опубликовано</div>
                  </div>
                  <div className="text-center">
                    <div className="text-2xl font-bold text-red-500">{task.errors_count}</div>
                    <div className="text-xs text-muted-foreground">Ошибок</div>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Drafts View */}
      {showDrafts && selectedTask && (
        <div className="space-y-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => setShowDrafts(false)}
              className="px-4 py-2 rounded-xl border border-border hover:bg-muted transition-colors"
            >
              ← Назад к задачам
            </button>
            <div>
              <h2 className="text-xl font-semibold">{selectedTask.name}</h2>
              <p className="text-sm text-muted-foreground">
                {pendingDrafts.length} черновиков ожидает проверки
              </p>
            </div>
          </div>

          <div className="space-y-4">
            {drafts.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground bg-card border border-border rounded-3xl">
                <p>Черновиков пока нет</p>
              </div>
            ) : (
              drafts.map(draft => (
                <div key={draft.id} className="bg-card border border-border rounded-3xl p-6">
                  <div className="flex items-start justify-between gap-4 mb-4">
                    <div className="flex items-center gap-2">
                      {draft.moderation_flagged && (
                        <span className="px-2 py-1 rounded bg-red-500/10 text-red-600 text-xs">
                          <Warning size={14} className="inline mr-1" />
                          {draft.moderation_reason || 'Заблокировано'}
                        </span>
                      )}
                      <span className={`px-2 py-1 rounded text-xs ${
                        draft.status === 'pending' ? 'bg-yellow-500/10 text-yellow-600' :
                        draft.status === 'published' ? 'bg-green-500/10 text-green-600' :
                        draft.status === 'approved' ? 'bg-blue-500/10 text-blue-600' :
                        'bg-muted text-muted-foreground'
                      }`}>
                        {draftStatusLabels[draft.status]}
                      </span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      {new Date(draft.created_at).toLocaleString('ru-RU')}
                    </span>
                  </div>

                  <div className="mb-4">
                    <p className="text-sm text-muted-foreground mb-1">Пост:</p>
                    <p className="text-sm bg-muted/50 rounded-lg p-3 line-clamp-3">{draft.post_text}</p>
                  </div>

                  <div className="mb-4">
                    <p className="text-sm text-muted-foreground mb-1">Сгенерированный комментарий:</p>
                    <p className="bg-primary/5 border border-primary/20 rounded-lg p-3">{draft.draft_text}</p>
                  </div>

                  {draft.status === 'pending' && (
                    <div className="flex justify-end gap-2">
                      <button
                        onClick={() => handleRejectDraft(selectedTask.id, draft.id)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl border border-border hover:bg-red-500/10 hover:border-red-500/50 transition-colors text-red-600"
                      >
                        <X size={18} />
                        Отклонить
                      </button>
                      <button
                        onClick={() => handleApproveDraft(selectedTask.id, draft.id)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl bg-green-500 text-white hover:bg-green-600 transition-colors"
                      >
                        <Check size={18} />
                        Опубликовать
                      </button>
                    </div>
                  )}

                  {draft.error_message && (
                    <p className="text-sm text-red-500 mt-2">Ошибка: {draft.error_message}</p>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
