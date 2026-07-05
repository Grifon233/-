import { useState, useEffect } from 'react'
import { format, startOfMonth, endOfMonth, eachDayOfInterval, isSameDay, isToday } from 'date-fns'
import { ru } from 'date-fns/locale'
import { ChevronLeft, ChevronRight, Clock, User, Phone, Plus, Settings as SettingsIcon, X, StickyNote, Trash2 } from 'lucide-react'
import { getBookings, updateBooking, getMaster, getServices, createAdminBooking } from '../utils/api'
import { Link, useLocation } from 'react-router-dom'
import { resolveMediaUrl } from '../utils/media'

const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')

// Авторизация запроса свободных слотов. Календарь мастера открывается как из
// Telegram (bot_id), так и из ВКонтакте (vk_user/vk_sig). Пробрасываем все
// параметры из адреса страницы, иначе сервер отдаёт 403 и все даты гаснут.
function slotAuthParams() {
  const src = new URLSearchParams(window.location.search)
  const out = new URLSearchParams()
  for (const key of ['bot_id', 'vk_bot_id', 'vk_user', 'vk_sig', 'auth_ts']) {
    const value = src.get(key)
    if (value) out.set(key, value)
  }
  const qs = out.toString()
  return qs ? `&${qs}` : ''
}

const STATUS = {
  upcoming: { label: 'Предстоящая', bg: 'rgba(212, 168, 83, 0.15)', text: '#d4a853' },
  completed: { label: 'Завершена', bg: 'rgba(74, 222, 128, 0.1)', text: '#4ade80' },
  cancelled: { label: 'Отменена', bg: 'rgba(248, 113, 113, 0.1)', text: '#f87171' },
}

