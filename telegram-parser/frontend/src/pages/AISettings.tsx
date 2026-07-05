import { useState, useEffect, forwardRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Robot,
  ChatCircle,
  Textbox,
  PaperPlaneTilt,
  Brain,
  CheckCircle,
  XCircle,
  Clock,
  Plus,
  X,
  Play,
  Stop,
  Trash,
  DotsThree,
  Globe,
  Users,
  TextAlignLeft,
  SpinnerGap,
  Gear,
  Lightning
} from '@phosphor-icons/react'

interface AISettings {
  id: number
  account_id: number
  account_name: string
  type: 'dialogs' | 'chatting' | 'commenting'
  enabled: boolean
  system_prompt: string
  context_depth: number
  min_delay: number
  max_delay: number
  model: string
  provider: string
  created_at: string
}

interface DialogStats {
  total_dialogs: number
  active_dialogs: number
  messages_today: number
  avg_response_time: string
}

interface AIProvider {
  id: string
  name: string
  models: string[]
  configured: boolean
}

const typeConfig: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  dialogs: { icon: ChatCircle, label: 'Диалоги (ЛС)', color: 'text-blue-600 bg-blue-500/10' },
  chatting: { icon: Users, label: 'Чаттинг', color: 'text-emerald-600 bg-emerald-500/10' },
  commenting: { icon: TextAlignLeft, label: 'Комментинг', color: 'text-purple-600 bg-purple-500/10' },
}

const promptPresets = [
  {
    id: 'sales',
    name: 'Продажи',
    prompt: `Ты — ассистент по продажам в Telegram.
Отвечай кратко (до 2-3 предложений), дружелюбно, профессионально.
Не отправляй длинные сообщения.
Если не знаешь ответ — признайся и предложи связаться с менеджером.`
  },
  {
    id: 'support',
    name: 'Поддержка',
    prompt: `Ты — служба поддержки клиентов.
Отвечай вежливо, предоставляй полезную информацию.
Если нужна помощь специалиста — переключай на менеджера.
Всегда благодари за обращение.`
  },
  {
    id: 'chatbot',
    name: 'Чат-бот',
    prompt: `Ты — дружелюбный собеседник в Telegram.
Поддерживай естественную беседу, будь интересным.
Не отправляй слишком длинные сообщения.
Задавай уточняющие вопросы.`
  },
  {
    id: 'friend',
    name: 'Друг',
    prompt: `Ты — близкий друг пользователя в Telegram. 
Твой стиль общения — неформальный, теплый и искренний. 
Используй сленг, если это уместно, но оставайся вежливым. 
Твоя задача — поддерживать общение, давать советы как другу и просто быть рядом. 
Отвечай кратко, как в обычном мессенджере.`
  },
  {
    id: 'onboarding',
    name: 'Онбординг',
    prompt: `Ты — бот для онбординга новых пользователей.
Помоги пользователю познакомиться с продуктом.
Отвечай кратко и по делу.
Расскажи о ключевых возможностях.`
  },
]

