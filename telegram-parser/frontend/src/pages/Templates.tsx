import { useState, useEffect, forwardRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Trash,
  X,
  PencilSimple,
  TextAa,
  Info,
  CaretDown,
  Lightbulb,
  Sparkle,
  Check
} from '@phosphor-icons/react'

interface Template {
  id: number
  name: string
  content: string
  created_at: string
}

const TemplateCard = forwardRef<HTMLDivElement, { template: Template, onEdit: () => void, onDelete: () => void }>(({ template, onEdit, onDelete }, ref) => {
  const [expanded, setExpanded] = useState(false)

  return (
    <motion.div
      ref={ref}
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="bg-card rounded-2xl border border-border/50 overflow-hidden hover:border-border transition-colors group"
    >
      {/* Header */}
      <div className="p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 rounded-2xl bg-primary/10 flex items-center justify-center">
              <TextAa size={24} className="text-primary" weight="duotone" />
            </div>
            <div>
              <h3 className="font-semibold">{template.name}</h3>
              <p className="text-sm text-muted-foreground">
                Создан {new Date(template.created_at).toLocaleDateString('ru')}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <button
              onClick={onEdit}
              className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground hover:text-foreground"
            >
              <PencilSimple size={18} />
            </button>
            <button
              onClick={onDelete}
              className="p-2 rounded-xl hover:bg-red-500/10 transition-colors text-muted-foreground hover:text-red-600"
            >
              <Trash size={18} />
            </button>
          </div>
        </div>

        {/* Preview */}
        <div className="relative">
          <p className={`text-sm text-muted-foreground leading-relaxed ${expanded ? '' : 'line-clamp-2'}`}>
            {template.content}
          </p>
          {!expanded && template.content.length > 100 && (
            <button
              onClick={() => setExpanded(true)}
              className="absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-card to-transparent flex items-center justify-center text-xs text-primary hover:underline"
            >
              Показать полностью
            </button>
          )}
        </div>
      </div>

      {/* Tags preview */}
      <div className="px-6 pb-4 flex flex-wrap gap-2">
        {template.content.match(/\{[^}]+\}/g)?.slice(0, 3).map((tag, i) => (
          <span key={i} className="px-2 py-1 rounded-lg bg-muted text-xs font-mono text-muted-foreground">
            {tag}
          </span>
        )) || null}
        {(template.content.match(/\{[^}]+\}/g)?.length || 0) > 3 && (
          <span className="px-2 py-1 rounded-lg bg-muted text-xs text-muted-foreground">
            +{(template.content.match(/\{[^}]+\}/g)?.length || 0) - 3} тегов
          </span>
        )}
      </div>
    </motion.div>
  )
})

