import { useState, useEffect, useRef } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import {
  VideoCamera,
  UploadSimple,
  PaperPlaneRight,
  UserCircle,
  XCircle,
  CheckCircle,
  SpinnerGap
} from '@phosphor-icons/react'

export default function VideoNotes() {
  const [accounts, setAccounts] = useState<{id: number, phone_number: string}[]>([])
  const [accountId, setAccountId] = useState<number | null>(null)
  const [chats, setChats] = useState('')
  const [videoFile, setVideoFile] = useState<File | null>(null)
  const [videoPreview, setVideoPreview] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [statusMsg, setStatusMsg] = useState<{type: 'success'|'error', text: string} | null>(null)
  
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const fetchAccounts = async () => {
      try {
        const res = await api.get('/api/v1/accounts')
        setAccounts(res.data)
      } catch (error) {
        console.error('Ошибка загрузки аккаунтов:', error)
      }
    }
    fetchAccounts()
  }, [])

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      if (file.size > 20 * 1024 * 1024) {
        setStatusMsg({ type: 'error', text: 'Файл слишком большой. Максимум 20 МБ.' })
        return
      }
      setVideoFile(file)
      const url = URL.createObjectURL(file)
      setVideoPreview(url)
      setStatusMsg(null)
    }
  }

  const handleRemoveVideo = () => {
    setVideoFile(null)
    if (videoPreview) {
      URL.revokeObjectURL(videoPreview)
    }
    setVideoPreview(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!accountId || !videoFile || !chats.trim()) {
      setStatusMsg({ type: 'error', text: 'Заполните все поля и выберите видео.' })
      return
    }

    setIsSubmitting(true)
    setStatusMsg(null)

    const formData = new FormData()
    formData.append('account_id', accountId.toString())
    formData.append('chats', chats)
    formData.append('video', videoFile)

    try {
      const response = await api.post('/api/v1/video/send-note', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      })
      setStatusMsg({ type: 'success', text: response.data.message })
      // Clear form
      setChats('')
      handleRemoveVideo()
    } catch (error: any) {
      setStatusMsg({ type: 'error', text: error.response?.data?.detail || 'Произошла ошибка при отправке.' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="space-y-8 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Кружки из видео</h1>
          <p className="text-muted-foreground mt-1">Отправка видеосообщений в Telegram с автоматической конвертацией</p>
        </div>
        <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-primary">
          <VideoCamera size={32} weight="fill" />
        </div>
      </div>

      <div className="bg-card rounded-3xl border border-border overflow-hidden">
        <form onSubmit={handleSubmit} className="p-8 space-y-8">
          
          {statusMsg && (
            <motion.div 
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              className={`p-4 rounded-xl flex items-center gap-3 ${statusMsg.type === 'success' ? 'bg-emerald-500/10 text-emerald-600' : 'bg-red-500/10 text-red-600'}`}
            >
              {statusMsg.type === 'success' ? <CheckCircle size={20} weight="fill" /> : <XCircle size={20} weight="fill" />}
              <span className="font-medium">{statusMsg.text}</span>
            </motion.div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-6">
              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <UserCircle size={18} />
                  Аккаунт-отправитель
                </label>
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

              <div className="space-y-2">
                <label className="text-sm font-medium flex items-center gap-2">
                  <PaperPlaneRight size={18} />
                  Получатели (по одному на строку)
                </label>
                <textarea
                  value={chats}
                  onChange={(e) => setChats(e.target.value)}
                  placeholder="@username&#10;https://t.me/chat_link&#10;123456789"
                  rows={6}
                  className="w-full px-4 py-3 rounded-xl border border-border bg-background focus:border-primary outline-none resize-none font-mono text-sm"
                  required
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium flex items-center gap-2">
                <VideoCamera size={18} />
                Видеофайл
              </label>
              
              {!videoFile ? (
                <div 
                  className="border-2 border-dashed border-border rounded-3xl p-8 flex flex-col items-center justify-center text-center hover:bg-muted/30 transition-colors cursor-pointer min-h-[300px]"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center text-primary mb-4">
                    <UploadSimple size={24} weight="bold" />
                  </div>
                  <h3 className="font-medium text-lg mb-1">Загрузить видео</h3>
                  <p className="text-sm text-muted-foreground max-w-[200px]">
                    MP4 или MOV, до 20 МБ, желательно до 60 сек
                  </p>
                </div>
              ) : (
                <div className="relative rounded-3xl border border-border overflow-hidden bg-black flex items-center justify-center min-h-[300px]">
                  {videoPreview && (
                    <video 
                      src={videoPreview} 
                      className="w-full h-full object-contain max-h-[300px]"
                      controls 
                    />
                  )}
                  <button
                    type="button"
                    onClick={handleRemoveVideo}
                    className="absolute top-4 right-4 p-2 bg-black/50 hover:bg-red-500 text-white rounded-full transition-colors backdrop-blur-md"
                  >
                    <XCircle size={24} weight="fill" />
                  </button>
                </div>
              )}
              
              <input 
                type="file" 
                ref={fileInputRef}
                className="hidden" 
                accept="video/mp4,video/quicktime,video/x-msvideo"
                onChange={handleFileChange}
              />
            </div>
          </div>

          <div className="pt-6 border-t border-border/50 flex justify-end">
            <button
              type="submit"
              disabled={isSubmitting || !accountId || !videoFile || !chats.trim()}
              className="px-8 py-3 rounded-xl bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-3"
            >
              {isSubmitting ? (
                <>
                  <SpinnerGap size={20} className="animate-spin" />
                  Отправка...
                </>
              ) : (
                <>
                  <PaperPlaneRight size={20} weight="fill" />
                  Конвертировать и Отправить
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
