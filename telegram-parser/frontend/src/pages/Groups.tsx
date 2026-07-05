import { useState, useEffect } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Play,
  Pause,
  X,
  Users,
  CheckCircle,
  XCircle,
  Clock,
  DotsThree,
  Trash,
  Lightning,
  SpinnerGap,
  ShieldCheck,
  Link as LinkIcon
} from '@phosphor-icons/react'

interface GroupTask {
  id: number
  account_id: number
  account_name: string
  groups: string[]
  status: 'pending' | 'running' | 'completed' | 'failed' | 'stopped'
  groups_joined: number
  started_at: string | null
  completed_at: string | null
  created_at: string
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType }> = {
  pending: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Clock },
  running: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: SpinnerGap },
  completed: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: CheckCircle },
  failed: { color: 'text-red-600', bg: 'bg-red-500/10', icon: XCircle },
  stopped: { color: 'text-orange-600', bg: 'bg-orange-500/10', icon: Pause },
}

function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status] || statusConfig.pending
  const Icon = config.icon

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      <Icon size={12} weight="bold" className={status === 'running' ? 'animate-spin' : ''} />
      {status === 'completed' ? 'Готово' : status === 'failed' ? 'Ошибка' : status === 'running' ? 'В процессе' : status === 'stopped' ? 'Остановлено' : 'Ожидание'}
    </span>
  )
}

function CreateGroupTaskModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [accountId, setAccountId] = useState<number | null>(null)
  const [groups, setGroups] = useState('')
  const [delayMin, setDelayMin] = useState(30)
  const [delayMax, setDelayMax] = useState(120)
  const [submitting, setSubmitting] = useState(false)
  const [accounts, setAccounts] = useState<{id: number, phone_number: string}[]>([])
  const [safeGroups, setSafeGroups] = useState<string[]>([])
  const [savedSources, setSavedSources] = useState<string[]>([])

  useEffect(() => {
    if (isOpen) {
      const fetchData = async () => {
        try {
          const [accsRes, safeRes, sourcesRes] = await Promise.all([
            api.get('/api/v1/accounts'),
            api.get('/api/v1/groups/safe-groups'),
            api.get('/api/v1/telegram-sources'),
          ])
          setAccounts(accsRes.data)
          setSafeGroups(safeRes.data)
          setSavedSources(sourcesRes.data.map((source: { normalized_link: string }) => source.normalized_link))
        } catch (error) {
          console.error('Ошибка при загрузке данных:', error)
        }
      }
      fetchData()
    }
  }, [isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!accountId) return
    setSubmitting(true)

    try {
      const groupList = groups.split('\n').map(c => c.trim()).filter(Boolean)
      await api.post('/api/v1/groups', {
        account_id: accountId,
        groups: groupList,
        delay_min: delayMin,
        delay_max: delayMax,
      })
      onSuccess()
      onClose()
      setGroups('')
    } catch (error) {
      console.error('Ошибка при запуске:', error)
    } finally {
      setSubmitting(false)
    }
  }

  const addSafeGroups = () => {
    setGroups(prev => {
      const current = prev.split('\n').map(c => c.trim()).filter(Boolean)
      const uniqueSafe = safeGroups.filter(g => !current.includes(g))
      return [...current, ...uniqueSafe].join('\n')
    })
  }

  const addSavedSources = () => {
    setGroups(prev => {
      const current = prev.split('\n').map(c => c.trim()).filter(Boolean)
      const uniqueSaved = savedSources.filter(source => !current.includes(source))
      return [...current, ...uniqueSaved].join('\n')
    })
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
              <h2 className="text-xl font-semibold">Авто-вступление в группы</h2>
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
                    <option key={acc.id} value={acc.id}>{acc.phone_number}</option>
                  ))}
                </select>
              </div>

              {/* Groups */}
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <label className="text-sm font-medium">Группы (username или ссылка)</label>
                  <div className="flex gap-3">
                    <button type="button" onClick={addSavedSources} className="text-xs text-primary hover:underline flex items-center gap-1">
                      <LinkIcon size={14} />
                      Из источников
                    </button>
                    <button type="button" onClick={addSafeGroups} className="text-xs text-primary hover:underline flex items-center gap-1">
                      <ShieldCheck size={14} />
                      Безопасные
                    </button>
                  </div>
                </div>
                <textarea
                  value={groups}
                  onChange={(e) => setGroups(e.target.value)}
                  placeholder="@group1&#10;https://t.me/group2"
                  rows={4}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none font-mono text-sm"
                  required
                />
              </div>

              {/* Delays */}
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium">Мин. задержка (сек)</label>
                  <input
                    type="number"
                    value={delayMin}
                    onChange={(e) => setDelayMin(Number(e.target.value))}
                    min="10"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium">Макс. задержка (сек)</label>
                  <input
                    type="number"
                    value={delayMax}
                    onChange={(e) => setDelayMax(Number(e.target.value))}
                    min="20"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
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

function TaskRow({ task, onStop }: {
  task: GroupTask
  onStop: () => void
}) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex items-center gap-4 p-5 hover:bg-muted/30 transition-colors group"
    >
      <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-blue-500/20 to-indigo-500/20 flex items-center justify-center">
        <Users size={24} className="text-blue-500" weight="duotone" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="font-medium">{task.account_name}</p>
        <p className="text-sm text-muted-foreground truncate">
          {task.groups.length} групп • {task.groups_joined} вступил
        </p>
      </div>

      <div className="w-32">
        <StatusBadge status={task.status} />
      </div>

      <div className="flex items-center gap-2">
        {task.status === 'running' && (
          <button
            onClick={onStop}
            className="p-2.5 rounded-xl bg-orange-500/10 text-orange-600 hover:bg-orange-500/20 transition-colors"
            title="Остановить"
          >
            <Pause size={18} weight="fill" />
          </button>
        )}
      </div>
    </motion.div>
  )
}

export default function Groups() {
  const [tasks, setTasks] = useState<GroupTask[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const fetchTasks = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/groups')
      setTasks(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTasks()
    const interval = setInterval(fetchTasks, 10000)
    return () => clearInterval(interval)
  }, [])

  const handleStop = async (id: number) => {
    try {
      await api.post(`/api/v1/groups/${id}/stop`)
      fetchTasks()
    } catch (error) {
      console.error('Ошибка при остановке:', error)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Группы</h1>
          <p className="text-muted-foreground mt-1">Автоматическое вступление в группы и сообщества</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
        >
          <Plus size={18} weight="bold" />
          Новая задача
        </button>
      </div>

      {loading && tasks.length === 0 ? (
        <div className="flex items-center justify-center py-20">
          <SpinnerGap size={32} className="animate-spin text-primary" />
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-20 bg-card rounded-3xl border border-dashed border-border">
          <Users size={48} className="mx-auto text-muted-foreground mb-4" />
          <h3 className="text-lg font-medium">Нет активных задач</h3>
          <p className="text-muted-foreground mt-1">Создайте задачу, чтобы начать автоматическое вступление в группы</p>
        </div>
      ) : (
        <div className="bg-card rounded-3xl border border-border overflow-hidden">
          <div className="divide-y divide-border">
            {tasks.map(task => (
              <TaskRow key={task.id} task={task} onStop={() => handleStop(task.id)} />
            ))}
          </div>
        </div>
      )}

      <CreateGroupTaskModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchTasks}
      />
    </div>
  )
}