function DateAvailabilityCalendar({ currentMonth, setCurrentMonth, selectedDate, onSelectDate, availableDates, loading, minDate }) {
  const monthStart = startOfMonth(currentMonth)
  const monthEnd = endOfMonth(currentMonth)
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd })
  const leadingDays = (monthStart.getDay() + 6) % 7

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <button type="button" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() - 1, 1))} className="p-2 rounded-lg btn-ghost">
          <ChevronLeft size={18} />
        </button>
        <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{format(currentMonth, 'LLLL yyyy', { locale: ru })}</div>
        <button type="button" onClick={() => setCurrentMonth(new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 1))} className="p-2 rounded-lg btn-ghost">
          <ChevronRight size={18} />
        </button>
      </div>
      <div className="grid grid-cols-7 gap-1 text-[11px] uppercase">
        {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map(day => (
          <div key={day} className="text-center py-1" style={{ color: 'var(--color-text-muted)' }}>{day}</div>
        ))}
        {Array.from({ length: leadingDays }).map((_, index) => <div key={`empty-${index}`} />)}
        {days.map(day => {
          const dateStr = format(day, 'yyyy-MM-dd')
          const available = availableDates[dateStr] === true
          const known = Object.prototype.hasOwnProperty.call(availableDates, dateStr)
          const isPast = minDate && day < minDate
          const isSelected = selectedDate === dateStr
          const disabled = isPast || (known && !available)
          return (
            <button
              key={dateStr}
              type="button"
              onClick={() => !disabled && onSelectDate(dateStr)}
              disabled={disabled}
              className="aspect-square rounded-lg text-sm font-medium transition-all"
              style={{
                backgroundColor: isSelected ? 'var(--color-accent)' : 'var(--color-surface-elevated)',
                color: isSelected ? '#fff' : disabled ? 'var(--color-text-muted)' : 'var(--color-text)',
                opacity: disabled ? 0.38 : known || loading ? 1 : 0.7,
                border: `1px solid ${isSelected ? 'var(--color-accent)' : 'var(--color-border)'}`,
              }}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>
      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
        {loading ? 'Проверяем доступные даты...' : 'Блеклые даты недоступны для выбранной длительности.'}
      </p>
    </div>
  )
}

function uniqueSlots(slots) {
  const seen = new Set()
  return (slots || []).filter(slot => {
    const key = slot?.time?.slice(0, 5)
    if (!key || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

// Ссылка устарела/недействительна — бэкенд просит заново открыть бота и нажать «Старт».
function isExpiredLinkMessage(message) {
  return typeof message === 'string' && (message.includes('нажмите «Старт»') || message.includes('устарел'))
}

export default function Calendar() {
  const location = useLocation()
  const [currentDate, setCurrentDate] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState(null)
  const [bookings, setBookings] = useState([])
  const [loading, setLoading] = useState(true)
  const [master, setMaster] = useState(null)
  const [services, setServices] = useState([])
  const [showRescheduleModal, setShowRescheduleModal] = useState(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [linkExpired, setLinkExpired] = useState(false)
  const [avatarError, setAvatarError] = useState(false)

  useEffect(() => { loadBookings(); loadMaster(); loadServices() }, [])

  async function loadMaster() {
    try {
      const m = await getMaster()
      setMaster(m)
    } catch (e) { if (isExpiredLinkMessage(e?.message)) setLinkExpired(true) }
  }

  async function loadServices() {
    try {
      const s = await getServices()
      setServices(s.services || [])
    } catch (e) { if (isExpiredLinkMessage(e?.message)) setLinkExpired(true) }
  }

  async function loadBookings() {
    try {
      const data = await getBookings()
      setBookings(data.bookings || [])
    } catch (e) { setBookings([]); if (isExpiredLinkMessage(e?.message)) setLinkExpired(true) }
    finally { setLoading(false) }
  }

  async function handleAddBooking(bookingData) {
    try {
      await createAdminBooking({ ...bookingData })
      setShowAddModal(null)
      loadBookings()
    } catch (e) {
      alert('Ошибка: ' + e.message)
    }
  }

  function authQuery() {
    const params = new URLSearchParams(location.search)
    const auth = new URLSearchParams()
    ;['user', 'user_id', 'username', 'name', 'sig', 'master_id', 'bot_id', 'auth_ts', 'vk_user', 'auth_source'].forEach(key => {
      const value = params.get(key)
      if (value) auth.set(key, value)
    })
    const query = auth.toString()
    return query ? `&${query}` : ''
  }

  async function handleRescheduleSubmit(id, newDate, newTime, comment, serviceIds) {
    const response = await fetch(`${API_URL}/api/bookings/${id}/reschedule?${authQuery().replace(/^&/, '')}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_date: newDate, new_time: newTime, comment, service_ids: serviceIds })
    })
    if (!response.ok) {
      const detail = await response.json().then(d => d.detail).catch(() => null)
      throw new Error(typeof detail === 'string' ? detail : 'Не удалось перенести запись')
    }
    setShowRescheduleModal(null)
    loadBookings()
  }

  async function handleCancelSubmit(id, comment) {
    const auth = authQuery().replace(/^&/, '?')
    const response = await fetch(`${API_URL}/api/bookings/${id}${auth}`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: comment || '', cancelled_by: 'master' })
    })
    if (!response.ok) {
      const detail = await response.json().then(d => d.detail).catch(() => null)
      throw new Error(typeof detail === 'string' ? detail : 'Не удалось отменить запись')
    }
    setShowRescheduleModal(null)
    loadBookings()
  }

  async function handleModalSubmit(booking, param1, param2, param3, param4) {
    const id = booking.id
    const isCancel = booking.mode === 'cancel'
    // Раньше ошибки переноса/отмены молча уходили в консоль, и мастеру казалось,
    // что кнопка сломалась. Теперь показываем причину и оставляем окно открытым.
    try {
      if (isCancel) {
        await handleCancelSubmit(id, param1)
      } else {
        await handleRescheduleSubmit(id, param1, param2, param3, param4)
      }
    } catch (e) {
      alert('Не удалось сохранить: ' + (e?.message || 'ошибка сервера'))
    }
  }

  async function handleHardDelete(id) {
    try {
      const auth = authQuery().replace(/^&/, '?')
      await fetch(`${API_URL}/api/bookings/${id}/hard${auth}`, { method: 'DELETE' })
      loadBookings()
    } catch (e) { console.error(e) }
  }

  const monthStart = startOfMonth(currentDate)
  const monthEnd = endOfMonth(currentDate)
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd })
  const weekDays = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

  const selectedBookings = selectedDate
    ? bookings.filter(b => b.date === format(selectedDate, 'yyyy-MM-dd'))
    : []

  const avatarUrl = resolveMediaUrl(master?.avatar_url)

  useEffect(() => {
    setAvatarError(false)
  }, [avatarUrl])

  const isDemoUrl = new URLSearchParams(location.search).get('demo') === '1'
  const isDemo = master?.is_demo === true || isDemoUrl
  const [showDemoMessage, setShowDemoMessage] = useState(null)
  const [showDemoAddModal, setShowDemoAddModal] = useState(false)

  function handleDemoAction(action) {
    if (action === 'add') {
      setShowDemoAddModal(true)
      return
    }
    setShowDemoMessage(action)
    setTimeout(() => setShowDemoMessage(null), 3000)
  }

  if (linkExpired) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="card w-full max-w-md rounded-2xl p-6 text-center">
          <div className="text-4xl mb-3">🔗</div>
          <h1 className="text-xl font-bold">Ссылка больше не актуальна</h1>
          <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
            Откройте бота в Telegram и нажмите «Старт» (/start) — бот пришлёт свежую ссылку,
            чтобы снова зайти в календарь.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-[calc(100vh-100px)] min-h-[600px] flex gap-6 py-10
      max-md:flex-col max-md:gap-4 max-md:py-4 max-md:h-auto max-md:min-h-0">
      {isDemo && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-yellow-500/90 text-black text-center py-2 text-sm font-medium">
          Демо-режим — просмотр записей
        </div>
      )}
      {showDemoMessage && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: showDemoMessage === 'add_block' ? 'var(--color-accent)' : 'var(--color-error)', color: showDemoMessage === 'add_block' ? '#0a0a0a' : 'white' }}>
          {showDemoMessage === 'add_block' ? 'В демо-режиме нельзя добавлять записи' : 'Недоступно в демо-режиме'}
        </div>
      )}
      {/* Calendar Card - Premium Dark */}
      <div className="flex-1 flex flex-col card overflow-hidden max-md:min-h-[350px]">
        {/* Header - Gold Accent */}
        <div className="px-6 py-5 flex items-center gap-4 max-md:px-4 max-md:py-3 max-md:gap-3" style={{ background: 'linear-gradient(135deg, #1a1a1a 0%, #0f0f0f 100%)' }}>
          {avatarUrl && !avatarError ? (
            <img
              src={avatarUrl}
              alt="Мастер"
              className="w-14 h-14 rounded-full object-cover avatar-ring max-md:w-10 max-md:h-10"
              onError={() => setAvatarError(true)}
            />
          ) : (
            <div className="w-14 h-14 rounded-full flex items-center justify-center max-md:w-10 max-md:h-10" style={{ background: 'var(--color-accent-light)', border: '2px solid var(--color-accent)' }}>
              <User size={26} style={{ color: 'var(--color-accent)' }} />
            </div>
          )}
          <div>
            <span className="text-xl font-bold text-white max-md:text-base">{master?.name || 'Мастер'}</span>
          </div>
        </div>

        {/* Month Navigation */}
        <div className="px-6 pt-4 pb-2 flex items-center justify-between">
          <span className="text-sm font-medium tracking-wide" style={{ color: 'var(--color-text-secondary)' }}>{format(currentDate, 'LLLL yyyy', { locale: ru })}</span>
          <div className="flex gap-2">
            <button onClick={() => setCurrentDate(d => new Date(d.getFullYear(), d.getMonth() - 1))} className="p-2 rounded-lg btn-ghost">
              <ChevronLeft size={20} />
            </button>
            <button onClick={() => setCurrentDate(d => new Date(d.getFullYear(), d.getMonth() + 1))} className="p-2 rounded-lg btn-ghost">
              <ChevronRight size={20} />
            </button>
          </div>
        </div>

        {/* Week Days Header */}
        <div className="grid grid-cols-7 divider">
          {weekDays.map(d => (
            <div key={`wd-${d}`} className="text-[11px] font-semibold uppercase tracking-widest py-3 text-center max-md:text-[9px] max-md:py-2" style={{ color: 'var(--color-text-muted)' }}>{d}</div>
          ))}
        </div>

        {/* Days Grid */}
        <div className="flex-1 grid grid-cols-7 max-md:grid-cols-7">
          {/* Empty cells for days before month starts */}
          {Array.from({ length: (monthStart.getDay() + 6) % 7 }).map((_, i) => (
            <div key={`e${i}`} className="border-r border-b max-md:border-r-0" style={{ borderColor: 'var(--color-border-subtle)', background: 'var(--color-surface)' }} />
          ))}
          {days.map(day => {
            const dayStr = format(day, 'yyyy-MM-dd')
            const dayBookings = bookings.filter(b => b.date === dayStr)
            const hasUpcoming = dayBookings.some(b => b.status === 'upcoming')
            const isTodayDate = isToday(day)
            const isSelected = selectedDate && isSameDay(day, selectedDate)
            const bookingDays = master?.schedule?.booking_days || 90
            const maxDate = new Date()
            maxDate.setDate(maxDate.getDate() + bookingDays)
            const isBlocked = day > maxDate

            return (
              <button
                key={dayStr}
                onClick={() => !isBlocked && setSelectedDate(day)}
                disabled={isBlocked}
                className={`
                  flex flex-col items-center justify-center transition-all duration-200 border-r border-b last:border-r-0 max-md:last:border-r max-md:border-r-0
                  ${isSelected ? 'text-white' : ''}
                  ${isTodayDate && !isSelected ? 'font-semibold' : ''}
                  ${isBlocked ? 'opacity-30 cursor-not-allowed' : 'cursor-pointer'}
                `}
                style={{
                  background: isSelected ? 'var(--color-accent)' : isTodayDate ? 'var(--color-accent-light)' : 'var(--color-surface)',
                  color: isSelected ? '#0a0a0a' : isTodayDate ? 'var(--color-accent)' : isBlocked ? 'var(--color-text-muted)' : 'var(--color-text)',
                  borderColor: 'var(--color-border-subtle)'
                }}
              >
                <span className="text-sm max-md:text-xs">{format(day, 'd')}</span>
                {hasUpcoming && (
                  <span className="w-1.5 h-1.5 rounded-full mt-0.5 max-md:w-1 max-md:h-1" style={{ background: isSelected ? '#0a0a0a' : 'var(--color-accent)' }} />
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Bookings Panel - Premium Dark */}
      <div className="w-[360px] card flex flex-col max-md:w-full max-md:max-h-[350px]">
        <div className="p-5 max-md:p-4" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <h3 className="text-lg font-bold max-md:text-base" style={{ color: 'var(--color-text)' }}>
            {selectedDate ? format(selectedDate, 'd MMMM', { locale: ru }) : 'Выберите дату'}
          </h3>
          {selectedDate && (
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              {selectedBookings.length} {selectedBookings.length === 1 ? 'запись' : selectedBookings.length < 5 ? 'записи' : 'записей'}
            </p>
          )}
        </div>

        <div className="flex-1 overflow-y-auto p-5">
          {loading ? (
            <div className="space-y-3">
              {[1, 2, 3].map(i => (
                <div key={i} className="h-20 skeleton rounded-xl" />
              ))}
            </div>
          ) : !selectedDate ? (
            <div className="flex flex-col items-center justify-center h-40 text-center">
              <div className="w-16 h-16 rounded-full flex items-center justify-center mb-4" style={{ background: 'var(--color-surface-elevated)' }}>
                <svg className="w-8 h-8" fill="none" viewBox="0 0 24 24" stroke="currentColor" style={{ color: 'var(--color-text-muted)' }}>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              </div>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Выберите дату в календаре</p>
            </div>
          ) : selectedBookings.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-40 text-center">
              <div className="w-16 h-16 rounded-full flex items-center justify-center mb-4" style={{ background: 'var(--color-accent-light)' }}>
                <Plus size={24} style={{ color: 'var(--color-accent)' }} />
              </div>
              <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>Нет записей</p>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>Нажмите "Добавить" ниже</p>
            </div>
          ) : (
            <div className="space-y-3">
              {selectedBookings.map((booking, idx) => {
                const s = STATUS[booking.status] || STATUS.upcoming
                return (
                  <div key={booking.id} className="card-elevated p-4 animate-fade-slide" style={{ animationDelay: `${idx * 60}ms` }}>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Clock size={14} style={{ color: 'var(--color-text-muted)' }} />
                        <span className="text-sm font-semibold">{booking.time?.slice(0, 5)}</span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs px-2 py-1 rounded-full font-medium badge" style={{ background: s.bg, color: s.text }}>
                          {s.label}
                        </span>
                        {booking.status === 'upcoming' && (
                          <button onClick={() => isDemo ? handleDemoAction('delete') : (async () => {
                            try {
                              const auth = authQuery().replace(/^&/, '?')
                              await fetch(`${API_URL}/api/bookings/${booking.id}${auth}`, {
                                method: 'DELETE',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ cancelled_by: 'master' })
                              })
                              loadBookings()
                            } catch (e) {}
                          })()} className="p-1 rounded hover:bg-red-500/10 transition-colors" style={{ color: 'var(--color-error)' }}>
                            <X size={16} />
                          </button>
                        )}
                        {booking.status === 'cancelled' && (
                          <button onClick={() => handleHardDelete(booking.id)} className="p-1 rounded hover:bg-red-500/10 transition-colors" style={{ color: 'var(--color-error)' }}>
                            <X size={16} />
                          </button>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 mb-1.5">
                      <User size={14} style={{ color: 'var(--color-text-muted)' }} />
                      <span className="text-sm font-medium">{booking.client?.name || 'Клиент'}</span>
                    </div>
                    {booking.client?.phone && (
                      <div className="flex items-center gap-2 mb-1.5">
                        <Phone size={14} style={{ color: 'var(--color-text-muted)' }} />
                        <span className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>{booking.client.phone}</span>
                      </div>
                    )}
                    {booking.client?.telegram_id && (
                      <a
                        href={booking.client?.telegram_profile_url || `tg://user?id=${booking.client.telegram_id}`}
                        className="text-xs font-medium hover:underline"
                        style={{ color: 'var(--color-accent)' }}
                      >
                        Написать клиенту в Telegram
                      </a>
                    )}
                    {booking.service_name && (
                      <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-accent)' }}>
                        {booking.service_name}
                        {booking.duration_minutes && (
                          <span className="ml-1 text-[10px]" style={{ color: 'var(--color-text-muted)' }}>
                            ({booking.duration_minutes} мин)
                          </span>
                        )}
                      </div>
                    )}
                    {!booking.service_name && booking.duration_minutes && (
                      <div className="text-xs font-medium mb-2" style={{ color: 'var(--color-accent)' }}>
                        Длительность: {booking.duration_minutes} мин
                      </div>
                    )}
                    {booking.comment && (
                      <div className="mt-2 p-2 rounded-lg" style={{ background: 'rgba(100, 116, 139, 0.15)' }}>
                        <div className="flex items-center gap-1 mb-1">
                          <span className="text-[10px] font-medium" style={{ color: 'var(--color-text-muted)' }}>Комментарий клиента:</span>
                        </div>
                        <div className="text-xs italic" style={{ color: 'var(--color-text-secondary)' }}>
                          {booking.comment}
                        </div>
                      </div>
                    )}
                    {booking.master_comment && (
                      <div className="mt-2 p-2 rounded-lg" style={{ background: 'rgba(251, 191, 36, 0.1)' }}>
                        <div className="flex items-center gap-1 mb-1">
                          <StickyNote size={10} style={{ color: 'var(--color-warning)' }} />
                          <span className="text-[10px] font-medium" style={{ color: 'var(--color-warning)' }}>Ваша заметка:</span>
                        </div>
                        <div className="text-xs" style={{ color: '#fef3c7' }}>
                          {booking.master_comment}
                        </div>
                      </div>
                    )}
                    {booking.status === 'upcoming' && (
                      <div className="flex gap-4 pt-3 mt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
                        <button onClick={() => isDemo ? handleDemoAction('cancel') : setShowRescheduleModal({ ...booking, mode: 'cancel' })} className="text-xs font-medium hover:underline" style={{ color: 'var(--color-error)' }}>
                          Отменить
                        </button>
                        <button onClick={() => isDemo ? handleDemoAction('reschedule') : setShowRescheduleModal({ ...booking, mode: 'reschedule' })} className="text-xs font-medium hover:underline" style={{ color: 'var(--color-accent)' }}>
                          Перенести
                        </button>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Bottom Navigation */}
        <div className="p-4 flex gap-3" style={{ borderTop: '1px solid var(--color-border)' }}>
          <button onClick={() => isDemo ? handleDemoAction('add') : setShowAddModal(true)} className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-sm btn-primary btn-press">
            <Plus size={18} />
            Добавить
          </button>
          <Link to={`/settings${location.search}`} className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl font-bold text-sm btn-secondary">
            <SettingsIcon size={18} />
            Настройки
          </Link>
        </div>
      </div>

      {/* Demo Add Booking Modal — форма видна, сохранение блокируется */}
      {showDemoAddModal && (
        <AddBookingModal
          services={master?.use_services ? services : []}
          selectedDate={selectedDate}
          onClose={() => setShowDemoAddModal(false)}
          onSubmit={() => {
            setShowDemoAddModal(false)
            setShowDemoMessage('add_block')
            setTimeout(() => setShowDemoMessage(null), 3000)
          }}
          isDemo={true}
        />
      )}

      {/* Reschedule Modal */}
      {showRescheduleModal && (
        <RescheduleModal
          booking={showRescheduleModal}
          services={master?.use_services ? services : []}
          onClose={() => setShowRescheduleModal(null)}
          onSubmit={handleModalSubmit}
        />
      )}

      {/* Add Booking Modal */}
      {showAddModal && (
        <AddBookingModal
          services={master?.use_services ? services : []}
          intervalMinutes={master?.interval_minutes || 60}
          masterId={master?.id}
          selectedDate={selectedDate}
          onClose={() => setShowAddModal(false)}
          onSubmit={handleAddBooking}
        />
      )}
    </div>
  )
}

function RescheduleModal({ booking, services, onClose, onSubmit }) {
  const activeServices = services.filter(service => service.active)
  const [isCancelMode, setIsCancelMode] = useState(booking.mode === 'cancel')
  const [newDate, setNewDate] = useState(booking.date)
  const [newTime, setNewTime] = useState(booking.time?.slice(0, 5) || '')
  const [availableSlots, setAvailableSlots] = useState([])
  const [availableDates, setAvailableDates] = useState({})
  const [calendarMonth, setCalendarMonth] = useState(new Date(`${booking.date}T00:00:00`))
  const [loadingSlots, setLoadingSlots] = useState(false)
  const [loadingDates, setLoadingDates] = useState(false)
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState('')
  const [serviceIds, setServiceIds] = useState((booking.service_ids || []).filter(id => activeServices.some(service => service.id === id)))
  const selectedServices = activeServices.filter(service => serviceIds.includes(service.id))
  const selectedDuration = selectedServices.reduce((sum, service) => sum + service.duration_minutes, 0)
  const duration = selectedDuration || booking.duration_minutes || 60

  async function loadSlots(dateStr) {
    setLoadingSlots(true)
    try {
      const params = new URLSearchParams(window.location.search)
      const endpoint = new URLSearchParams(window.location.search).get('demo') === '1'
        ? `/api/demo/slots?date_str=${dateStr}&duration=${duration}`
        : `/api/${booking.master_id || 1}/slots?date=${dateStr}&duration=${duration}${slotAuthParams()}&exclude_booking_id=${booking.id}`
      const resp = await fetch(`${API_URL}${endpoint}`)
      const data = await resp.json()
      if (data.success) {
        setAvailableSlots(uniqueSlots(data.data.slots))
      }
    } catch {}
    setLoadingSlots(false)
  }

  useEffect(() => {
    if (!isCancelMode) {
      loadSlots(newDate)
    }
  }, [newDate, serviceIds])

  useEffect(() => {
    if (isCancelMode) return
    let cancelled = false
    async function loadDates() {
      setLoadingDates(true)
      try {
        const params = new URLSearchParams(window.location.search)
        const monthStart = startOfMonth(calendarMonth)
        const monthEnd = endOfMonth(calendarMonth)
        const isDemo = new URLSearchParams(window.location.search).get('demo') === '1'
        if (isDemo) {
          const entries = await Promise.all(eachDayOfInterval({ start: monthStart, end: monthEnd }).map(async day => {
            const dateStr = format(day, 'yyyy-MM-dd')
            try {
              const response = await fetch(`${API_URL}/api/demo/slots?date_str=${dateStr}&duration=${duration}`)
              const data = await response.json()
              return [dateStr, Boolean(data?.success && (data.data?.slots || []).some(slot => slot.available))]
            } catch {
              return [dateStr, false]
            }
          }))
          if (!cancelled) setAvailableDates(Object.fromEntries(entries))
        } else {
          const endpoint = `/api/${booking.master_id || 1}/availability?date_from=${format(monthStart, 'yyyy-MM-dd')}` +
            `&date_to=${format(monthEnd, 'yyyy-MM-dd')}&duration=${duration}${slotAuthParams()}&exclude_booking_id=${booking.id}`
          const response = await fetch(`${API_URL}${endpoint}`)
          const data = await response.json()
          if (!cancelled) setAvailableDates(data?.success ? (data.data?.availability || {}) : {})
        }
      } finally {
        if (!cancelled) setLoadingDates(false)
      }
    }
    loadDates()
    return () => { cancelled = true }
  }, [isCancelMode, duration, booking.id, booking.master_id, calendarMonth])

  function handleSubmit(e) {
    e.preventDefault()
    if (isCancelMode) {
      onSubmit(booking, showComment ? comment : '', null, null)
    } else {
      if (!newDate || !newTime) return
      onSubmit(booking, newDate, newTime, showComment ? comment : '', serviceIds.length > 0 ? serviceIds : undefined)
    }
  }

  const isCancel = isCancelMode || booking.mode === 'cancel'
  const hasTelegramClient = Boolean(booking.client?.telegram_id)
  const commentPlaceholder = hasTelegramClient ? 'Комментарий для клиента...' : 'Заметка для себя...'

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 modal-backdrop animate-fade" onClick={onClose}>
      <div className="w-full max-w-md mx-4 max-h-[calc(100dvh-2rem)] overflow-y-auto modal-content animate-scale" onClick={e => e.stopPropagation()}>
        <div className="p-6 pb-4 flex justify-between items-center" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <h3 className="text-xl font-bold">{isCancel ? 'Отменить запись' : 'Перенести запись'}</h3>
          <button onClick={onClose} className="p-2 rounded-lg btn-ghost">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {!isCancel && (
            <>
              {activeServices.length > 0 && (
                <div>
                  <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Услуги</label>
                  <div className="space-y-2">
                    {activeServices.map(service => (
                      <label key={service.id} className="flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={serviceIds.includes(service.id)} onChange={() => {
                          setNewTime('')
                          setServiceIds(serviceIds.includes(service.id) ? serviceIds.filter(id => id !== service.id) : [...serviceIds, service.id])
                        }} />
                        <span>{service.name} ({service.duration_minutes} мин)</span>
                      </label>
                    ))}
                  </div>
                  {serviceIds.length === 0 && booking.service_name && (
                    <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                      Если не выбрать новую услугу, сохранится текущая: {booking.service_name}.
                    </p>
                  )}
                </div>
              )}
              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Новая дата</label>
                <DateAvailabilityCalendar
                  currentMonth={calendarMonth}
                  setCurrentMonth={setCalendarMonth}
                  selectedDate={newDate}
                  onSelectDate={(value) => {
                    setNewTime('')
                    setNewDate(value)
                  }}
                  availableDates={availableDates}
                  loading={loadingDates}
                  minDate={new Date()}
                />
              </div>

              <div>
                <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Время</label>
                {loadingSlots ? (
                  <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Загрузка...</div>
                ) : (
                  <div className="grid grid-cols-4 gap-2 max-h-40 overflow-y-auto pr-2">
                    {availableSlots.map(slot => (
                      <button
                        key={slot.time}
                        type="button"
                        onClick={() => setNewTime(slot.time)}
                        disabled={!slot.available}
                        className={`p-2 rounded-lg text-sm font-medium transition-all ${
                          slot.available
                            ? (newTime === slot.time ? 'btn-primary' : 'btn-secondary')
                            : 'opacity-30 cursor-not-allowed'
                        }`}
                      >
                        {slot.time.slice(0, 5)}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </>
          )}

          {isCancel && (
            <p className="text-sm">
              Запись клиента <span className="font-medium">{booking.client?.name || 'клиента'}</span> на {booking.time?.slice(0, 5)} будет отменена.
            </p>
          )}

          {showComment && (
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value.slice(0, 200))}
              placeholder={commentPlaceholder}
              rows={2}
              maxLength={200}
              className="w-full resize-none"
            />
          )}

          <button type="button" onClick={() => setShowComment(!showComment)} className="text-sm font-medium hover:underline" style={{ color: 'var(--color-accent)' }}>
            {showComment ? '− Скрыть комментарий' : '+ Добавить комментарий'}
          </button>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border font-bold btn-secondary">
              Отмена
            </button>
            <button type="submit" className="flex-1 py-3 rounded-xl font-bold btn-press" style={isCancel ? { background: 'var(--color-error)', color: 'white' } : {}}>
              {isCancel ? 'Отменить' : 'Перенести'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function CancelModal({ booking, onClose, onSubmit }) {
  const [showComment, setShowComment] = useState(false)
  const [comment, setComment] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    onSubmit(booking.id, showComment ? comment : '')
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 modal-backdrop animate-fade" onClick={onClose}>
      <div className="w-full max-w-md mx-4 max-h-[calc(100dvh-2rem)] overflow-y-auto modal-content animate-scale" onClick={e => e.stopPropagation()}>
        <div className="p-6 pb-4 flex justify-between items-center" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <h3 className="text-xl font-bold">Отменить запись</h3>
          <button onClick={onClose} className="p-2 rounded-lg btn-ghost">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          <p className="text-sm">
            Запись клиента <span className="font-medium">{booking.client?.name || 'клиента'}</span> на {booking.time?.slice(0, 5)} будет отменена.
          </p>

          {showComment && (
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value.slice(0, 200))}
              placeholder="Причина отмены..."
              rows={2}
              maxLength={200}
              className="w-full resize-none"
            />
          )}

          <button type="button" onClick={() => setShowComment(!showComment)} className="text-sm font-medium hover:underline" style={{ color: 'var(--color-accent)' }}>
            {showComment ? '− Скрыть заметку' : '+ Добавить заметку'}
          </button>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border font-bold btn-secondary">
              Отмена
            </button>
            <button type="submit" className="flex-1 py-3 rounded-xl font-bold btn-press" style={{ background: 'var(--color-error)', color: 'white' }}>
              Отменить
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function AddBookingModal({ services, selectedDate, onClose, onSubmit, isDemo, intervalMinutes = 60, masterId = 1 }) {
  const activeServices = services.filter(service => service.active)
  const [clientName, setClientName] = useState('')
  const [clientPhone, setClientPhone] = useState('')
  const [serviceIds, setServiceIds] = useState([])
  const [comment, setComment] = useState('')
  const [showComment, setShowComment] = useState(false)
  const [availableSlots, setAvailableSlots] = useState([])
  const [availableDates, setAvailableDates] = useState({})
  const [calendarMonth, setCalendarMonth] = useState(selectedDate || new Date())
  const [loadingDates, setLoadingDates] = useState(false)
  const [selectedTime, setSelectedTime] = useState('')
  const [date, setDate] = useState(selectedDate ? format(selectedDate, 'yyyy-MM-dd') : format(new Date(), 'yyyy-MM-dd'))
  const duration = activeServices.length > 0
    ? activeServices.filter(service => serviceIds.includes(service.id)).reduce((sum, service) => sum + service.duration_minutes, 0)
    : intervalMinutes

  useEffect(() => {
    if (!date || (activeServices.length > 0 && duration === 0)) {
      setAvailableSlots([])
      return
    }
    const params = new URLSearchParams(window.location.search)
    const endpoint = isDemo
      ? `/api/demo/slots?date_str=${date}&duration=${duration}`
      : `/api/${masterId}/slots?date=${date}&duration=${duration}${slotAuthParams()}`
    fetch(`${API_URL}${endpoint}`).then(response => response.json()).then(data => {
      setAvailableSlots(uniqueSlots(data.data?.slots).filter(slot => slot.available))
    }).catch(() => setAvailableSlots([]))
  }, [date, duration, activeServices.length, isDemo, masterId])

  useEffect(() => {
    let cancelled = false
    async function loadDates() {
      if (activeServices.length > 0 && duration === 0) {
        setAvailableDates({})
        return
      }
      setLoadingDates(true)
      try {
        const params = new URLSearchParams(window.location.search)
        const monthStart = startOfMonth(calendarMonth)
        const monthEnd = endOfMonth(calendarMonth)
        if (isDemo) {
          const entries = await Promise.all(eachDayOfInterval({ start: monthStart, end: monthEnd }).map(async day => {
            const dateStr = format(day, 'yyyy-MM-dd')
            try {
              const response = await fetch(`${API_URL}/api/demo/slots?date_str=${dateStr}&duration=${duration}`)
              const data = await response.json()
              return [dateStr, Boolean(data?.success && (data.data?.slots || []).some(slot => slot.available))]
            } catch {
              return [dateStr, false]
            }
          }))
          if (!cancelled) setAvailableDates(Object.fromEntries(entries))
        } else {
          const endpoint = `/api/${masterId}/availability?date_from=${format(monthStart, 'yyyy-MM-dd')}` +
            `&date_to=${format(monthEnd, 'yyyy-MM-dd')}&duration=${duration}${slotAuthParams()}`
          const response = await fetch(`${API_URL}${endpoint}`)
          const data = await response.json()
          if (!cancelled) setAvailableDates(data?.success ? (data.data?.availability || {}) : {})
        }
      } finally {
        if (!cancelled) setLoadingDates(false)
      }
    }
    loadDates()
    return () => { cancelled = true }
  }, [calendarMonth, duration, isDemo, masterId, activeServices.length])

  function handleSubmit(e) {
    e.preventDefault()
    if (!clientName.trim()) {
      alert('Введите имя клиента')
      return
    }
    if (isDemo) {
      onSubmit(null)  // demo — блокируем сохранение
      return
    }

    if (activeServices.length > 0 && serviceIds.length === 0) {
      alert('Выберите хотя бы одну услугу')
      return
    }
    if (!selectedTime) {
      alert('Выберите свободное время')
      return
    }

    onSubmit({
      client_name: clientName,
      client_phone: clientPhone || null,
      service_ids: serviceIds,
      date,
      time: `${selectedTime}:00`,
      master_comment: showComment ? comment : ''
    })
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center z-50 modal-backdrop animate-fade" onClick={onClose}>
      <div className="w-full max-w-md mx-4 max-h-[calc(100dvh-2rem)] overflow-y-auto modal-content animate-scale" onClick={e => e.stopPropagation()}>
        <div className="p-6 pb-4 flex justify-between items-center" style={{ borderBottom: '1px solid var(--color-border)' }}>
          <h3 className="text-xl font-bold">Новая запись</h3>
          <button onClick={onClose} className="p-2 rounded-lg btn-ghost">
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Имя клиента *</label>
            <input
              type="text"
              value={clientName}
              onChange={e => setClientName(e.target.value.slice(0, 50))}
              placeholder="Как зовут клиента"
              maxLength={50}
              className="w-full"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Телефон</label>
            <input
              type="tel"
              value={clientPhone}
              onChange={e => setClientPhone(e.target.value.replace(/[^0-9+\-\s]/g, '').slice(0, 20))}
              placeholder="+7 999 123-45-67"
              className="w-full"
            />
          </div>

          {activeServices.length > 0 && (
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Услуги</label>
              <div className="space-y-2">
                {activeServices.map(service => (
                  <label key={service.id} className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={serviceIds.includes(service.id)} onChange={() => {
                      setSelectedTime('')
                      setServiceIds(serviceIds.includes(service.id) ? serviceIds.filter(id => id !== service.id) : [...serviceIds, service.id])
                    }} />
                    <span>{service.name} ({service.duration_minutes} мин)</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Дата</label>
            <DateAvailabilityCalendar
              currentMonth={calendarMonth}
              setCurrentMonth={setCalendarMonth}
              selectedDate={date}
              onSelectDate={(value) => {
                setSelectedTime('')
                setDate(value)
              }}
              availableDates={availableDates}
              loading={loadingDates}
              minDate={new Date()}
            />
          </div>

          <div>
            <label className="block text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-muted)' }}>Свободное время</label>
            <div className="grid grid-cols-4 gap-2">
              {availableSlots.map(slot => (
                <button type="button" key={slot.time} onClick={() => setSelectedTime(slot.time.slice(0, 5))} className={selectedTime === slot.time.slice(0, 5) ? 'btn-primary p-2 rounded-lg text-sm' : 'btn-secondary p-2 rounded-lg text-sm'}>
                  {slot.time.slice(0, 5)}
                </button>
              ))}
            </div>
            {availableSlots.length === 0 && <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{activeServices.length > 0 && serviceIds.length === 0 ? 'Сначала выберите хотя бы одну услугу, затем дату.' : 'На выбранную дату свободного времени нет.'}</p>}
          </div>

          {showComment && (
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              placeholder="Заметка для себя..."
              rows={2}
              className="w-full resize-none"
            />
          )}

          <button type="button" onClick={() => setShowComment(!showComment)} className="text-sm font-medium hover:underline" style={{ color: 'var(--color-accent)' }}>
            {showComment ? '− Скрыть заметку' : '+ Добавить заметку'}
          </button>

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 py-3 rounded-xl border font-bold btn-secondary">
              Отмена
            </button>
            <button type="submit" className="flex-1 py-3 rounded-xl font-bold btn-primary btn-press">
              Добавить
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
