import { useState, useEffect, forwardRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Play,
  Pause,
  Trash,
  PaperPlaneTilt,
  Clock,
  ChartLine,
  X,
  Check,
  Lightning,
  Timer,
  DotsThree,
  ArrowRight
} from '@phosphor-icons/react'

interface Template {
  id: number
  name: string
}

interface Campaign {
  id: number
  name: string
  template_id: number
  status: 'draft' | 'scheduled' | 'running' | 'paused' | 'completed' | 'failed'
  min_delay: number
  max_delay: number
  sent_count: number
  failed_count: number
  total_contacts?: number
  total_recipients?: number
  created_at: string
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  draft: { color: 'text-muted-foreground', bg: 'bg-muted', icon: Clock, label: 'Черновик' },
  scheduled: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: Clock, label: 'Запланирована' },
  running: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: Lightning, label: 'Активна' },
  paused: { color: 'text-amber-600', bg: 'bg-amber-500/10', icon: Pause, label: 'На паузе' },
  completed: { color: 'text-primary', bg: 'bg-primary/10', icon: Check, label: 'Завершена' },
  failed: { color: 'text-red-600', bg: 'bg-red-500/10', icon: X, label: 'Ошибка' },
}

function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status] || statusConfig.draft
  const Icon = config.icon

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      <Icon size={12} weight="bold" />
      {config.label}
    </span>
  )
}

