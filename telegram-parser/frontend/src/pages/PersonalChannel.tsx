import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  Plus,
  Television,
  Trash,
  CheckCircle,
  CircleNotch,
  Image as ImageIcon,
} from '@phosphor-icons/react'
import api from '../services/api'

interface TemplatePost {
  id?: number
  position: number
  text: string
  image_filename?: string | null
  image_mime_type?: string | null
  image_base64?: string | null
  imageFile?: File | null
  previewUrl?: string
}

interface ChannelTemplate {
  id: number
  name: string
  channel_title: string
  channel_about?: string | null
  channel_avatar_mode?: 'none' | 'template' | 'profile'
  channel_avatar_filename?: string | null
  channel_avatar_mime_type?: string | null
  channel_avatar_base64?: string | null
  channelAvatarFile?: File | null
  channelAvatarPreviewUrl?: string
  posts: TemplatePost[]
}

function imageSrc(post: TemplatePost) {
  if (post.previewUrl) return post.previewUrl
  if (post.image_base64) {
    return `data:${post.image_mime_type || 'image/jpeg'};base64,${post.image_base64}`
  }
  return ''
}

function avatarSrc(template: ChannelTemplate) {
  if (template.channelAvatarPreviewUrl) return template.channelAvatarPreviewUrl
  if (template.channel_avatar_base64) {
    return `data:${template.channel_avatar_mime_type || 'image/jpeg'};base64,${template.channel_avatar_base64}`
  }
  return ''
}

