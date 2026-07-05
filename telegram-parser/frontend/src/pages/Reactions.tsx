import { useState, useEffect } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Play,
  Pause,
  X,
  Heart,
  Fire,
  ThumbsUp,
  HandsClapping,
  Question,
  Eyes,
  Confetti,
  CheckCircle,
  XCircle,
  Clock,
  DotsThree,
  Trash,
  Lightning,
  Users,
  SpinnerGap
} from '@phosphor-icons/react'

const REACTION_EMOJIS = [
  { emoji: '👍', icon: ThumbsUp, label: 'Класс' },
  { emoji: '❤️', icon: Heart, label: 'Сердце' },
  { emoji: '🔥', icon: Fire, label: 'Огонь' },
  { emoji: '👏', icon: HandsClapping, label: 'Аплодисменты' },
  { emoji: '🤔', icon: Question, label: 'Думаю' },
  { emoji: '👀', icon: Eyes, label: 'Глаза' },
  { emoji: '🎉', icon: Confetti, label: 'Праздник' },
]

interface ReactionTask {
  id: number
  account_id: number
  account_name: string
  channels: string[]
  reactions_used: number
  status: 'pending' | 'running' | 'completed' | 'failed'
  reactions_per_day: number
  selected_reactions: string[]
  started_at: string | null
  completed_at: string | null
  created_at: string
}

interface ReactionStats {
  total_tasks: number
  active_tasks: number
  reactions_sent_today: number
  accounts_reacting: number
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType }> = {
  pending: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Clock },
  running: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: SpinnerGap },
  completed: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: CheckCircle },
  failed: { color: 'text-red-600', bg: 'bg-red-500/10', icon: XCircle },
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

function CreateReactionModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [accountId, setAccountId] = useState<number | null>(null)
  const [channels, setChannels] = useState('')
  const [reactions, setReactions] = useState<string[]>(['👍', '❤️', '🔥'])
  const [reactionsPerDay, setReactionsPerDay] = useState(200)
  const [postsPerChannel, setPostsPerChannel] = useState(10)
  const [submitting, setSubmitting] = useState(false)
  const [accounts, setAccounts] = useState<{id: number, name: string}[]>([])

  useEffect(() => {
    if (isOpen) {
      setAccounts([
        { id: 1, name: 'Account 1 (@user1)' },
        { id: 2, name: 'Account 2 (@user2)' },
        { id: 3, name: 'Account 3 (@user3)' },
      ])
    }
  }, [isOpen])

  const toggleReaction = (emoji: string) => {
    setReactions(prev =>
      prev.includes(emoji)
        ? prev.filter(r => r !== emoji)
        : [...prev, emoji]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!accountId) return
    setSubmitting(true)

    try {
      const channelList = channels.split('\n').map(c => c.trim()).filter(Boolean)
      await api.post('/api/v1/reactions/start', {
        account_id: accountId,
        channels: channelList,
        reactions: reactions,
        reactions_per_day: reactionsPerDay,
        posts_per_channel: postsPerChannel,
      })
      onSuccess()
      onClose()
      setChannels('')
    } catch (error) {
      console.error('Ошибка при запуске:', error)
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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-lg max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50 sticky top-0 bg-card rounded-t-3xl">
              <h2 className="text-xl font-semibold">Массовые реакции</h2>
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

              {/* Channels */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Каналы (по одному на строку)</label>
                <textarea
                  value={channels}
                  onChange={(e) => setChannels(e.target.value)}
                  placeholder="@channel1&#10;https://t.me/channel2&#10;@another_channel"
                  rows={4}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none"
                  required
                />
              </div>

              {/* Reaction types */}
              <div className="space-y-3">
                <label className="text-sm font-medium">Типы реакций</label>
                <div className="flex flex-wrap gap-2">
                  {REACTION_EMOJIS.map(({ emoji, icon: Icon, label }) => (
                    <button
                      key={emoji}
                      type="button"
                      onClick={() => toggleReaction(emoji)}
                      className={`flex items-center gap-2 px-3 py-2 rounded-xl border transition-all ${
                        reactions.includes(emoji)
                          ? 'bg-primary/10 border-primary/30 text-primary'
                          : 'bg-card border-border hover:border-border/80'
                      }`}
                    >
                      <span className="text-lg">{emoji}</span>
                      <span className="text-xs">{label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {/* Reactions per day */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center justify-between">
                  <span>Реакций в день</span>
                  <span className="text-primary font-semibold">{reactionsPerDay}</span>
                </label>
                <input
                  type="range"
                  value={reactionsPerDay}
                  onChange={(e) => setReactionsPerDay(Number(e.target.value))}
                  min="50"
                  max="500"
                  step="10"
                  className="w-full accent-primary"
                />
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>50</span>
                  <span>500</span>
                </div>
              </div>

              {/* Posts per channel */}
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center justify-between">
                  <span>Постов на канал</span>
                  <span className="text-primary font-semibold">{postsPerChannel}</span>
                </label>
                <input
                  type="range"
                  value={postsPerChannel}
                  onChange={(e) => setPostsPerChannel(Number(e.target.value))}
                  min="5"
                  max="50"
                  step="5"
                  className="w-full accent-primary"
                />
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
                  {submitting ? 'Запуск...' : 'Запустить'}
                  <Lightning size={18} weight="fill" />
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function TaskRow({ task, onStop, onDelete }: {
  task: ReactionTask
  onStop: () => void
  onDelete: () => void
}) {
  const [showMenu, setShowMenu] = useState(false)
  const config = statusConfig[task.status]
  const StatusIcon = config.icon

  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex items-center gap-4 p-5 hover:bg-muted/30 transition-colors group"
    >
      {/* Reaction Icon */}
      <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-orange-500/20 to-red-500/20 flex items-center justify-center">
        <Fire size={24} className="text-orange-500" weight="duotone" />
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0">
        <p className="font-medium">{task.account_name}</p>
        <p className="text-sm text-muted-foreground truncate">
          {task.channels.length} каналов • {task.selected_reactions.length} типов реакций
        </p>
      </div>

      {/* Reaction Emojis */}
      <div className="flex gap-1">
        {task.selected_reactions.slice(0, 4).map(emoji => (
          <span key={emoji} className="text-lg">{emoji}</span>
        ))}
        {task.selected_reactions.length > 4 && (
          <span className="text-sm text-muted-foreground">+{task.selected_reactions.length - 4}</span>
        )}
      </div>

      {/* Stats */}
      <div className="w-24 text-center">
        <p className="font-semibold">{task.reactions_used.toLocaleString()}</p>
        <p className="text-xs text-muted-foreground">реакций</p>
      </div>

      {/* Status */}
      <div className="w-32">
        <StatusBadge status={task.status} />
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
        {task.status === 'running' && (
          <button
            onClick={onStop}
            className="p-2.5 rounded-xl bg-orange-500/10 text-orange-600 hover:bg-orange-500/20 transition-colors"
            title="Остановить"
          >
            <Pause size={18} weight="fill" />
          </button>
        )}
        <div className="relative">
          <button
            onClick={() => setShowMenu(!showMenu)}
            className="p-2.5 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
          >
            <DotsThree size={18} weight="bold" />
          </button>
          {showMenu && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
              <div className="absolute right-0 top-full mt-2 w-40 bg-card rounded-xl border border-border shadow-xl z-20 py-2">
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
    </motion.div>
  )
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-4"
    >
      <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-orange-500/10 to-red-500/10 flex items-center justify-center mb-6">
        <Fire size={40} className="text-orange-500" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет задач с реакциями</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Создайте задачу для массового добавления реакций к постам в каналах и чатах.
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

export default function Reactions() {
  const [tasks, setTasks] = useState<ReactionTask[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const fetchTasks = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/reactions')
      setTasks(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
      setTasks([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [])

  const handleStop = async (id: number) => {
    try {
      await api.post(`/api/v1/reactions/${id}/stop`)
      fetchTasks()
    } catch (error) {
      console.error('Ошибка при остановке:', error)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить эту задачу?')) return
    try {
      await api.delete(`/api/v1/reactions/${id}`)
      fetchTasks()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const stats: ReactionStats = {
    total_tasks: tasks.length,
    active_tasks: tasks.filter(t => t.status === 'running').length,
    reactions_sent_today: tasks.reduce((sum, t) => sum + t.reactions_used, 0),
    accounts_reacting: new Set(tasks.filter(t => t.status === 'running').map(t => t.account_id)).size,
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
          <h1 className="text-3xl font-bold tracking-tight">Реакции</h1>
          <p className="text-muted-foreground mt-1">Массовые реакции на посты</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-orange-500 to-red-500 text-white font-medium hover:opacity-90 transition-opacity shadow-lg shadow-orange-500/20"
        >
          <Plus size={18} weight="bold" />
          Новая задача
        </button>
      </motion.div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{stats.total_tasks}</p>
          <p className="text-sm text-muted-foreground">Всего задач</p>
        </div>
        <div className="p-5 rounded-2xl bg-blue-500/5 border border-blue-500/20">
          <p className="text-3xl font-bold text-blue-600">{stats.active_tasks}</p>
          <p className="text-sm text-muted-foreground">Активных</p>
        </div>
        <div className="p-5 rounded-2xl bg-orange-500/5 border border-orange-500/20">
          <p className="text-3xl font-bold text-orange-600">{stats.reactions_sent_today.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">Реакций сегодня</p>
        </div>
        <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
          <p className="text-3xl font-bold text-emerald-600">{stats.accounts_reacting}</p>
          <p className="text-sm text-muted-foreground">Аккаунтов</p>
        </div>
      </div>

      {/* Tasks List */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-20 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <EmptyState onAdd={() => setIsModalOpen(true)} />
      ) : (
        <motion.div
          layout
          className="bg-card rounded-2xl border border-border/50 overflow-hidden"
        >
          {/* Table Header */}
          <div className="grid grid-cols-[48px_1fr_auto_96px_128px_auto] gap-4 px-5 py-3 border-b border-border/50 text-sm font-medium text-muted-foreground">
            <div></div>
            <div>Аккаунт</div>
            <div>Типы</div>
            <div className="text-center">Реакций</div>
            <div>Статус</div>
            <div></div>
          </div>

          {/* Table Body */}
          <div className="divide-y divide-border/30">
            <AnimatePresence mode="popLayout">
              {tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  onStop={() => handleStop(task.id)}
                  onDelete={() => handleDelete(task.id)}
                />
              ))}
            </AnimatePresence>
          </div>
        </motion.div>
      )}

      <CreateReactionModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchTasks}
      />
    </div>
  )
}