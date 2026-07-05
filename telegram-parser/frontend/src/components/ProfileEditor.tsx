/* Profile editor + personal-channel management modal for an Account.

The modal fetches the cached profile fields from the backend, lets
the operator edit name / bio / username, upload an avatar, create
a personal broadcast channel and post to it. Every change is
mirrored on the Telegram account via the backend.

This file is intentionally self-contained — Accounts.tsx is already
large and we want to keep the diff small.
*/
import { useEffect, useRef, useState } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  X,
  UserCircle,
  At,
  IdentificationCard,
  FileText,
  Upload,
  Television,
  PaperPlaneTilt,
  CircleNotch,
  CheckCircle,
  Warning,
  GenderIntersex
} from '@phosphor-icons/react'

interface Account {
  id: number
  phone_number: string
  status: string
  proxy_id?: number
  has_session: boolean
  first_name?: string | null
  last_name?: string | null
  bio?: string | null
  username?: string | null
  avatar_path?: string | null
  gender?: string
  personal_channel_id?: number | null
  personal_channel_username?: string | null
}

interface Props {
  account: Account | null
  accounts: Account[]
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

interface ChannelTemplateOption {
  id: number
  name: string
  channel_title: string
  posts: { id: number; position: number; text: string; image_filename?: string | null }[]
}

function base64ToFile(base64: string, filename: string, mimeType: string) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i)
  }
  return new File([bytes], filename, { type: mimeType || 'image/jpeg' })
}