function TemplateForm({ isOpen, onClose, onSuccess, template }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
  template?: Template | null
}) {
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (template) {
      setName(template.name)
      setContent(template.content)
    } else {
      setName('')
      setContent('')
    }
  }, [template])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setSubmitting(true)
    try {
      if (template) {
        await api.put(`/api/v1/templates/${template.id}`, { name, content })
      } else {
        await api.post('/api/v1/templates', { name, content })
      }
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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold">
                {template ? 'Редактировать шаблон' : 'Новый шаблон'}
              </h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-6 flex-1 overflow-y-auto">
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <TextAa size={16} />
                  Название шаблона
                </label>
                <input
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Приветствие для новых клиентов"
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                  required
                />
              </div>

              <div className="space-y-2">
                <label className="text-sm font-medium">Текст сообщения</label>
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Привет, {first_name}!&#10;&#10;Используйте Spintax и переменные для персонализации."
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all h-40 resize-none font-mono text-sm"
                  required
                />
              </div>

              {/* Help section */}
              <div className="p-4 rounded-2xl bg-muted/50 border border-border/30 space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Lightbulb size={18} className="text-primary" />
                  Синтаксис шаблонов
                </div>
                <div className="grid grid-cols-2 gap-4 text-sm">
                  <div className="p-3 rounded-xl bg-card">
                    <code className="text-primary font-mono">{"{Привет|Здравствуйте}"}</code>
                    <p className="text-xs text-muted-foreground mt-1">Случайный выбор из вариантов</p>
                  </div>
                  <div className="p-3 rounded-xl bg-card">
                    <code className="text-primary font-mono">{"{first_name}"}</code>
                    <p className="text-xs text-muted-foreground mt-1">Имя контакта из базы</p>
                  </div>
                  <div className="p-3 rounded-xl bg-card">
                    <code className="text-primary font-mono">{"{username}"}</code>
                    <p className="text-xs text-muted-foreground mt-1">Имя пользователя Telegram</p>
                  </div>
                  <div className="p-3 rounded-xl bg-card">
                    <code className="text-primary font-mono">{"{phone}"}</code>
                    <p className="text-xs text-muted-foreground mt-1">Номер телефона</p>
                  </div>
                </div>
              </div>

              {/* Preview */}
              <div className="p-4 rounded-2xl bg-primary/5 border border-primary/20">
                <div className="flex items-center gap-2 text-sm font-medium text-primary mb-3">
                  <Sparkle size={16} />
                  Предпросмотр
                </div>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {content
                    .replace(/\{([^|}]+)\|([^}]+)\}/g, '$1')
                    .replace(/\{([^}]+)\}/g, '[Имя]')
                    .replace(/\n/g, ' ')}
                </p>
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
                  {submitting ? 'Сохранение...' : template ? 'Обновить' : 'Сохранить'}
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

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-4"
    >
      <div className="w-20 h-20 rounded-3xl bg-primary/10 flex items-center justify-center mb-6">
        <TextAa size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет шаблонов</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Создайте шаблоны сообщений с переменными и Spintax для персонализированных рассылок.
      </p>
      <button
        onClick={onAdd}
        className="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
      >
        <Plus size={18} weight="bold" />
        Создать шаблон
      </button>
    </motion.div>
  )
}

export default function Templates() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [editingTemplate, setEditingTemplate] = useState<Template | null>(null)

  const fetchTemplates = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/templates')
      setTemplates(response.data)
    } catch (error) {
      console.error('Ошибка при загрузке:', error)
      setTemplates([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchTemplates()
  }, [])

  const handleEdit = (template: Template) => {
    setEditingTemplate(template)
    setIsFormOpen(true)
  }

  const handleDelete = async (id: number) => {
    if (!confirm('Удалить этот шаблон?')) return
    try {
      await api.delete(`/api/v1/templates/${id}`)
      fetchTemplates()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const handleFormClose = () => {
    setIsFormOpen(false)
    setEditingTemplate(null)
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
          <h1 className="text-3xl font-bold tracking-tight">Шаблоны</h1>
          <p className="text-muted-foreground mt-1">Шаблоны сообщений с персонализацией</p>
        </div>
        <button
          onClick={() => setIsFormOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Plus size={18} weight="bold" />
          Создать
        </button>
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">{templates.length}</p>
          <p className="text-sm text-muted-foreground">Всего шаблонов</p>
        </div>
        <div className="p-5 rounded-2xl bg-card border border-border/50">
          <p className="text-3xl font-bold">
            {templates.reduce((sum, t) => sum + (t.content.match(/\{[^}]+\}/g)?.length || 0), 0)}
          </p>
          <p className="text-sm text-muted-foreground">Переменных</p>
        </div>
        <div className="p-5 rounded-2xl bg-primary/5 border border-primary/20">
          <p className="text-3xl font-bold text-primary">
            {templates.filter(t => t.content.includes('|')).length}
          </p>
          <p className="text-sm text-muted-foreground">Со Spintax</p>
        </div>
      </div>

      {/* Templates Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-48 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : templates.length === 0 ? (
        <EmptyState onAdd={() => setIsFormOpen(true)} />
      ) : (
        <motion.div layout className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
          <AnimatePresence mode="popLayout">
            {templates.map((template) => (
              <TemplateCard
                key={template.id}
                template={template}
                onEdit={() => handleEdit(template)}
                onDelete={() => handleDelete(template.id)}
              />
            ))}
          </AnimatePresence>
        </motion.div>
      )}

      <TemplateForm
        isOpen={isFormOpen}
        onClose={handleFormClose}
        onSuccess={fetchTemplates}
        template={editingTemplate}
      />
    </div>
  )
}