function StatusBadge({ enabled }: { enabled: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${
      enabled
        ? 'text-emerald-600 bg-emerald-500/10'
        : 'text-muted-foreground bg-muted'
    }`}>
      {enabled ? (
        <>
          <CheckCircle size={12} weight="bold" />
          Активен
        </>
      ) : (
        <>
          <Clock size={12} weight="bold" />
          Отключен
        </>
      )}
    </span>
  )
}

function CreateSettingsModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [accountId, setAccountId] = useState<number | null>(null)
  const [type, setType] = useState<'dialogs' | 'chatting' | 'commenting'>('dialogs')
  const [systemPrompt, setSystemPrompt] = useState(promptPresets[0].prompt)
  const [contextDepth, setContextDepth] = useState(10)
  const [minDelay, setMinDelay] = useState(5)
  const [maxDelay, setMaxDelay] = useState(30)
  const [model, setModel] = useState('gpt-4o-mini')
  const [provider, setProvider] = useState('openai')
  const [submitting, setSubmitting] = useState(false)
  const [accounts, setAccounts] = useState<{id: number, name: string}[]>([])
  const [providers, setProviders] = useState<AIProvider[]>([])

  useEffect(() => {
    if (isOpen) {
      Promise.all([
        api.get('/api/v1/accounts'),
        api.get('/api/v1/ai/providers/catalog'),
      ]).then(([accountsResponse, providersResponse]) => {
        setAccounts(accountsResponse.data.map((account: { id: number, phone_number: string }) => ({
          id: account.id,
          name: account.phone_number,
        })))
        setProviders(providersResponse.data)
      }).catch(error => console.error('Ошибка загрузки AI формы:', error))
    }
  }, [isOpen])

  const applyPreset = (presetId: string) => {
    const preset = promptPresets.find(p => p.id === presetId)
    if (preset) {
      setSystemPrompt(preset.prompt)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!accountId) return
    setSubmitting(true)

    try {
      await api.post('/api/v1/ai/setup', {
        account_id: accountId,
        type,
        system_prompt: systemPrompt,
        context_depth: contextDepth,
        min_delay: minDelay,
        max_delay: maxDelay,
        model,
        provider,
      })
      onSuccess()
      onClose()
    } catch (error) {
      console.error('Ошибка при сохранении:', error)
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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50 sticky top-0 bg-card rounded-t-3xl z-10">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <Brain size={24} className="text-primary" />
                AI Настройки
              </h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-6">
              {/* Account selector */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Аккаунт</label>
                <select
                  value={accountId || ''}
                  onChange={(e) => setAccountId(Number(e.target.value))}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  required
                >
                  <option value="">Выберите аккаунт</option>
                  {accounts.map(acc => (
                    <option key={acc.id} value={acc.id}>{acc.name}</option>
                  ))}
                </select>
              </div>

              {/* Type selector */}
              <div className="space-y-3">
                <label className="text-sm font-medium">Тип AI</label>
                <div className="grid grid-cols-3 gap-3">
                  {Object.entries(typeConfig).map(([key, config]) => {
                    const Icon = config.icon
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setType(key as any)}
                        className={`p-4 rounded-2xl border transition-all flex flex-col items-center gap-2 ${
                          type === key
                            ? 'bg-primary/10 border-primary/30 text-primary'
                            : 'bg-card border-border hover:border-border/80'
                        }`}
                      >
                        <Icon size={24} weight={type === key ? 'fill' : 'regular'} />
                        <span className="text-xs font-medium">{config.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Prompt presets */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Шаблон промпта</label>
                <div className="flex flex-wrap gap-2">
                  {promptPresets.map(preset => (
                    <button
                      key={preset.id}
                      type="button"
                      onClick={() => applyPreset(preset.id)}
                      className="px-3 py-1.5 rounded-lg bg-muted hover:bg-muted/80 text-sm transition-colors"
                    >
                      {preset.name}
                    </button>
                  ))}
                </div>
              </div>

              {/* System prompt */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Системный промпт</label>
                <textarea
                  value={systemPrompt}
                  onChange={(e) => setSystemPrompt(e.target.value)}
                  rows={5}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none"
                  placeholder="Инструкции для AI ассистента..."
                />
              </div>

              {/* Provider selector */}
              <div className="space-y-2">
                <label className="text-sm font-medium">AI-провайдер</label>
                <select
                  value={provider}
                  onChange={(e) => {
                    const nextProvider = e.target.value
                    const firstModel = providers.find(item => item.id === nextProvider)?.models[0]
                    setProvider(nextProvider)
                    if (firstModel) setModel(firstModel)
                  }}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                >
                  {providers.map(item => (
                    <option key={item.id} value={item.id}>
                      {item.name}{item.configured ? ' - ключ настроен' : ' - нет ключа'}
                    </option>
                  ))}
                </select>
              </div>

              {/* Model selector */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Модель</label>
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                >
                  {(providers.find(item => item.id === provider)?.models || [model]).map(item => (
                    <option key={item} value={item}>{item}</option>
                  ))}
                </select>
              </div>

              {/* Context depth */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center justify-between">
                  <span>Глубина контекста (сообщений)</span>
                  <span className="text-primary font-semibold">{contextDepth}</span>
                </label>
                <input
                  type="range"
                  value={contextDepth}
                  onChange={(e) => setContextDepth(Number(e.target.value))}
                  min="3"
                  max="50"
                  step="1"
                  className="w-full accent-primary"
                />
              </div>

              {/* Delay range */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium flex items-center justify-between">
                    <span>Мин. задержка (сек)</span>
                    <span className="text-primary font-semibold">{minDelay}</span>
                  </label>
                  <input
                    type="range"
                    value={minDelay}
                    onChange={(e) => setMinDelay(Number(e.target.value))}
                    min="1"
                    max="30"
                    step="1"
                    className="w-full accent-primary"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium flex items-center justify-between">
                    <span>Макс. задержка (сек)</span>
                    <span className="text-primary font-semibold">{maxDelay}</span>
                  </label>
                  <input
                    type="range"
                    value={maxDelay}
                    onChange={(e) => setMaxDelay(Number(e.target.value))}
                    min="10"
                    max="120"
                    step="5"
                    className="w-full accent-primary"
                  />
                </div>
              </div>

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
                  disabled={submitting || !accountId}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting ? 'Сохранение...' : 'Сохранить'}
                  <Gear size={18} />
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const SettingsCard = forwardRef<HTMLDivElement, { settings: AISettings, onToggle: () => void, onDelete: () => void }>(({ settings, onToggle, onDelete }, ref) => {
  const [showMenu, setShowMenu] = useState(false)
  const config = typeConfig[settings.type]
  const TypeIcon = config.icon

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className="bg-card rounded-2xl border border-border/50 p-5 hover:border-border transition-colors"
    >
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${config.color}`}>
            <TypeIcon size={20} weight="duotone" />
          </div>
          <div>
            <p className="font-medium">{settings.account_name}</p>
            <p className="text-sm text-muted-foreground">{config.label}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge enabled={settings.enabled} />
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
            >
              <DotsThree size={18} weight="bold" />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className="absolute right-0 top-full mt-2 w-40 bg-card rounded-xl border border-border shadow-xl z-20 py-2">
                  <button
                    onClick={() => { onToggle(); setShowMenu(false); }}
                    className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                  >
                    {settings.enabled ? <Stop size={16} /> : <Play size={16} />}
                    {settings.enabled ? 'Отключить' : 'Включить'}
                  </button>
                  <button
                    onClick={() => { onDelete(); setShowMenu(false); }}
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

      {/* Settings details */}
      <div className="grid grid-cols-4 gap-4 text-sm">
        <div>
          <p className="text-muted-foreground">Модель</p>
          <p className="font-medium truncate">{settings.model}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Контекст</p>
          <p className="font-medium">{settings.context_depth} сообщ.</p>
        </div>
        <div>
          <p className="text-muted-foreground">Задержка</p>
          <p className="font-medium">{settings.min_delay}-{settings.max_delay}с</p>
        </div>
        <div>
          <p className="text-muted-foreground">Промпт</p>
          <p className="font-medium truncate">{settings.system_prompt.slice(0, 15)}...</p>
        </div>
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
        <Robot size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет AI настроек</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Настройте AI автоответы для аккаунтов — диалоги, чаттинг или комментинг.
      </p>
      <button
        onClick={onAdd}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
      >
        <Plus size={18} weight="bold" />
        Добавить настройки
      </button>
    </motion.div>
  )
}