function CreateCampaignModal({ isOpen, onClose, onSuccess, templates }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  templates: Template[]
}) {
  const [name, setName] = useState('')
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [minDelay, setMinDelay] = useState(30)
  const [maxDelay, setMaxDelay] = useState(120)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!templateId) return

    setSubmitting(true)
    try {
      await api.post('/api/v1/campaigns', {
        name,
        template_id: templateId,
        min_delay: minDelay,
        max_delay: maxDelay
      })
      onSuccess()
      onClose()
      setName('')
      setTemplateId('')
      setMinDelay(30)
      setMaxDelay(120)
    } catch (error) {
      console.error('Ошибка при создании:', error)
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
              <h2 className="text-xl font-semibold">Создать кампанию</h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-medium">Название кампании</label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Напр: Акция Марта 2024"
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  required
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Шаблон сообщения</label>
                <select
                  value={templateId}
                  onChange={(e) => setTemplateId(Number(e.target.value))}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  required
                >
                  <option value="">Выберите шаблон...</option>
                  {templates.map(t => (
                    <option key={t.id} value={t.id}>{t.name}</option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <Timer size={14} />
                    Мин. задержка (сек)
                  </label>
                  <input
                    type="number"
                    value={minDelay}
                    onChange={(e) => setMinDelay(Number(e.target.value))}
                    min="1"
                    className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium flex items-center gap-2">
                    <Timer size={14} />
                    Макс. задержка (сек)
                  </label>
                  <input
                    type="number"
                    value={maxDelay}
                    onChange={(e) => setMaxDelay(Number(e.target.value))}
                    min="1"
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
                  disabled={submitting}
                  className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground hover:bg-primary/90 transition-colors font-medium disabled:opacity-50 flex items-center justify-center gap-2"
                >
                  {submitting ? 'Создание...' : 'Создать'}
                  <Check size={18} weight="bold" />
                </button>
              </div>
            </form>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const CampaignCard = forwardRef<HTMLDivElement, { campaign: Campaign, onStart: () => void, onPause: () => void, onDelete: () => void }>(({ campaign, onStart, onPause, onDelete }, ref) => {
  const [showMenu, setShowMenu] = useState(false)
  const totalRecipients = campaign.total_contacts || campaign.total_recipients || 0
  const progress = totalRecipients > 0
    ? Math.round((campaign.sent_count / totalRecipients) * 100)
    : 0
  const config = statusConfig[campaign.status] || statusConfig.draft

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="bg-card rounded-2xl border border-border/50 p-6 hover:border-border transition-colors group"
    >
      <div className="flex items-start justify-between mb-5">
        <div className="flex items-center gap-4">
          <div className={`w-12 h-12 rounded-2xl ${config.bg} flex items-center justify-center`}>
            <config.icon size={24} className={config.color} weight="duotone" />
          </div>
          <div>
            <h3 className="font-semibold">{campaign.name}</h3>
            <p className="text-sm text-muted-foreground">
              Создана {new Date(campaign.created_at).toLocaleDateString('ru')}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={campaign.status} />
          <div className="relative">
            <button
              onClick={() => setShowMenu(!showMenu)}
              className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
            >
              <DotsThree size={20} weight="bold" />
            </button>
            {showMenu && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
                <div className="absolute right-0 top-full mt-2 w-44 bg-card rounded-xl border border-border shadow-xl z-20 py-2">
                  {campaign.status === 'draft' && (
                    <button
                      onClick={() => { onStart(); setShowMenu(false); }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                    >
                      <Play size={16} />
                      Запустить
                    </button>
                  )}
                  {campaign.status === 'running' && (
                    <button
                      onClick={() => { onPause(); setShowMenu(false); }}
                      className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm"
                    >
                      <Pause size={16} />
                      Пауза
                    </button>
                  )}
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

      {/* Progress */}
      <div className="space-y-3 mb-5">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Прогресс</span>
          <span className="font-medium">{(campaign.sent_count || 0).toLocaleString()} / {(campaign.total_contacts || campaign.total_recipients || 0).toLocaleString()}</span>
        </div>
        <div className="h-2 bg-muted rounded-full overflow-hidden">
          <motion.div
            className="h-full bg-primary rounded-full"
            initial={{ width: 0 }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.8 }}
          />
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 pt-4 border-t border-border/30">
        <div className="text-center">
          <p className="text-lg font-bold text-emerald-600">{campaign.sent_count}</p>
          <p className="text-xs text-muted-foreground">Отправлено</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold text-red-600">{campaign.failed_count}</p>
          <p className="text-xs text-muted-foreground">Ошибки</p>
        </div>
        <div className="text-center">
          <p className="text-lg font-bold">{campaign.min_delay}-{campaign.max_delay}с</p>
          <p className="text-xs text-muted-foreground">Задержка</p>
        </div>
      </div>

      {/* Actions */}
      {(campaign.status === 'draft' || campaign.status === 'paused') && (
        <button
          onClick={onStart}
          className="w-full mt-5 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors flex items-center justify-center gap-2"
        >
          <Play size={18} weight="fill" />
          Запустить рассылку
        </button>
      )}
      {campaign.status === 'running' && (
        <button
          onClick={onPause}
          className="w-full mt-5 py-3 rounded-xl border border-border font-medium hover:bg-muted transition-colors flex items-center justify-center gap-2"
        >
          <Pause size={18} weight="fill" />
          Поставить на паузу
        </button>
      )}
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
        <PaperPlaneTilt size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет кампаний</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Создайте кампанию для массовой рассылки сообщений по вашей базе контактов.
      </p>
      <button
        onClick={onAdd}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
      >
        <Plus size={18} weight="bold" />
        Создать кампанию
      </button>
    </motion.div>
  )
}

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [isModalOpen, setIsModalOpen] = useState(false)

  const fetchCampaigns = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/campaigns')
      setCampaigns(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
      setCampaigns([])
    } finally {
      setLoading(false)
    }
  }

  const fetchTemplates = async () => {
    try {
      const response = await api.get('/api/v1/templates')
      setTemplates(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке шаблонов:', error)
      setTemplates([])
    }
  }

  useEffect(() => {
    fetchCampaigns()
    fetchTemplates()
  }, [])

  const handleStart = async (id: number) => {
    try {
      await api.post(`/api/v1/campaigns/${id}/start`)
      fetchCampaigns()
    } catch (error) {
      console.error('Ошибка при запуске:', error)
    }
  }

  const handlePause = async (id: number) => {
    try {
      await api.post(`/api/v1/campaigns/${id}/pause`)
      fetchCampaigns()
    } catch (error) {
      console.error('Ошибка при паузе:', error)
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить эту кампанию?')) return
    try {
      await api.delete(`/api/v1/campaigns/${id}`)
      fetchCampaigns()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const stats = {
    total: campaigns.length,
    running: campaigns.filter(c => c.status === 'running').length,
    completed: campaigns.filter(c => c.status === 'completed').length,
    totalSent: campaigns.reduce((sum, c) => sum + c.sent_count, 0),
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
          <h1 className="text-3xl font-bold tracking-tight">Рассылки</h1>
          <p className="text-muted-foreground mt-1">Управление кампаниями</p>
        </div>
        <button
          onClick={() => setIsModalOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus size={18} weight="bold" />
          Создать кампанию
        </button>
      </motion.div>

      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{stats.total}</p>
          <p className="text-sm text-muted-foreground">Всего кампаний</p>
        </div>
        <div className="p-5 rounded-2xl bg-emerald-500/5 border border-emerald-500/20">
          <p className="text-3xl font-bold text-emerald-600">{stats.running}</p>
          <p className="text-sm text-muted-foreground">Активных</p>
        </div>
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{stats.completed}</p>
          <p className="text-sm text-muted-foreground">Завершено</p>
        </div>
        <div className="p-5 rounded-2xl bg-primary/5 border border-primary/20">
          <p className="text-3xl font-bold text-primary">{stats.totalSent.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">Всего отправлено</p>
        </div>
      </div>

      {/* Campaigns Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-72 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : campaigns.length === 0 ? (
        <EmptyState onAdd={() => setIsModalOpen(true)} />
      ) : (
        <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          <AnimatePresence mode="popLayout">
            {campaigns.map((campaign) => (
              <CampaignCard
                key={campaign.id}
                campaign={campaign}
                onStart={() => handleStart(campaign.id)}
                onPause={() => handlePause(campaign.id)}
                onDelete={() => handleDelete(campaign.id)}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      <CreateCampaignModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={fetchCampaigns}
        templates={templates}
      />
    </div>
  )
}