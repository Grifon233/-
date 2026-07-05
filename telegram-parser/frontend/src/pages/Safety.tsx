import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Check,
  X,
  ShieldCheck,
  ShieldWarning,
  ArrowsClockwise,
  FileText,
  IdentificationBadge,
  SpinnerGap,
} from '@phosphor-icons/react'

import api from '@/services/api'

interface Draft {
  id: number
  source_id: string
  post_id: number
  draft: string
  status: string
  created_at: string
  moderation_result: any
  context?: string
}

interface Source {
  id: number
  source_id: string
  source_type: string
  source_title: string
  consent_verified: boolean
}

const draftStatusConfig: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'Ожидает', color: 'text-amber-600', bg: 'bg-amber-500/10' },
  approved: { label: 'Одобрен', color: 'text-emerald-600', bg: 'bg-emerald-500/10' },
  rejected: { label: 'Отклонён', color: 'text-red-600', bg: 'bg-red-500/10' },
  published: { label: 'Опубликован', color: 'text-blue-600', bg: 'bg-blue-500/10' },
}

function StatusBadge({ status }: { status: string }) {
  const config = draftStatusConfig[status] || draftStatusConfig.pending
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}
    >
      {config.label}
    </span>
  )
}

export default function SafetyPage() {
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [sources, setSources] = useState<Source[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeTab, setActiveTab] = useState<'drafts' | 'sources'>('drafts')
  const [busyDraftId, setBusyDraftId] = useState<number | null>(null)

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadData = async () => {
    setLoading(true)
    setError('')
    try {
      // The drafts endpoint accepts an optional ``status`` query
      // parameter. We only show pending drafts in the moderation
      // queue; approved/rejected/published live in the journal.
      const [draftsRes, sourcesRes] = await Promise.all([
        api.get('/api/v1/safety/drafts', { params: { status: 'pending' } }),
        api.get('/api/v1/safety/sources'),
      ])
      setDrafts(Array.isArray(draftsRes.data) ? draftsRes.data : [])
      setSources(Array.isArray(sourcesRes.data) ? sourcesRes.data : [])
    } catch (e: any) {
      const detail =
        e.response?.data?.detail || e.message || 'Не удалось загрузить данные модерации'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  const handleModerate = async (draftId: number, action: 'approve' | 'reject') => {
    setBusyDraftId(draftId)
    try {
      await api.post(`/api/v1/safety/drafts/${draftId}/moderate`, { action })
      // Refresh the list so the operator sees the new state.
      await loadData()
    } catch (e: any) {
      const detail = e.response?.data?.detail || e.message || 'Ошибка модерации'
      setError(detail)
    } finally {
      setBusyDraftId(null)
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <SpinnerGap size={48} className="animate-spin text-primary/50 mx-auto mb-4" />
          <p className="text-muted-foreground">Загрузка данных модерации...</p>
        </div>
      </div>
    )
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
          <h1 className="text-3xl font-bold tracking-tight">Безопасность и модерация</h1>
          <p className="text-muted-foreground mt-1">
            Черновики комментариев и allowlist источников
          </p>
        </div>
        <button
          onClick={loadData}
          className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
        >
          <ArrowsClockwise size={18} />
          Обновить
        </button>
      </motion.div>

      {error && (
        <div className="rounded-2xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-600">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-border/50">
        {[
          { key: 'drafts' as const, label: 'Черновики', count: drafts.length, icon: FileText },
          { key: 'sources' as const, label: 'Источники', count: sources.length, icon: IdentificationBadge },
        ].map((tab) => {
          const isActive = activeTab === tab.key
          const Icon = tab.icon
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`inline-flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
                isActive
                  ? 'border-primary text-primary'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`}
            >
              <Icon size={16} weight={isActive ? 'fill' : 'regular'} />
              {tab.label} ({tab.count})
            </button>
          )
        })}
      </div>

      <AnimatePresence mode="wait">
        {activeTab === 'drafts' && (
          <motion.div
            key="drafts"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="space-y-3"
          >
            {drafts.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 px-4 rounded-3xl border border-border/50 bg-card">
                <ShieldCheck size={48} className="text-muted-foreground/50 mb-4" />
                <h3 className="text-xl font-semibold mb-2">Нет ожидающих черновиков</h3>
                <p className="text-muted-foreground text-center max-w-md">
                  Когда нейрокомментинг создаст черновик, он появится здесь для модерации.
                </p>
              </div>
            ) : (
              drafts.map((draft) => (
                <div
                  key={draft.id}
                  className="bg-card border border-border/50 rounded-2xl p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-2 mb-3">
                    <div className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="font-mono">{draft.source_id}</span>
                      <span className="text-muted-foreground">Post #{draft.post_id}</span>
                    </div>
                    <StatusBadge status={draft.status} />
                  </div>
                  {draft.context && (
                    <p className="text-xs text-muted-foreground mb-3 p-2 bg-muted/50 rounded-lg">
                      <ShieldWarning size={12} className="inline mr-1" />
                      Контекст: {draft.context.slice(0, 200)}
                      {draft.context.length > 200 ? '…' : ''}
                    </p>
                  )}
                  <p className="text-sm mb-4 p-3 bg-muted/50 rounded-lg whitespace-pre-wrap">
                    {draft.draft}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleModerate(draft.id, 'approve')}
                      disabled={busyDraftId === draft.id}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 font-medium text-sm disabled:opacity-50"
                    >
                      {busyDraftId === draft.id ? (
                        <SpinnerGap size={14} className="animate-spin" />
                      ) : (
                        <Check size={14} weight="bold" />
                      )}
                      Опубликовать
                    </button>
                    <button
                      onClick={() => handleModerate(draft.id, 'reject')}
                      disabled={busyDraftId === draft.id}
                      className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-red-500/10 text-red-600 hover:bg-red-500/20 font-medium text-sm disabled:opacity-50"
                    >
                      <X size={14} weight="bold" />
                      Отклонить
                    </button>
                  </div>
                </div>
              ))
            )}
          </motion.div>
        )}

        {activeTab === 'sources' && (
          <motion.div
            key="sources"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="bg-card rounded-2xl border border-border/50 overflow-hidden"
          >
            {sources.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 px-4">
                <IdentificationBadge size={48} className="text-muted-foreground/50 mb-4" />
                <h3 className="text-xl font-semibold mb-2">Нет источников</h3>
                <p className="text-muted-foreground text-center max-w-md">
                  Добавьте Telegram-источники в разделе «Источники», чтобы они появились здесь
                  для верификации.
                </p>
              </div>
            ) : (
              <div className="divide-y divide-border/30">
                {sources.map((source) => (
                  <div
                    key={source.id}
                    className="flex items-center justify-between gap-4 px-5 py-3 hover:bg-muted/30 transition-colors"
                  >
                    <div className="min-w-0">
                      <p className="font-mono text-sm truncate">{source.source_id}</p>
                      <p className="text-xs text-muted-foreground">
                        {source.source_type} · {source.source_title}
                      </p>
                    </div>
                    {source.consent_verified ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium text-emerald-600 bg-emerald-500/10">
                        <ShieldCheck size={12} weight="bold" />
                        Verified
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium text-amber-600 bg-amber-500/10">
                        <ShieldWarning size={12} weight="bold" />
                        Pending
                      </span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