export default function AISettings() {
  const [settings, setSettings] = useState<AISettings[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const fetchSettings = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/ai')
      setSettings(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
      setSettings([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchSettings()
  }, [])

  const handleToggle = async (id: number) => {
    try {
      await api.post(`/api/v1/ai/${id}/toggle`)
      fetchSettings()
    } catch (error) {
      console.error('Ошибка при переключении:', error)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить эти настройки?')) return
    try {
      await api.delete(`/api/v1/ai/${id}`)
      fetchSettings()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const stats: DialogStats = {
    total_dialogs: settings.length,
    active_dialogs: settings.filter(s => s.enabled).length,
    messages_today: 1247,
    avg_response_time: '1.2s',
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
          <h1 className="text-3xl font-bold tracking-tight">AI Настройки</h1>
          <p className="text-muted-foreground mt-1">НейроДиалоги, Чаттинг, Комментинг</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus size={18} weight="bold" />
          Добавить настройки
        </button>
      </motion.div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{stats.total_dialogs}</p>
          <p className="text-sm text-muted-foreground">Всего настроек</p>
        </div>
        <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
          <p className="text-3xl font-bold text-emerald-600">{stats.active_dialogs}</p>
          <p className="text-sm text-muted-foreground">Активных</p>
        </div>
        <div className="p-5 rounded-2xl bg-blue-500/5 border border-blue-500/20">
          <p className="text-3xl font-bold text-blue-600">{stats.messages_today.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">Сообщений сегодня</p>
        </div>
        <div className="p-5 rounded-2xl bg-purple-500/5 border border-purple-500/20">
          <p className="text-3xl font-bold text-purple-600">{stats.avg_response_time}</p>
          <p className="text-sm text-muted-foreground">Среднее время</p>
        </div>
      </div>

      {/* Type tabs */}
      <div className="flex gap-2">
        {Object.entries(typeConfig).map(([key, config]) => {
          const Icon = config.icon
          const count = settings.filter(s => s.type === key).length
          return (
            <div
              key={key}
              className="flex items-center gap-2 px-4 py-2 rounded-xl bg-muted text-sm"
            >
              <Icon size={16} />
              <span>{config.label}</span>
              <span className="px-2 py-0.5 rounded-full bg-background text-xs font-medium">
                {count}
              </span>
            </div>
          )
        })}
      </div>

      {/* Settings List */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : settings.length === 0 ? (
        <EmptyState onAdd={() => setIsModalOpen(true)} />
      ) : (
        <motion.div
          layout
          className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          <AnimatePresence mode="popLayout">
            {settings.map((item) => (
              <SettingsCard
                key={item.id}
                settings={item}
                onToggle={() => handleToggle(item.id)}
                onDelete={() => handleDelete(item.id)}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      <CreateSettingsModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchSettings}
      />
    </div>
  )
}