export default function PersonalChannel() {
  const [templates, setTemplates] = useState<ChannelTemplate[]>([])
  const [activeId, setActiveId] = useState<number | null>(null)
  const [active, setActive] = useState<ChannelTemplate | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [ok, setOk] = useState('')

  const loadTemplates = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/v1/personal-channel-templates')
      setTemplates(res.data)
      if (!activeId && res.data.length > 0) setActiveId(res.data[0].id)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Не удалось загрузить шаблоны')
    } finally {
      setLoading(false)
    }
  }

  const loadTemplate = async (id: number) => {
    setError('')
    const res = await api.get(`/api/v1/personal-channel-templates/${id}`)
    setActive({
      ...res.data,
      posts: res.data.posts.length > 0
        ? res.data.posts
        : [{ position: 1, text: '', imageFile: null }],
    })
  }

  useEffect(() => {
    loadTemplates()
  }, [])

  useEffect(() => {
    if (activeId) loadTemplate(activeId).catch(e => setError(e.response?.data?.detail || 'Не удалось открыть шаблон'))
  }, [activeId])

  const createTemplate = async () => {
    const name = window.prompt('Название шаблона')
    if (!name?.trim()) return
    setError('')
    const res = await api.post('/api/v1/personal-channel-templates', {
      name: name.trim(),
      channel_title: name.trim(),
    })
    await loadTemplates()
    setActiveId(res.data.id)
  }

  const updateActive = (patch: Partial<ChannelTemplate>) => {
    if (!active) return
    setActive({ ...active, ...patch })
  }

  const saveAvatarSettings = async (
    templateId: number,
    mode: 'none' | 'template' | 'profile',
    file?: File | null,
  ) => {
    setSaving(true)
    setError('')
    setOk('')
    try {
      const fd = new FormData()
      fd.append('mode', mode)
      if (mode === 'template' && file) fd.append('image', file)
      if (mode === 'none') fd.append('clear_avatar', 'true')
      const res = await api.post(`/api/v1/personal-channel-templates/${templateId}/avatar`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setActive({
        ...res.data,
        posts: res.data.posts.length > 0 ? res.data.posts : [{ position: 1, text: '', imageFile: null }],
      })
      await loadTemplates()

      if (mode !== 'none') {
        // Immediately apply avatar to all bound accounts and show results
        try {
          const applyRes = await api.post(`/api/v1/personal-channel-templates/${templateId}/apply-avatar`)
          const d = applyRes.data
          if (d.bound_accounts === 0) {
            setOk('Настройка аватарки сохранена. Нет привязанных аккаунтов — используйте «Добавить канал» в панели аккаунтов.')
          } else if (d.ok === d.bound_accounts) {
            setOk(`Аватарка канала обновлена у ${d.ok} из ${d.bound_accounts} аккаунтов.`)
          } else {
            const errors = (d.results as any[]).filter(r => r.status !== 'ok').map((r: any) => `${r.phone}: ${r.reason || r.status}`).join('; ')
            setError(`Аватарка применена у ${d.ok} из ${d.bound_accounts}. Ошибки: ${errors}`)
          }
        } catch {
          setOk('Настройка аватарки сохранена. Применить к каналам — нажмите «Сохранить весь шаблон».')
        }
      } else {
        setOk('Настройка аватарки канала сохранена.')
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Не удалось сохранить настройку аватарки канала')
    } finally {
      setSaving(false)
    }
  }

  const updatePost = (index: number, patch: Partial<TemplatePost>) => {
    if (!active) return
    const posts = active.posts.map((post, i) => i === index ? { ...post, ...patch } : post)
    setActive({ ...active, posts })
  }

  const addPost = () => {
    if (!active) return
    setActive({
      ...active,
      posts: [...active.posts, { position: active.posts.length + 1, text: '', imageFile: null }],
    })
  }

  // After any template edit, push the (now-final) content to every
  // account this template is bound to. The backend runs it in the
  // background and de-dupes (wipe-and-repost), so this is a fast,
  // fire-and-forget call.
  const syncToAccounts = async (templateId: number) => {
    try {
      const res = await api.post(`/api/v1/personal-channel-templates/${templateId}/sync`)
      const n = res.data?.bound_accounts ?? 0
      if (n > 0) setOk(`Изменения отправляются в привязанные аккаунты (${n})`)
    } catch (e) {
      // Non-fatal: the template is saved; sync can be retried via re-save.
      console.error('Не удалось синхронизировать шаблон с аккаунтами', e)
    }
  }

  const saveTemplateMeta = async () => {
    if (!active) return
    setSaving(true)
    setError('')
    setOk('')
    try {
      const res = await api.put(`/api/v1/personal-channel-templates/${active.id}`, {
        name: active.name,
        channel_title: active.channel_title,
        channel_about: active.channel_about || null,
        channel_avatar_mode: active.channel_avatar_mode || 'none',
      })
      setActive({ ...active, ...res.data })
      await loadTemplates()
      setOk('Название и описание сохранены. Посты сохраняются кнопкой “Сохранить пост” или “Сохранить весь шаблон”.')
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Не удалось сохранить шаблон')
    } finally {
      setSaving(false)
    }
  }

  const savePost = async (post: TemplatePost, index: number) => {
    if (!active) return
    setSaving(true)
    setError('')
    setOk('')
    try {
      const fd = new FormData()
      if (post.id) fd.append('post_id', String(post.id))
      fd.append('position', String(index + 1))
      fd.append('text', post.text || '')
      if (post.imageFile) fd.append('image', post.imageFile)
      const res = await api.post(`/api/v1/personal-channel-templates/${active.id}/posts`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setActive({
        ...res.data,
        posts: res.data.posts.length > 0 ? res.data.posts : [{ position: 1, text: '', imageFile: null }],
      })
      setOk(`Пост ${index + 1} сохранён`)
      await loadTemplates()
    } catch (e: any) {
      setError(e.response?.data?.detail || `Не удалось сохранить пост ${index + 1}`)
    } finally {
      setSaving(false)
    }
  }

  const saveAll = async () => {
    if (!active) return
    setSaving(true)
    setError('')
    setOk('')
    try {
      await api.put(`/api/v1/personal-channel-templates/${active.id}`, {
        name: active.name,
        channel_title: active.channel_title,
        channel_about: active.channel_about || null,
        channel_avatar_mode: active.channel_avatar_mode || 'none',
      })
      if ((active.channel_avatar_mode || 'none') !== 'none' && (active.channelAvatarFile || active.channel_avatar_mode === 'profile')) {
        const fd = new FormData()
        fd.append('mode', active.channel_avatar_mode || 'none')
        if (active.channelAvatarFile && active.channel_avatar_mode === 'template') {
          fd.append('image', active.channelAvatarFile)
        }
        await api.post(`/api/v1/personal-channel-templates/${active.id}/avatar`, fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }
      for (let index = 0; index < active.posts.length; index += 1) {
        const post = active.posts[index]
        if (!post.text.trim() && !post.imageFile && !post.image_base64) continue
        const fd = new FormData()
        if (post.id) fd.append('post_id', String(post.id))
        fd.append('position', String(index + 1))
        fd.append('text', post.text || '')
        if (post.imageFile) fd.append('image', post.imageFile)
        await api.post(`/api/v1/personal-channel-templates/${active.id}/posts`, fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      }
      await loadTemplate(active.id)
      await loadTemplates()
      setOk('Шаблон и посты сохранены')
      await syncToAccounts(active.id)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Не удалось сохранить шаблон целиком')
    } finally {
      setSaving(false)
    }
  }

  const deletePost = async (post: TemplatePost, index: number) => {
    if (!active) return
    if (!post.id) {
      setActive({ ...active, posts: active.posts.filter((_, i) => i !== index) })
      return
    }
    await api.delete(`/api/v1/personal-channel-templates/${active.id}/posts/${post.id}`)
    await loadTemplate(active.id)
    await loadTemplates()
  }

  // Swap a post with its neighbour to change the display order. If every
  // post is already saved, persist the new order on the server (which also
  // pushes it to bound accounts); otherwise just reorder locally.
  const movePost = async (index: number, direction: -1 | 1) => {
    if (!active) return
    const target = index + direction
    if (target < 0 || target >= active.posts.length) return
    const newPosts = [...active.posts]
    const tmp = newPosts[index]
    newPosts[index] = newPosts[target]
    newPosts[target] = tmp
    setActive({ ...active, posts: newPosts })
    if (newPosts.every(p => p.id)) {
      try {
        await api.post(`/api/v1/personal-channel-templates/${active.id}/posts/reorder`, {
          post_ids: newPosts.map(p => p.id),
        })
        await loadTemplate(active.id)
        await loadTemplates()
        setOk('Порядок постов изменён')
      } catch (e: any) {
        setError(e.response?.data?.detail || 'Не удалось изменить порядок постов')
      }
    } else {
      setOk('Порядок изменён. Нажмите «Сохранить весь шаблон», чтобы зафиксировать.')
    }
  }

  const deleteTemplate = async (template: ChannelTemplate) => {
    if (!confirm(`Удалить шаблон "${template.name}"?`)) return
    await api.delete(`/api/v1/personal-channel-templates/${template.id}`)
    setActive(null)
    setActiveId(null)
    await loadTemplates()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Личный канал</h1>
          <p className="text-muted-foreground mt-1">
            Шаблоны стартовых постов для личных каналов аккаунтов текущего проекта.
          </p>
        </div>
        <button
          onClick={createTemplate}
          className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90"
        >
          <Plus size={18} weight="bold" />
          Создать шаблон
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[320px_1fr] gap-6">
        <div className="rounded-3xl border border-border bg-card p-4 space-y-3">
          <h2 className="font-semibold flex items-center gap-2">
            <Television size={18} weight="duotone" />
            Шаблоны
          </h2>
          {loading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
          {templates.length === 0 && !loading && (
            <p className="text-sm text-muted-foreground">Пока нет шаблонов. Нажмите “Создать шаблон”.</p>
          )}
          {templates.map(template => (
            <button
              key={template.id}
              onClick={() => setActiveId(template.id)}
              className={`w-full text-left rounded-2xl border p-3 transition-colors ${
                activeId === template.id ? 'border-primary/40 bg-primary/10' : 'border-border hover:bg-muted'
              }`}
            >
              <p className="font-medium">{template.name}</p>
              <p className="text-xs text-muted-foreground">{template.posts.length} пост(ов)</p>
            </button>
          ))}
        </div>

        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="rounded-3xl border border-border bg-card p-5 min-h-[480px]"
        >
          {!active ? (
            <div className="h-full flex items-center justify-center text-muted-foreground">
              Выберите шаблон или создайте новый.
            </div>
          ) : (
            <div className="space-y-5">
              <div className="flex items-start justify-between gap-3">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 flex-1">
                  <div>
                    <label className="text-xs text-muted-foreground">Название шаблона</label>
                    <input
                      value={active.name}
                      onChange={e => updateActive({ name: e.target.value })}
                      className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Название канала</label>
                    <input
                      value={active.channel_title}
                      onChange={e => updateActive({ channel_title: e.target.value })}
                      className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background"
                    />
                  </div>
                  <div className="md:col-span-2">
                    <label className="text-xs text-muted-foreground">Описание канала</label>
                    <input
                      value={active.channel_about || ''}
                      onChange={e => updateActive({ channel_about: e.target.value })}
                      className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background"
                    />
                  </div>
                  <div className="md:col-span-2 rounded-2xl border border-border/60 bg-background/40 p-4 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <label className="text-sm font-medium">Аватарка личного канала</label>
                        <p className="text-xs text-muted-foreground mt-1">
                          Можно загрузить одну аватарку для всех аккаунтов шаблона или брать аватар самого Telegram-профиля.
                        </p>
                      </div>
                      {active.channel_avatar_mode === 'template' && avatarSrc(active) && (
                        <img
                          src={avatarSrc(active)}
                          alt="Аватарка личного канала"
                          className="h-16 w-16 rounded-full object-cover border border-border"
                        />
                      )}
                    </div>

                    <div className="flex flex-wrap gap-2">
                      <label className={`px-3 py-2 rounded-xl border cursor-pointer text-sm ${
                        (active.channel_avatar_mode || 'none') === 'profile' ? 'border-primary bg-primary/10 text-primary' : 'border-border'
                      }`}>
                        <input
                          type="radio"
                          name="channel_avatar_mode"
                          checked={(active.channel_avatar_mode || 'none') === 'profile'}
                          onChange={async () => {
                            updateActive({ channel_avatar_mode: 'profile', channelAvatarFile: null, channelAvatarPreviewUrl: undefined })
                            await saveAvatarSettings(active.id, 'profile', null)
                          }}
                          className="mr-2"
                        />
                        Как у профиля
                      </label>
                      <label className={`px-3 py-2 rounded-xl border cursor-pointer text-sm ${
                        active.channel_avatar_mode === 'template' ? 'border-primary bg-primary/10 text-primary' : 'border-border'
                      }`}>
                        <input
                          type="radio"
                          name="channel_avatar_mode"
                          checked={active.channel_avatar_mode === 'template'}
                          onChange={() => updateActive({ channel_avatar_mode: 'template' })}
                          className="mr-2"
                        />
                        Своя аватарка шаблона
                      </label>
                      <label className={`px-3 py-2 rounded-xl border cursor-pointer text-sm ${
                        (active.channel_avatar_mode || 'none') === 'none' ? 'border-primary bg-primary/10 text-primary' : 'border-border'
                      }`}>
                        <input
                          type="radio"
                          name="channel_avatar_mode"
                          checked={(active.channel_avatar_mode || 'none') === 'none'}
                          onChange={async () => {
                            updateActive({ channel_avatar_mode: 'none', channelAvatarFile: null, channelAvatarPreviewUrl: undefined })
                            await saveAvatarSettings(active.id, 'none', null)
                          }}
                          className="mr-2"
                        />
                        Не менять
                      </label>
                    </div>

                    {active.channel_avatar_mode === 'template' && (
                      <label className="flex items-center gap-2 text-sm">
                        <ImageIcon size={16} />
                        Файл аватарки
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          onChange={async e => {
                            const file = e.target.files?.[0] || null
                            const previewUrl = file ? URL.createObjectURL(file) : undefined
                            updateActive({ channelAvatarFile: file, channelAvatarPreviewUrl: previewUrl })
                            if (file) {
                              await saveAvatarSettings(active.id, 'template', file)
                            }
                          }}
                          className="flex-1 px-3 py-2 rounded-xl border border-border bg-background file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-medium"
                        />
                      </label>
                    )}
                  </div>
                </div>
                <button onClick={() => deleteTemplate(active)} className="p-2 rounded-xl hover:bg-red-500/10 text-red-600">
                  <Trash size={18} />
                </button>
              </div>

              <div className="flex gap-2">
                <button
                  onClick={saveTemplateMeta}
                  disabled={saving || !active.name.trim() || !active.channel_title.trim()}
                  className="px-4 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50"
                >
                  {saving ? 'Сохранение…' : 'Сохранить название'}
                </button>
                <button
                  onClick={saveAll}
                  disabled={saving || !active.name.trim() || !active.channel_title.trim()}
                  className="px-4 py-2 rounded-xl border border-primary/30 text-primary hover:bg-primary/10 disabled:opacity-50"
                >
                  Сохранить весь шаблон
                </button>
                <button onClick={addPost} className="px-4 py-2 rounded-xl border border-border hover:bg-muted">
                  + Пост
                </button>
              </div>

              {error && <p className="text-sm text-red-500 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}
              {ok && <p className="text-sm text-emerald-600 flex items-center gap-1"><CheckCircle size={14} weight="bold" /> {ok}</p>}

              <p className="text-xs text-muted-foreground bg-muted/50 px-3 py-2 rounded-xl">
                Пост №1 — самый свежий: он публикуется последним и виден первым при входе в канал. Чем выше номер поста — тем он старее.
              </p>

              <div className="space-y-4">
                {active.posts.map((post, index) => (
                  <div key={post.id || `new-${index}`} className="rounded-3xl border border-border/60 p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="font-semibold">Пост {index + 1}</h3>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => movePost(index, -1)}
                          disabled={index === 0}
                          title="Выше: этот пост увидят раньше (ближе ко входу в канал)"
                          className="p-2 rounded-xl hover:bg-primary/10 disabled:opacity-30"
                        >↑</button>
                        <button
                          onClick={() => movePost(index, 1)}
                          disabled={index === active.posts.length - 1}
                          title="Ниже: этот пост увидят позже (нужно проскроллить вниз)"
                          className="p-2 rounded-xl hover:bg-primary/10 disabled:opacity-30"
                        >↓</button>
                        <button onClick={() => deletePost(post, index)} className="p-2 rounded-xl hover:bg-red-500/10 text-red-600">
                          <Trash size={16} />
                        </button>
                      </div>
                    </div>
                    <textarea
                      value={post.text}
                      onChange={e => updatePost(index, { text: e.target.value })}
                      rows={4}
                      placeholder="Текст поста. Ссылки можно вставлять обычным URL — Telegram сам сделает их кликабельными."
                      className="w-full px-3 py-2 rounded-xl border border-border bg-background resize-none"
                    />
                    {imageSrc(post) && (
                      <img src={imageSrc(post)} alt={`Пост ${index + 1}`} className="max-h-64 rounded-2xl border border-border object-cover" />
                    )}
                    <label className="flex items-center gap-2 text-sm">
                      <ImageIcon size={16} />
                      Картинка
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        onChange={e => {
                          const file = e.target.files?.[0] || null
                          const previewUrl = file ? URL.createObjectURL(file) : undefined
                          updatePost(index, { imageFile: file, previewUrl })
                        }}
                        className="flex-1 px-3 py-2 rounded-xl border border-border bg-background file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-medium"
                      />
                    </label>
                    <button
                      onClick={() => savePost(post, index)}
                      disabled={saving || (!post.text.trim() && !post.imageFile && !post.image_base64)}
                      className="px-4 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50 inline-flex items-center gap-2"
                    >
                      {saving && <CircleNotch size={14} className="animate-spin" />}
                      Сохранить пост {index + 1}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </motion.div>
      </div>
    </div>
  )
}
