import { useState, useEffect, useRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Plus,
  Upload,
  Trash,
  X,
  User,
  Phone,
  At,
  MagnifyingGlass,
  FunnelSimple,
  DotsThree,
  Check,
  UserCircle,
  ChatCircle,
  UserMinus
} from '@phosphor-icons/react'

interface Contact {
  id: number
  group_id?: number | null
  telegram_id: string
  username?: string
  first_name?: string
  last_name?: string
  phone_number?: string
  source: string
  is_processed: boolean
  created_at: string
}

interface ContactGroup {
  id: number
  name: string
  description?: string | null
}

const statusConfig: Record<string, { color: string; bg: string; icon: React.ElementType; label: string }> = {
  new: { color: 'text-blue-600', bg: 'bg-blue-500/10', icon: UserCircle, label: 'Новый' },
  contacted: { color: 'text-amber-600', bg: 'bg-amber-500/10', icon: ChatCircle, label: 'Обработан' },
  replied: { color: 'text-emerald-600', bg: 'bg-emerald-500/10', icon: Check, label: 'Ответил' },
  blocked: { color: 'text-red-600', bg: 'bg-red-500/10', icon: UserMinus, label: 'Заблокирован' },
}

function StatusBadge({ status }: { status: string }) {
  const config = statusConfig[status] || statusConfig.new
  const Icon = config.icon

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${config.color} ${config.bg}`}>
      <Icon size={12} weight="bold" />
      {config.label}
    </span>
  )
}

function UploadModal({ isOpen, onClose, onSuccess }: {
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}) {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  // Two independent refs — previously both file inputs shared a single
  // ref, so clicking the Excel button always opened the file picker
  // for the first <input> (CSV). See HIGH-010 from the 2026-06-02 audit.
  const csvInputRef = useRef<HTMLInputElement>(null)
  const excelInputRef = useRef<HTMLInputElement>(null)

  const handleUpload = async (event: React.ChangeEvent<HTMLInputElement>, type: 'csv' | 'excel') => {
    const file = event.target.files?.[0]
    if (!file) return

    const formData = new FormData()
    formData.append('file', file)

    const endpoint = type === 'csv' ? 'upload-csv' : 'upload-excel'

    setUploading(true)
    setError('')
    try {
      const response = await api.post(`/api/v1/contacts/${endpoint}`, formData)
      const imported = response.data?.imported ?? 0
      const skipped = response.data?.skipped_duplicates ?? 0
      const errs = response.data?.errors ?? []
      // Surface partial-success so the operator understands what
      // happened when not every row is accepted.
      const parts: string[] = []
      if (imported) parts.push(`импортировано ${imported}`)
      if (skipped) parts.push(`пропущено дублей ${skipped}`)
      if (errs.length) parts.push(`ошибок ${errs.length}`)
      // eslint-disable-next-line no-console
      console.log('[Contacts] upload report:', response.data)
      onSuccess()
      onClose()
    } catch (e: any) {
      const detail =
        e.response?.data?.detail ||
        e.message ||
        'Не удалось загрузить файл'
      setError(detail)
    } finally {
      setUploading(false)
      // Reset the value so the same file can be selected again.
      const ref = type === 'csv' ? csvInputRef : excelInputRef
      if (ref.current) ref.current.value = ''
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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold">Загрузить контакты</h2>
              <button
                onClick={onClose}
                className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground"
              >
                <X size={20} />
              </button>
            </div>

            <div className="p-6 space-y-4">
              {error && (
                <p className="text-sm text-red-500 bg-red-500/10 px-4 py-2 rounded-lg">
                  {error}
                </p>
              )}

              <input
                type="file"
                ref={csvInputRef}
                onChange={(e) => handleUpload(e, 'csv')}
                className="hidden"
                accept=".csv"
              />
              <input
                type="file"
                ref={excelInputRef}
                onChange={(e) => handleUpload(e, 'excel')}
                className="hidden"
                accept=".xlsx,.xls"
              />

              <button
                onClick={() => csvInputRef.current?.click()}
                disabled={uploading}
                className="w-full p-6 rounded-2xl border-2 border-dashed border-border hover:border-primary hover:bg-primary/5 transition-all group"
              >
                <Upload size={32} className="mx-auto mb-3 text-muted-foreground group-hover:text-primary transition-colors" />
                <p className="font-medium">CSV файл</p>
                <p className="text-sm text-muted-foreground mt-1">Выберите .csv файл</p>
              </button>

              <div className="relative">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-border/50" />
                </div>
                <div className="relative flex justify-center">
                  <span className="bg-card px-4 text-sm text-muted-foreground">или</span>
                </div>
              </div>

              <button
                onClick={() => excelInputRef.current?.click()}
                disabled={uploading}
                className="w-full p-6 rounded-2xl border-2 border-dashed border-border hover:border-primary hover:bg-primary/5 transition-all group"
              >
                <Upload size={32} className="mx-auto mb-3 text-muted-foreground group-hover:text-primary transition-colors" />
                <p className="font-medium">Excel файл</p>
                <p className="text-sm text-muted-foreground mt-1">Выберите .xlsx файл</p>
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

function ContactRow({ contact, onDelete }: {
  contact: Contact
  onDelete: (id: number) => void
}) {
  const [showMenu, setShowMenu] = useState(false)
  const status = contact.is_processed ? 'contacted' : 'new'

  return (
    <motion.div
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="flex items-center gap-4 p-4 hover:bg-muted/50 transition-colors group"
    >
      {/* Avatar */}
      <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center text-primary font-semibold text-sm">
        {contact.first_name?.[0] || contact.username?.[0] || '?'}
      </div>

      {/* Info */}
      <div className="flex-1 min-w-0 grid grid-cols-4 gap-4">
        <div className="min-w-0">
          <p className="font-medium truncate">
            {contact.first_name && contact.last_name
              ? `${contact.first_name} ${contact.last_name}`
              : contact.first_name || contact.username || 'Не указано'
            }
          </p>
          {contact.username && (
            <p className="text-sm text-muted-foreground truncate flex items-center gap-1">
              <At size={12} />
              @{contact.username}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1 text-muted-foreground">
          <Phone size={14} />
          <span className="text-sm">{contact.phone_number || '—'}</span>
        </div>
        <div className="flex items-center">
          <StatusBadge status={status} />
        </div>
        <div className="text-sm text-muted-foreground">
          {contact.source}
        </div>
      </div>

      {/* Actions */}
      <div className="relative">
        <button
          onClick={() => setShowMenu(!showMenu)}
          className="p-2 rounded-xl hover:bg-muted transition-colors text-muted-foreground opacity-0 group-hover:opacity-100"
        >
          <DotsThree size={20} weight="bold" />
        </button>
        {showMenu && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setShowMenu(false)} />
            <div className="absolute right-0 top-full mt-2 w-40 bg-card rounded-xl border border-border shadow-xl z-20 py-2">
              <button
                onClick={() => { onDelete(contact.id); setShowMenu(false); }}
                className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-muted transition-colors text-sm text-red-600"
              >
                <Trash size={16} />
                Удалить
              </button>
            </div>
          </>
        )}
      </div>
    </motion.div>
  )
}

function EmptyState({ onUpload }: { onUpload: () => void }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center py-20 px-4"
    >
      <div className="w-20 h-20 rounded-3xl bg-primary/10 flex items-center justify-center mb-6">
        <User size={40} className="text-primary" weight="duotone" />
      </div>
      <h3 className="text-xl font-semibold mb-2">Нет контактов</h3>
      <p className="text-muted-foreground text-center mb-8 max-w-md">
        Загрузите базу контактов из CSV или Excel файла для начала рассылки.
      </p>
      <div className="flex gap-3">
        <button
          onClick={onUpload}
          className="inline-flex items-center gap-2 px-6 py-3 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
        >
          <Upload size={18} />
          Загрузить файл
        </button>
      </div>
    </motion.div>
  )
}

export default function Contacts() {
  const [contacts, setContacts] = useState<Contact[]>([])
  const [groups, setGroups] = useState<ContactGroup[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [groupName, setGroupName] = useState('')
  const [bulkValues, setBulkValues] = useState('')
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(true)
  const [isUploadOpen, setIsUploadOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  const fetchContacts = async () => {
    try {
      setLoading(true)
      const [contactsResponse, groupsResponse] = await Promise.all([
        api.get('/api/v1/contacts'),
        api.get('/api/v1/contacts/groups'),
      ])
      setContacts(contactsResponse.data)
      setGroups(groupsResponse.data)
      if (!selectedGroupId && groupsResponse.data.length > 0) {
        setSelectedGroupId(groupsResponse.data[0].id)
      }
    } catch (error) {
      console.error('Ошибка при загрузке контактов:', error)
      setContacts([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchContacts()
  }, [])

  const deleteContact = async (id: number) => {
    try {
      await api.delete(`/api/v1/contacts/${id}`)
      fetchContacts()
    } catch (error) {
      console.error('Ошибка при удалении:', error)
    }
  }

  const createGroup = async () => {
    const name = groupName.trim()
    if (!name) return
    try {
      const response = await api.post('/api/v1/contacts/groups', { name })
      setGroups(prev => [response.data, ...prev])
      setSelectedGroupId(response.data.id)
      setGroupName('')
      setMessage('Пул контактов создан.')
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'Не удалось создать пул контактов.')
    }
  }

  const deleteGroup = async () => {
    if (!selectedGroupId || !confirm('Удалить выбранный пул? Контакты останутся без пула.')) return
    await api.delete(`/api/v1/contacts/groups/${selectedGroupId}`)
    setSelectedGroupId(null)
    await fetchContacts()
  }

  const addBulkContacts = async () => {
    const values = bulkValues.split(/\r?\n|,|;/).map(value => value.trim()).filter(Boolean)
    if (!values.length || !selectedGroupId) return
    try {
      const response = await api.post('/api/v1/contacts/bulk', {
        group_id: selectedGroupId,
        values,
      })
      setMessage(`Добавлено: ${response.data.created}. Дубликаты: ${response.data.skipped}. Некорректные: ${response.data.invalid.length}.`)
      setBulkValues('')
      await fetchContacts()
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'Не удалось добавить контакты.')
    }
  }

  const filteredContacts = contacts.filter(contact => {
    if (selectedGroupId && contact.group_id !== selectedGroupId) return false
    const matchesSearch =
      contact.username?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      contact.first_name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      contact.phone_number?.includes(searchQuery)
    const matchesStatus = statusFilter === 'all' ||
      (statusFilter === 'new' && !contact.is_processed) ||
      (statusFilter === 'processed' && contact.is_processed)
    return matchesSearch && matchesStatus
  })

  const statusCounts = {
    all: contacts.length,
    new: contacts.filter(c => !c.is_processed).length,
    processed: contacts.filter(c => c.is_processed).length,
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
          <h1 className="text-3xl font-bold tracking-tight">Контакты</h1>
          <p className="text-muted-foreground mt-1">База контактов для рассылки</p>
        </div>
        <button
          onClick={() => setIsUploadOpen(true)}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors"
        >
          <Upload size={18} weight="bold" />
          Загрузить
        </button>
      </motion.div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="bg-card rounded-2xl border border-border/50 p-5 space-y-4">
          <h2 className="font-semibold">Пулы контактов</h2>
          <div className="flex gap-2">
            <input
              value={groupName}
              onChange={event => setGroupName(event.target.value)}
              placeholder="Например: мои аккаунты"
              className="min-w-0 flex-1 px-3 py-2 rounded-xl border border-border bg-background outline-none focus:border-primary"
            />
            <button onClick={createGroup} className="px-3 py-2 rounded-xl bg-primary text-primary-foreground">
              <Plus size={18} />
            </button>
          </div>
          <button
            onClick={() => setSelectedGroupId(null)}
            className={`w-full text-left px-3 py-3 rounded-2xl ${selectedGroupId === null ? 'bg-primary/10 text-primary' : 'bg-muted/50 hover:bg-muted'}`}
          >
            Все контакты · {contacts.length}
          </button>
          {groups.map(group => (
            <button
              key={group.id}
              onClick={() => setSelectedGroupId(group.id)}
              className={`w-full text-left px-3 py-3 rounded-2xl ${selectedGroupId === group.id ? 'bg-primary/10 text-primary' : 'bg-muted/50 hover:bg-muted'}`}
            >
              <span className="block font-medium truncate">{group.name}</span>
              <span className="text-xs text-muted-foreground">
                {contacts.filter(contact => contact.group_id === group.id).length} контактов
              </span>
            </button>
          ))}
        </div>

        <div className="bg-card rounded-2xl border border-border/50 p-5 space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">Добавить в пул</h2>
              <p className="text-sm text-muted-foreground">Вставь username или телефоны столбиком.</p>
            </div>
            {selectedGroupId && (
              <button onClick={deleteGroup} className="px-3 py-2 rounded-xl border border-red-500/30 text-red-600 hover:bg-red-500/10">
                Удалить пул
              </button>
            )}
          </div>
          <textarea
            value={bulkValues}
            onChange={event => setBulkValues(event.target.value)}
            rows={5}
            disabled={!selectedGroupId}
            placeholder={'@username\n+79991234567\nusername2'}
            className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary resize-y font-mono text-sm disabled:opacity-50"
          />
          <button
            onClick={addBulkContacts}
            disabled={!selectedGroupId || !bulkValues.trim()}
            className="px-4 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium disabled:opacity-50"
          >
            Добавить контакты
          </button>
          {message && <p className="text-sm text-muted-foreground">{message}</p>}
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {[
          { key: 'all', label: 'Всего' },
          { key: 'new', label: 'Новые' },
          { key: 'processed', label: 'Обработаны' },
        ].map((item) => (
          <button
            key={item.key}
            onClick={() => setStatusFilter(item.key)}
            className={`
              p-4 rounded-2xl border transition-all text-left
              ${statusFilter === item.key
                ? 'bg-primary/10 border-primary/30 text-primary'
                : 'bg-card border-border hover:border-border/80'
              }
            `}
          >
            <p className="text-2xl font-bold">{statusCounts[item.key as keyof typeof statusCounts]}</p>
            <p className="text-sm text-muted-foreground">{item.label}</p>
          </button>
        ))}
      </div>

      {/* Search */}
      <div className="relative">
        <MagnifyingGlass size={20} className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Поиск по имени, username или телефону..."
          className="w-full pl-12 pr-4 py-3.5 rounded-2xl border border-border bg-card focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
        />
      </div>

      {/* Contacts List */}
      {loading ? (
        <div className="space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-20 bg-muted rounded-2xl animate-pulse" />
          ))}
        </div>
      ) : filteredContacts.length === 0 ? (
        <EmptyState onUpload={() => setIsUploadOpen(true)} />
      ) : (
        <motion.div
          layout
          className="bg-card rounded-2xl border border-border/50 overflow-hidden"
        >
          {/* Table Header */}
          <div className="grid grid-cols-[40px_1fr_120px_140px_100px] gap-4 px-4 py-3 border-b border-border/50 text-sm font-medium text-muted-foreground">
            <div></div>
            <div>Контакт</div>
            <div>Телефон</div>
            <div>Статус</div>
            <div>Источник</div>
          </div>

          {/* Table Body */}
          <div className="divide-y divide-border/30">
            <AnimatePresence mode="popLayout">
              {filteredContacts.map((contact) => (
                <div key={contact.id} className="grid grid-cols-[40px_1fr_120px_140px_100px] gap-4 px-4 py-4 hover:bg-muted/30 transition-colors group">
                  {/* Avatar */}
                  <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center text-primary font-semibold text-sm self-center">
                    {contact.first_name?.[0] || contact.username?.[0] || '?'}
                  </div>

                  {/* Name & Username */}
                  <div className="min-w-0 self-center">
                    <p className="font-medium truncate">
                      {contact.first_name && contact.last_name
                        ? `${contact.first_name} ${contact.last_name}`
                        : contact.first_name || contact.username || 'Не указано'
                      }
                    </p>
                    {contact.username && (
                      <p className="text-sm text-muted-foreground truncate flex items-center gap-1">
                        <At size={12} />
                        @{contact.username}
                      </p>
                    )}
                  </div>

                  {/* Phone */}
                  <div className="flex items-center gap-1 text-sm text-muted-foreground self-center">
                    <Phone size={14} />
                    <span>{contact.phone_number || '—'}</span>
                  </div>

                  {/* Status */}
                  <div className="self-center">
                    <StatusBadge status={contact.is_processed ? 'contacted' : 'new'} />
                  </div>

                  {/* Source & Actions */}
                  <div className="flex items-center justify-between self-center">
                    <span className="text-sm text-muted-foreground">{contact.source}</span>
                    <button
                      onClick={() => deleteContact(contact.id)}
                      className="p-2 rounded-xl hover:bg-red-500/10 transition-colors text-muted-foreground hover:text-red-600 opacity-0 group-hover:opacity-100"
                    >
                      <Trash size={18} />
                    </button>
                  </div>
                </div>
              ))}
            </AnimatePresence>
          </div>
        </motion.div>
      )}

      <UploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onSuccess={fetchContacts}
      />
    </div>
  )
}
