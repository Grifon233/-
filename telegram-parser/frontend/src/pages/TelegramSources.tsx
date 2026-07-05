import { useEffect, useMemo, useState } from 'react'
import { FolderSimple, Link, Plus, SpinnerGap, Trash } from '@phosphor-icons/react'
import api from '../services/api'

type SourceType = 'unknown' | 'chat' | 'group' | 'channel' | 'closed'

interface TelegramSourceGroup {
  id: number
  name: string
  description: string | null
}

interface TelegramSource {
  id: number
  group_id: number | null
  normalized_link: string
  source_type: SourceType
  created_at: string
}

const sourceLabels: Record<SourceType, string> = {
  unknown: 'Авто/не определено',
  chat: 'Личный чат',
  group: 'Группа/чат',
  channel: 'Канал',
  closed: 'Закрыто/инвайт',
}

export default function TelegramSources() {
  const [groups, setGroups] = useState<TelegramSourceGroup[]>([])
  const [sources, setSources] = useState<TelegramSource[]>([])
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null)
  const [groupName, setGroupName] = useState('')
  const [links, setLinks] = useState('')
  const [sourceType, setSourceType] = useState<SourceType>('unknown')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [diagnosing, setDiagnosing] = useState(false)
  const [message, setMessage] = useState('')

  const selectedGroup = groups.find(group => group.id === selectedGroupId) || null
  const visibleSources = useMemo(
    () => sources.filter(source => source.group_id === selectedGroupId),
    [sources, selectedGroupId]
  )

  const fetchData = async () => {
    try {
      setLoading(true)
      const [groupsResponse, sourcesResponse] = await Promise.all([
        api.get('/api/v1/telegram-sources/groups'),
        api.get('/api/v1/telegram-sources'),
      ])
      setGroups(groupsResponse.data)
      setSources(sourcesResponse.data)
      if (!selectedGroupId && groupsResponse.data.length > 0) {
        setSelectedGroupId(groupsResponse.data[0].id)
      }
    } catch (error) {
      console.error('Ошибка загрузки источников:', error)
      setMessage('Не удалось загрузить источники. Проверьте backend.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData()
  }, [])

  const createGroup = async () => {
    const name = groupName.trim()
    if (!name) return
    try {
      const response = await api.post('/api/v1/telegram-sources/groups', { name })
      setGroups(prev => [response.data, ...prev])
      setSelectedGroupId(response.data.id)
      setGroupName('')
      setMessage('Пул источников создан.')
    } catch (error) {
      console.error('Ошибка создания пула:', error)
      setMessage('Не удалось создать пул. Возможно, такое название уже есть.')
    }
  }

  const renameSelectedGroup = async () => {
    if (!selectedGroup) return
    const name = window.prompt('Новое название пула', selectedGroup.name)
    if (!name?.trim()) return
    const response = await api.patch(`/api/v1/telegram-sources/groups/${selectedGroup.id}`, { name: name.trim() })
    setGroups(prev => prev.map(group => group.id === selectedGroup.id ? response.data : group))
  }

  const deleteSelectedGroup = async () => {
    if (!selectedGroup || !confirm(`Удалить пул "${selectedGroup.name}" вместе со всеми его ссылками?`)) return
    await api.delete(`/api/v1/telegram-sources/groups/${selectedGroup.id}`)
    const nextGroups = groups.filter(group => group.id !== selectedGroup.id)
    setGroups(nextGroups)
    setSelectedGroupId(nextGroups[0]?.id || null)
    await fetchData()
  }

  const deleteOrphanedSources = async () => {
    if (!confirm('Удалить все ссылки без пула (накопившиеся от прошлых удалений)?')) return
    const response = await api.delete('/api/v1/telegram-sources/orphaned')
    setMessage(`Удалено осиротевших ссылок: ${response.data.deleted}.`)
    await fetchData()
  }

  const handleImport = async (event: React.FormEvent) => {
    event.preventDefault()
    const values = links.split(/\r?\n|,|;/).map(value => value.trim()).filter(Boolean)
    if (!values.length || !selectedGroupId) return
    try {
      setSubmitting(true)
      const response = await api.post('/api/v1/telegram-sources/bulk', {
        links: values,
        source_type: sourceType,
        group_id: selectedGroupId,
      })
      const { created, skipped, invalid } = response.data
      setMessage(`Добавлено: ${created}. Дубликаты: ${skipped}. Некорректные: ${invalid.length}.`)
      setLinks('')
      await fetchData()
    } catch (error) {
      console.error('Ошибка импорта источников:', error)
      setMessage('Не удалось добавить список. Проверьте ссылки и backend.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleDeleteSource = async (id: number) => {
    await api.delete(`/api/v1/telegram-sources/${id}`)
    await fetchData()
  }

  const deduplicateSelectedGroup = async () => {
    if (!selectedGroupId) return
    try {
      const response = await api.post(`/api/v1/telegram-sources/deduplicate?group_id=${selectedGroupId}`)
      setMessage(`Дубликаты удалены: ${response.data.removed}.`)
      await fetchData()
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'Не удалось удалить дубликаты.')
    }
  }

  const diagnoseSelectedGroup = async (deleteInvalid = false) => {
    if (!selectedGroupId) return
    if (deleteInvalid && !confirm('Удалить ссылки, которые Telegram не смог открыть? Закрытые invite-ссылки не удаляются, они будут помечены как закрытые.')) return
    try {
      setDiagnosing(true)
      const response = await api.post('/api/v1/telegram-sources/diagnose', {
        group_id: selectedGroupId,
        delete_invalid: deleteInvalid,
        limit: 5000,
      })
      const { checked, updated, deleted, failed, counts } = response.data
      setMessage(
        `Проверено: ${checked}. Обновлено: ${updated}. Удалено: ${deleted}. Ошибок: ${failed}. ` +
        `Каналы: ${counts.channel || 0}, группы: ${counts.group || 0}, закрытые: ${counts.closed || 0}, неизвестно: ${counts.unknown || 0}.`
      )
      await fetchData()
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'Не удалось проверить источники.')
    } finally {
      setDiagnosing(false)
    }
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Источники Telegram</h1>
          <p className="text-muted-foreground mt-1">
            Пулы ссылок для задач: отдельно каналы, группы/чаты или временно не определённые ссылки.
          </p>
        </div>
        {sources.some(s => s.group_id === null) && (
          <button
            onClick={deleteOrphanedSources}
            className="px-4 py-2 rounded-xl border border-orange-500/30 text-orange-700 hover:bg-orange-500/10 text-sm font-medium"
          >
            🧹 Удалить ссылки без пула ({sources.filter(s => s.group_id === null).length})
          </button>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="bg-card border border-border rounded-3xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <FolderSimple size={20} className="text-primary" />
            <h2 className="font-semibold">Пулы источников</h2>
          </div>
          <div className="flex gap-2">
            <input
              value={groupName}
              onChange={event => setGroupName(event.target.value)}
              placeholder="Например: Бьюти-мастера"
              className="min-w-0 flex-1 px-3 py-2 rounded-xl border border-border bg-background outline-none focus:border-primary"
            />
            <button onClick={createGroup} className="px-3 py-2 rounded-xl bg-primary text-primary-foreground">
              <Plus size={18} />
            </button>
          </div>

          {loading ? (
            <div className="flex justify-center py-8"><SpinnerGap size={24} className="animate-spin text-primary" /></div>
          ) : groups.length === 0 ? (
            <p className="text-sm text-muted-foreground">Создай первый пул и добавь ссылки столбиком.</p>
          ) : (
            <div className="space-y-2">
              {groups.map(group => {
                const count = sources.filter(source => source.group_id === group.id).length
                return (
                  <button
                    key={group.id}
                    onClick={() => setSelectedGroupId(group.id)}
                    className={`w-full text-left px-3 py-3 rounded-2xl transition-colors ${
                      selectedGroupId === group.id ? 'bg-primary/10 text-primary' : 'bg-muted/50 hover:bg-muted'
                    }`}
                  >
                    <span className="block font-medium truncate">{group.name}</span>
                    <span className="text-xs text-muted-foreground">{count} ссылок</span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="space-y-6">
          <form onSubmit={handleImport} className="bg-card border border-border rounded-3xl p-6 space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold">{selectedGroup?.name || 'Выбери пул источников'}</h2>
                <p className="text-sm text-muted-foreground">
                  По обычной t.me-ссылке тип не всегда понятен, поэтому лучше указывать тип списка при импорте.
                </p>
              </div>
              {selectedGroup && (
                <div className="flex gap-2">
                  <button type="button" onClick={renameSelectedGroup} className="px-3 py-2 rounded-xl border border-border hover:bg-muted">
                    Переименовать
                  </button>
                  <button type="button" onClick={deduplicateSelectedGroup} className="px-3 py-2 rounded-xl border border-border hover:bg-muted">
                    Удалить дубликаты
                  </button>
                  <button type="button" onClick={() => diagnoseSelectedGroup(false)} disabled={diagnosing} className="px-3 py-2 rounded-xl border border-border hover:bg-muted disabled:opacity-50">
                    {diagnosing ? 'Проверка...' : 'Проверить типы'}
                  </button>
                  <button type="button" onClick={() => diagnoseSelectedGroup(true)} disabled={diagnosing} className="px-3 py-2 rounded-xl border border-amber-500/30 text-amber-700 hover:bg-amber-500/10 disabled:opacity-50">
                    Проверить и удалить мёртвые
                  </button>
                  <button type="button" onClick={deleteSelectedGroup} className="px-3 py-2 rounded-xl border border-red-500/30 text-red-600 hover:bg-red-500/10">
                    Удалить пул
                  </button>
                </div>
              )}
            </div>

            <div className="grid gap-4 md:grid-cols-[1fr_240px]">
              <textarea
                value={links}
                onChange={event => setLinks(event.target.value)}
                rows={7}
                disabled={!selectedGroupId}
                placeholder={'https://t.me/channel_one\n@group_two\nhttps://t.me/+inviteCode'}
                className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary resize-y font-mono text-sm disabled:opacity-50"
              />
              <div className="space-y-3">
                <label className="block text-sm font-medium">Тип добавляемых ссылок</label>
                <select
                  value={sourceType}
                  onChange={event => setSourceType(event.target.value as SourceType)}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background outline-none focus:border-primary"
                >
                  <option value="channel">Каналы</option>
                  <option value="group">Группы/чаты</option>
                  <option value="unknown">Авто/не определено</option>
                </select>
                <button
                  type="submit"
                  disabled={submitting || !links.trim() || !selectedGroupId}
                  className="w-full px-4 py-3 rounded-xl bg-primary text-primary-foreground font-medium disabled:opacity-50"
                >
                  {submitting ? 'Импорт...' : 'Добавить ссылки'}
                </button>
              </div>
            </div>
            {message && <p className="text-sm text-muted-foreground">{message}</p>}
          </form>

          <div className="bg-card border border-border rounded-3xl overflow-hidden">
            {visibleSources.length === 0 ? (
              <div className="text-center py-16 text-muted-foreground">В выбранном пуле пока нет ссылок.</div>
            ) : (
              <div className="divide-y divide-border">
                {visibleSources.map(source => (
                  <div key={source.id} className="flex items-center gap-4 p-4">
                    <Link size={20} className="text-primary shrink-0" />
                    <a href={source.normalized_link} target="_blank" rel="noreferrer" className="flex-1 truncate hover:text-primary">
                      {source.normalized_link}
                    </a>
                    <span className="px-3 py-1 rounded-full bg-muted text-xs">{sourceLabels[source.source_type]}</span>
                    <button onClick={() => handleDeleteSource(source.id)} className="p-2 rounded-lg hover:bg-red-500/10 text-muted-foreground hover:text-red-600">
                      <Trash size={18} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