export function ProfileEditor({ account, accounts, isOpen, onClose, onSuccess }: Props) {
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [bio, setBio] = useState('')
  const [username, setUsername] = useState('')
  const [usernameCheck, setUsernameCheck] = useState('')
  const [checkingUsername, setCheckingUsername] = useState(false)
  const [gender, setGender] = useState('unknown')
  const [nameLocale, setNameLocale] = useState<'ru' | 'en'>('ru')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [avatarFile, setAvatarFile] = useState<File | null>(null)
  const [avatarPreviewUrl, setAvatarPreviewUrl] = useState('')
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [avatarOk, setAvatarOk] = useState(false)
  const [randomizingProfile, setRandomizingProfile] = useState(false)
  const [randomPresetOk, setRandomPresetOk] = useState('')
  const [refreshing, setRefreshing] = useState(false)

  // Channel state
  const [chTitle, setChTitle] = useState('')
  const [chAbout, setChAbout] = useState('')
  const [chUsername, setChUsername] = useState('')
  const [chSetPersonal, setChSetPersonal] = useState(true)
  const [creatingChannel, setCreatingChannel] = useState(false)
  const [chError, setChError] = useState('')
  const [chOk, setChOk] = useState<{ channel_id: number; channel_username?: string; title: string } | null>(null)
  const [channelTemplates, setChannelTemplates] = useState<ChannelTemplateOption[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | null>(null)
  const [applyingChannelTemplate, setApplyingChannelTemplate] = useState(false)
  const [postText, setPostText] = useState('')
  const [posting, setPosting] = useState(false)
  const [postOk, setPostOk] = useState(false)
  const [mediaPosts, setMediaPosts] = useState<{ text: string; image: File | null }[]>([{ text: '', image: null }])
  const [postingMedia, setPostingMedia] = useState(false)
  const [mediaPostOk, setMediaPostOk] = useState('')
  const [templateTargetIds, setTemplateTargetIds] = useState<number[]>([])
  const [templateTitle, setTemplateTitle] = useState('')
  const [templateAbout, setTemplateAbout] = useState('')
  const [templatePosts, setTemplatePosts] = useState('')
  const [applyingTemplate, setApplyingTemplate] = useState(false)
  const [templateError, setTemplateError] = useState('')
  const [templateOk, setTemplateOk] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (!avatarFile) {
      setAvatarPreviewUrl('')
      return
    }
    const url = URL.createObjectURL(avatarFile)
    setAvatarPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [avatarFile])

  useEffect(() => {
    if (!account) return
    setFirstName(account.first_name || '')
    setLastName(account.last_name || '')
    setBio(account.bio || '')
    setUsername(account.username || '')
    setUsernameCheck('')
    setGender(account.gender || 'unknown')
    setNameLocale('ru')
    setChTitle('')
    setChAbout('')
    setChUsername('')
    setChSetPersonal(true)
    // Show the template that is already applied to this account (instead of
    // defaulting to "— без шаблона —"), so there's no ambiguity.
    setSelectedTemplateId((account as any).personal_channel_template_id ?? null)
    setApplyingChannelTemplate(false)
    setAvatarFile(null)
    setAvatarPreviewUrl('')
    setAvatarOk(false)
    setRandomPresetOk('')
    setSavedAt(null)
    setChOk(null)
    setChError('')
    setError('')
    setPostText('')
    setPostOk(false)
    setMediaPosts([{ text: '', image: null }])
    setPostingMedia(false)
    setMediaPostOk('')
    setTemplateTargetIds([])
    setTemplateTitle('')
    setTemplateAbout('')
    setTemplatePosts('')
    setApplyingTemplate(false)
    setTemplateError('')
    setTemplateOk('')
  }, [account?.id, isOpen])

  useEffect(() => {
    if (!isOpen) return
    api.get('/api/v1/personal-channel-templates')
      .then(res => setChannelTemplates(res.data))
      .catch(error => console.error('Не удалось загрузить шаблоны личного канала', error))
  }, [isOpen])

  const save = async () => {
    if (!account) return
    setSaving(true)
    setError('')
    try {
      // Update gender via the standard PUT endpoint
      await api.put(`/api/v1/accounts/${account.id}`, { gender })
      // Profile fields go through the dedicated endpoint
      const profile: any = {}
      if (firstName !== (account.first_name || '')) profile.first_name = firstName
      if (lastName !== (account.last_name || '')) profile.last_name = lastName
      if (bio !== (account.bio || '')) profile.bio = bio
      if (username !== (account.username || '')) profile.username = username
      if (Object.keys(profile).length > 0) {
        await api.post(`/api/v1/accounts/${account.id}/profile`, profile)
      }
      if (avatarFile) {
        const fd = new FormData()
        fd.append('file', avatarFile)
        await api.post(`/api/v1/accounts/${account.id}/profile/avatar`, fd, {
          headers: { 'Content-Type': 'multipart/form-data' },
        })
        setAvatarOk(true)
        setAvatarFile(null)
        if (fileRef.current) fileRef.current.value = ''
      }
      setSavedAt(new Date())
      onSuccess()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const randomizeProfile = async () => {
    if (!account) return
    setError('')
    setRandomPresetOk('')
    if (gender !== 'male' && gender !== 'female') {
      setError('Сначала выберите пол: мужской или женский')
      return
    }
    setRandomizingProfile(true)
    try {
      const res = await api.post(`/api/v1/accounts/${account.id}/profile/random-preset`, {
        gender,
        locale: nameLocale,
      })
      setFirstName(res.data.first_name || '')
      setLastName(res.data.last_name || '')
      setUsername(res.data.username || '')
      if (res.data.avatar_base64) {
        setAvatarFile(base64ToFile(
          res.data.avatar_base64,
          res.data.avatar_filename || 'avatar.jpg',
          res.data.avatar_mime_type || 'image/jpeg',
        ))
        if (fileRef.current) fileRef.current.value = ''
      }
      setRandomPresetOk(`Выбрано: ${res.data.first_name} ${res.data.last_name}, @${res.data.username}`)
      setAvatarOk(false)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось выбрать случайный профиль')
    } finally {
      setRandomizingProfile(false)
    }
  }

  const uploadAvatar = async () => {
    if (!account || !avatarFile) return
    setUploadingAvatar(true)
    setError('')
    setAvatarOk(false)
    try {
      const fd = new FormData()
      fd.append('file', avatarFile)
      await api.post(`/api/v1/accounts/${account.id}/profile/avatar`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setAvatarOk(true)
      setAvatarFile(null)
      if (fileRef.current) fileRef.current.value = ''
      onSuccess()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось загрузить аватар')
    } finally {
      setUploadingAvatar(false)
    }
  }

  const refresh = async () => {
    if (!account) return
    setRefreshing(true)
    setError('')
    try {
      const res = await api.post(`/api/v1/accounts/${account.id}/profile/refresh`)
      onSuccess()
      setFirstName(res.data.first_name || '')
      setLastName(res.data.last_name || '')
      setBio(res.data.bio || '')
      setUsername(res.data.username || '')
      setGender(res.data.gender || 'unknown')
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setError(typeof detail === 'string' ? detail : 'Не удалось обновить')
    } finally {
      setRefreshing(false)
    }
  }

  const checkUsername = async () => {
    if (!account || !username.trim()) return
    setCheckingUsername(true)
    setUsernameCheck('')
    setError('')
    try {
      const res = await api.post(`/api/v1/accounts/${account.id}/profile/check-username`, {
        username: username.trim().replace(/^@/, ''),
      })
      setUsernameCheck(res.data.available ? 'Username свободен' : `Username недоступен${res.data.reason ? `: ${res.data.reason}` : ''}`)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setUsernameCheck(typeof detail === 'string' ? detail : 'Не удалось проверить username')
    } finally {
      setCheckingUsername(false)
    }
  }

  const createChannel = async () => {
    if (!account) return
    if (!chTitle.trim()) {
      setChError('Введите название канала')
      return
    }
    setCreatingChannel(true)
    setChError('')
    setChOk(null)
    try {
      const res = await api.post(`/api/v1/accounts/${account.id}/personal-channel`, {
        title: chTitle,
        about: chAbout || null,
        username: chUsername || null,
        set_as_personal: chSetPersonal,
      })
      setChOk(res.data)
      onSuccess()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setChError(typeof detail === 'string' ? detail : 'Не удалось создать канал')
    } finally {
      setCreatingChannel(false)
    }
  }

  const applySelectedChannelTemplate = async () => {
    if (!account || !selectedTemplateId) return
    setApplyingChannelTemplate(true)
    setChError('')
    setChOk(null)
    try {
      const res = await api.post(
        `/api/v1/personal-channel-templates/${selectedTemplateId}/apply`,
        {
          account_ids: [account.id],
          create_if_missing: true,
        },
        {
          timeout: 180000,
        }
      )
      const row = res.data?.results?.[0]
      if (!row) {
        setChError('Сервис не вернул результат применения шаблона')
      } else if (row.status !== 'applied') {
        setChError(row.reason || 'Шаблон не был применён')
      } else {
        setChOk({
          channel_id: row?.channel_id || account.personal_channel_id || 0,
          title: channelTemplates.find(item => item.id === selectedTemplateId)?.channel_title || 'Личный канал',
        })
        if (row.posted > 0) {
          setMediaPostOk(`Шаблон применён. Опубликовано постов: ${row.posted}`)
        }
        onSuccess()
      }
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setChError(typeof detail === 'string' ? detail : 'Не удалось применить шаблон')
    } finally {
      setApplyingChannelTemplate(false)
    }
  }

  const postToChannel = async () => {
    if (!account) return
    if (!postText.trim()) {
      return
    }
    setPosting(true)
    setPostOk(false)
    try {
      await api.post(`/api/v1/accounts/${account.id}/personal-channel/post`, { text: postText })
      setPostOk(true)
      setPostText('')
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setChError(typeof detail === 'string' ? detail : 'Не удалось отправить пост')
    } finally {
      setPosting(false)
    }
  }

  const updateMediaPost = (index: number, patch: Partial<{ text: string; image: File | null }>) => {
    setMediaPosts(prev => prev.map((item, i) => (i === index ? { ...item, ...patch } : item)))
  }

  const addMediaPost = () => {
    setMediaPosts(prev => [...prev, { text: '', image: null }])
  }

  const removeMediaPost = (index: number) => {
    setMediaPosts(prev => (prev.length === 1 ? prev : prev.filter((_, i) => i !== index)))
  }

  const postManyToChannel = async () => {
    if (!account) return
    const ready = mediaPosts.filter(item => item.text.trim())
    if (ready.length === 0) return
    setPostingMedia(true)
    setMediaPostOk('')
    setChError('')
    try {
      const fd = new FormData()
      ready.forEach(item => fd.append('texts', item.text.trim()))
      ready.forEach(item => {
        if (item.image) fd.append('images', item.image)
      })
      const res = await api.post(`/api/v1/accounts/${account.id}/personal-channel/posts`, fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setMediaPostOk(`Опубликовано постов: ${res.data?.posted || ready.length}`)
      setMediaPosts([{ text: '', image: null }])
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setChError(typeof detail === 'string' ? detail : 'Не удалось отправить посты')
    } finally {
      setPostingMedia(false)
    }
  }

  const toggleTemplateTarget = (targetId: number) => {
    setTemplateTargetIds(prev =>
      prev.includes(targetId) ? prev.filter(id => id !== targetId) : [...prev, targetId]
    )
  }

  const applyTemplate = async () => {
    if (!account) return
    if (!templateTitle.trim()) {
      setTemplateError('Введите название канала для шаблона')
      return
    }
    if (templateTargetIds.length === 0) {
      setTemplateError('Выберите хотя бы один аккаунт')
      return
    }
    setApplyingTemplate(true)
    setTemplateError('')
    setTemplateOk('')
    try {
      const posts = templatePosts
        .split('\n---\n')
        .map(item => item.trim())
        .filter(Boolean)

      const res = await api.post(`/api/v1/accounts/${account.id}/personal-channel/apply-template`, {
        target_account_ids: templateTargetIds,
        title: templateTitle.trim(),
        about: templateAbout.trim() || null,
        posts,
        create_if_missing: true,
      })
      const applied = Number(res.data?.applied || 0)
      setTemplateOk(`Шаблон применён к ${applied} аккаунтам`)
      onSuccess()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setTemplateError(typeof detail === 'string' ? detail : 'Не удалось применить шаблон')
    } finally {
      setApplyingTemplate(false)
    }
  }

  if (!account) return null
  const noProxy = !account.proxy_id
  const projectAccounts = accounts.filter(item => item.id !== account.id)

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
            className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <h2 className="text-xl font-semibold flex items-center gap-2">
                <UserCircle size={22} weight="duotone" />
                Профиль аккаунта
                <span className="text-sm text-muted-foreground font-normal">{account.phone_number}</span>
              </h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-muted">
                <X size={20} />
              </button>
            </div>

            {noProxy && (
              <div className="m-6 p-3 rounded-xl bg-red-500/10 text-red-700 text-xs flex items-start gap-2">
                <Warning size={16} weight="bold" className="shrink-0 mt-0.5" />
                <span>
                  К аккаунту <b>не привязан прокси</b>. Сохранение профиля и любые действия с Telegram
                  будут отклонены. Сначала привяжите прокси.
                </span>
              </div>
            )}

            <div className="p-6 space-y-5">
              {/* Profile fields */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground flex items-center gap-1">
                    <IdentificationCard size={12} /> Имя
                  </label>
                  <input
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    maxLength={64}
                    disabled={noProxy}
                    className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background disabled:opacity-50"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Фамилия</label>
                  <input
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    maxLength={64}
                    disabled={noProxy}
                    className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background disabled:opacity-50"
                  />
                </div>
              </div>

              <div>
                <label className="text-xs text-muted-foreground flex items-center gap-1">
                  <At size={12} /> Username
                </label>
                <div className="mt-1 flex gap-2">
                  <input
                    value={username}
                    onChange={(e) => {
                      setUsername(e.target.value.toLowerCase())
                      setUsernameCheck('')
                    }}
                    maxLength={32}
                    placeholder="my_handle"
                    disabled={noProxy}
                    className="flex-1 px-3 py-2 rounded-xl border border-border bg-background font-mono disabled:opacity-50"
                  />
                  <button
                    onClick={checkUsername}
                    disabled={checkingUsername || noProxy || !username.trim()}
                    className="px-3 py-2 rounded-xl border border-border hover:bg-muted disabled:opacity-50 text-sm"
                  >
                    {checkingUsername ? 'Проверка…' : 'Проверить'}
                  </button>
                </div>
                <p className="text-xs text-muted-foreground mt-1">5-32 символа, латиница/цифры/_</p>
                {usernameCheck && (
                  <p className={`text-xs mt-1 ${usernameCheck.includes('свободен') ? 'text-emerald-600' : 'text-amber-600'}`}>
                    {usernameCheck}
                  </p>
                )}
              </div>

              <div>
                <label className="text-xs text-muted-foreground flex items-center gap-1">
                  <FileText size={12} /> Bio (до 70 символов)
                </label>
                <textarea
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  maxLength={70}
                  rows={2}
                  disabled={noProxy}
                  className="w-full mt-1 px-3 py-2 rounded-xl border border-border bg-background disabled:opacity-50 resize-none"
                />
                <p className="text-xs text-muted-foreground mt-1 text-right">{bio.length}/70</p>
              </div>

              <div>
                <label className="text-xs text-muted-foreground flex items-center gap-1">
                  <GenderIntersex size={12} /> Пол (для фильтрации)
                </label>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-[1fr_auto_auto]">
                  <select
                    value={gender}
                    onChange={(e) => setGender(e.target.value)}
                    className="w-full px-3 py-2 rounded-xl border border-border bg-background"
                  >
                    <option value="unknown">Не указан</option>
                    <option value="male">Мужской</option>
                    <option value="female">Женский</option>
                  </select>
                  <div className="inline-flex rounded-xl border border-border bg-muted p-1">
                    <button
                      type="button"
                      onClick={() => setNameLocale('ru')}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                        nameLocale === 'ru' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'
                      }`}
                    >
                      рус
                    </button>
                    <button
                      type="button"
                      onClick={() => setNameLocale('en')}
                      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                        nameLocale === 'en' ? 'bg-card text-foreground shadow-sm' : 'text-muted-foreground'
                      }`}
                    >
                      англ
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={randomizeProfile}
                    disabled={randomizingProfile || gender === 'unknown'}
                    className="px-3 py-2 rounded-xl border border-primary/30 text-primary hover:bg-primary/10 disabled:opacity-50 flex items-center justify-center gap-1"
                  >
                    {randomizingProfile ? <CircleNotch size={14} className="animate-spin" /> : <UserCircle size={14} />}
                    Случайно
                  </button>
                </div>
                {randomPresetOk && (
                  <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1">
                    <CheckCircle size={12} weight="bold" />
                    {randomPresetOk}
                  </p>
                )}
              </div>

              <div>
                <label className="text-xs text-muted-foreground flex items-center gap-1">
                  <Upload size={12} /> Аватар
                </label>
                {avatarPreviewUrl && (
                  <div className="mt-2 flex items-center gap-3 rounded-2xl border border-border/60 bg-muted/30 p-3">
                    <img
                      src={avatarPreviewUrl}
                      alt="Предпросмотр аватара"
                      className="h-20 w-20 rounded-2xl object-cover border border-border"
                    />
                    <div className="min-w-0">
                      <p className="text-sm font-medium">Предпросмотр аватара</p>
                      <p className="text-xs text-muted-foreground break-all">{avatarFile?.name}</p>
                      <p className="text-xs text-muted-foreground mt-1">
                        Нажмите “Сохранить” или “Загрузить”, чтобы отправить его в Telegram.
                      </p>
                    </div>
                  </div>
                )}
                <div className="flex items-center gap-2 mt-1">
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/jpeg,image/png"
                    onChange={(e) => {
                      setAvatarFile(e.target.files?.[0] || null)
                      setAvatarOk(false)
                    }}
                    disabled={noProxy}
                    className="flex-1 px-3 py-2 rounded-xl border border-border bg-background file:mr-3 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-primary/10 file:text-primary file:font-medium disabled:opacity-50"
                  />
                  <button
                    onClick={uploadAvatar}
                    disabled={!avatarFile || uploadingAvatar || noProxy}
                    className="px-3 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50"
                  >
                    {uploadingAvatar ? <CircleNotch size={14} className="animate-spin" /> : 'Загрузить'}
                  </button>
                </div>
                {avatarFile && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Подготовлен аватар: {avatarFile.name}. Можно нажать “Сохранить” или “Загрузить”.
                  </p>
                )}
                {avatarOk && <p className="text-xs text-emerald-600 mt-1 flex items-center gap-1"><CheckCircle size={12} weight="bold" /> Аватар обновлён</p>}
              </div>

              {error && <p className="text-sm text-red-500 bg-red-500/10 px-3 py-2 rounded-lg">{error}</p>}

              <div className="flex gap-2 pt-1">
                <button
                  onClick={refresh}
                  disabled={refreshing || noProxy}
                  title="Считать текущие имя, username, bio, аватар и пол из Telegram и обновить локальную карточку"
                  className="px-3 py-2 rounded-xl border border-border hover:bg-muted disabled:opacity-50 flex items-center gap-1"
                >
                  {refreshing ? <CircleNotch size={14} className="animate-spin" /> : <UserCircle size={14} />}
                  Обновить из Telegram
                </button>
                <div className="flex-1" />
                <button
                  onClick={save}
                  disabled={saving || noProxy}
                  className="px-5 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50 flex items-center gap-1"
                >
                  {saving ? <CircleNotch size={14} className="animate-spin" /> : null}
                  Сохранить
                </button>
              </div>
              {savedAt && (
                <p className="text-xs text-emerald-600 flex items-center gap-1">
                  <CheckCircle size={12} weight="bold" />
                  Сохранено в {savedAt.toLocaleTimeString()}
                </p>
              )}

              {/* Personal channel */}
              <div className="border-t border-border/50 pt-4 mt-2">
                <h3 className="text-sm font-semibold mb-2 flex items-center gap-2">
                  <Television size={16} weight="duotone" />
                  Личный канал
                </h3>
                <div className="mb-3 rounded-2xl border border-border/60 bg-muted/20 p-3 space-y-2">
                  <label className="text-xs text-muted-foreground">Шаблон наполнения</label>
                  <div className="flex flex-col sm:flex-row gap-2">
                    <select
                      value={selectedTemplateId ?? ''}
                      onChange={(e) => setSelectedTemplateId(e.target.value ? Number(e.target.value) : null)}
                      disabled={noProxy}
                      className="flex-1 px-3 py-2 rounded-xl border border-border bg-background disabled:opacity-50"
                    >
                      <option value="">— без шаблона —</option>
                      {channelTemplates.map(template => (
                        <option key={template.id} value={template.id}>
                          {template.name} · {template.posts.length} пост(ов)
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={applySelectedChannelTemplate}
                      disabled={!selectedTemplateId || applyingChannelTemplate || noProxy}
                      className="px-3 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50 flex items-center justify-center gap-1"
                    >
                      {applyingChannelTemplate ? <CircleNotch size={14} className="animate-spin" /> : <Television size={14} />}
                      Применить шаблон
                    </button>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Если личного канала ещё нет, шаблон создаст канал и опубликует посты по порядку.
                  </p>
                  {(account as any).personal_channel_template_id && (
                    <div className="text-sm text-emerald-600 flex items-center gap-1 font-medium">
                      <CheckCircle size={14} weight="bold" />
                      Применён шаблон: {channelTemplates.find(t => t.id === (account as any).personal_channel_template_id)?.name || `#${(account as any).personal_channel_template_id}`}
                    </div>
                  )}
                </div>
                {account.personal_channel_id && (
                  <div className="text-sm text-emerald-600 flex items-center gap-1">
                    <CheckCircle size={14} weight="bold" />
                    Привязан: {account.personal_channel_username ? `@${account.personal_channel_username}` : `id ${account.personal_channel_id}`}
                  </div>
                )}
                {chError && <p className="text-xs text-red-500">{chError}</p>}
                {chOk && (
                  <p className="text-xs text-emerald-600 flex items-center gap-1">
                    <CheckCircle size={12} weight="bold" /> Шаблон применён: {chOk.title}
                  </p>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
