import { useState, useEffect, useRef } from 'react'
import { format, startOfMonth, eachDayOfInterval, isToday, addMonths, subMonths } from 'date-fns'
import { ru } from 'date-fns/locale'
import { Check } from 'lucide-react'
import { resolveMediaUrl } from '../utils/media'

const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')

const weekDays = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ', 'СБ', 'ВС']

function AvailabilityCalendar({ currentMonth, setCurrentMonth, selectedDate, onSelectDate, availableDates, loading, minDate }) {
  const monthStart = startOfMonth(currentMonth)
  const monthEnd = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0)
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd })
  const leadingDays = (monthStart.getDay() + 6) % 7

  return (
    <div className="mb-4">
      <div className="flex items-center justify-between mb-3">
        <button type="button" onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="px-3 py-2 rounded-lg border" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>‹</button>
        <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{format(currentMonth, 'LLLL yyyy', { locale: ru })}</div>
        <button type="button" onClick={() => setCurrentMonth(addMonths(currentMonth, 1))} className="px-3 py-2 rounded-lg border" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>›</button>
      </div>
      <div className="grid grid-cols-7 gap-1">
        {weekDays.map(day => <div key={day} className="text-center text-[11px] py-1" style={{ color: 'var(--color-text-muted)' }}>{day}</div>)}
        {Array.from({ length: leadingDays }).map((_, index) => <div key={`leading-${index}`} />)}
        {days.map(day => {
          const dateStr = format(day, 'yyyy-MM-dd')
          const available = availableDates[dateStr] === true
          const known = Object.prototype.hasOwnProperty.call(availableDates, dateStr)
          const disabled = day < minDate || (known && !available)
          const selected = selectedDate === dateStr
          return (
            <button
              key={dateStr}
              type="button"
              onClick={() => !disabled && onSelectDate(dateStr)}
              disabled={disabled}
              className="aspect-square rounded-lg text-sm font-medium border"
              style={{
                borderColor: selected ? 'var(--color-accent)' : 'var(--color-border)',
                backgroundColor: selected ? 'var(--color-accent)' : 'var(--color-surface-elevated)',
                color: selected ? '#fff' : disabled ? 'var(--color-text-muted)' : 'var(--color-text)',
                opacity: disabled ? 0.38 : (known || loading ? 1 : 0.7),
              }}
            >
              {format(day, 'd')}
            </button>
          )
        })}
      </div>
      <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
        {loading ? 'Проверяем доступные даты...' : 'Блеклые даты недоступны для переноса.'}
      </p>
    </div>
  )
}

function isScheduleDateExcluded(date, schedule) {
  const dateStr = format(date, 'yyyy-MM-dd')
  return (schedule?.exceptions || []).some(item => {
    if (typeof item === 'string') return item === dateStr
    const start = item.start || item.date
    const end = item.end || start
    return start && end && start <= dateStr && dateStr <= end
  })
}

function isDemoMode() {
  return new URLSearchParams(window.location.search).get('demo') === '1'
}

function friendlyErrorMessage(message) {
  const messages = {
    NOT_FOUND: 'Ссылка записи недоступна. В боте ещё раз нажмите /start и получите актуальную ссылку.',
    SERVICE_NOT_FOUND: 'Эта услуга больше недоступна. Обновите страницу и выберите другую услугу.',
    'Failed to fetch': 'Не удалось связаться с сервером. Проверьте интернет-соединение и попробуйте ещё раз.',
  }
  return messages[message] || message || 'Не удалось выполнить запрос. Попробуйте ещё раз.'
}

// Ссылка устарела/недействительна — бэкенд просит заново открыть бота и нажать «Старт».
function isExpiredLinkMessage(message) {
  return typeof message === 'string' && (message.includes('нажмите «Старт»') || message.includes('устарел'))
}

async function api(endpoint, options = {}) {
  let response
  const attempts = options.method && options.method !== 'GET' ? 1 : 2
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    try {
      response = await fetch(`${API_URL}${endpoint}`, {
        ...options,
      })
      break
    } catch (error) {
      if (attempt === attempts - 1) throw error
      await new Promise(resolve => setTimeout(resolve, 350))
    }
  }
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(response.ok ? 'Некорректный ответ сервера' : `Ошибка сервера ${response.status}: ${text || response.statusText}`)
  }
  if (!response.ok || !data.success) {
    const detail = data?.detail
    throw new Error(friendlyErrorMessage((typeof detail === 'string' ? detail : null) || data?.error?.message))
  }
  return data.data
}

async function mapWithConcurrency(items, limit, mapper) {
  const results = new Array(items.length)
  let nextIndex = 0
  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      results[index] = await mapper(items[index], index)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

async function readApiResponse(response) {
  const text = await response.text()
  let data = null
  try {
    data = text ? JSON.parse(text) : null
  } catch {
    throw new Error(response.ok ? 'Некорректный ответ сервера' : `Ошибка сервера ${response.status}: ${text || response.statusText}`)
  }
  if (!response.ok || !data?.success) {
    const detail = data?.detail
    throw new Error(friendlyErrorMessage((typeof detail === 'string' ? detail : null) || data?.error?.message || 'Ошибка записи'))
  }
  return data.data
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

export default function ClientBook() {
  const [master, setMaster] = useState(null)
  const [services, setServices] = useState([])
  const [currentMonth, setCurrentMonth] = useState(new Date())
  const [selectedDate, setSelectedDate] = useState(null)
  const [slots, setSlots] = useState([])
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState(null)
  const [tgUser, setTgUser] = useState(null)
  const [masterId, setMasterId] = useState(1)
  const [masterBotId, setMasterBotId] = useState(null)
  const [vkBotId, setVkBotId] = useState(null)
  const [telegramInitData, setTelegramInitData] = useState('')
  const [clientSig, setClientSig] = useState('')
  const [authTs, setAuthTs] = useState('')
  const [vkUser, setVkUser] = useState('')
  const [vkSig, setVkSig] = useState('')
  const [clientBookings, setClientBookings] = useState([])
  const [actionBooking, setActionBooking] = useState(null)
  const [actionMode, setActionMode] = useState(null)
  const [actionComment, setActionComment] = useState('')
  const [actionDate, setActionDate] = useState('')
  const [actionSlots, setActionSlots] = useState([])
  const [actionTime, setActionTime] = useState('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionServices, setActionServices] = useState([])
  const [actionMonth, setActionMonth] = useState(new Date())
  const [actionAvailableDates, setActionAvailableDates] = useState({})
  const [availableDates, setAvailableDates] = useState({})
  const [avatarError, setAvatarError] = useState(false)

  // Dialog state
  const [bookingStep, setBookingStep] = useState(null) // 'service' | 'comment' | null
  const [selectedServices, setSelectedServices] = useState([]) // Multiple services
  const [selectedSlot, setSelectedSlot] = useState(null)
  const [comment, setComment] = useState('')

  // Calculate total duration of selected services
  const activeServices = services.filter(service => service.active)
  const totalDuration = selectedServices.reduce((sum, s) => sum + (s.duration_minutes || 60), 0)
  const useServices = master?.use_services && activeServices.length > 0
  const actionDuration = actionBooking
    ? (useServices
      ? actionServices.reduce((sum, service) => sum + (service.duration_minutes || 0), 0) || actionBooking.duration_minutes || master?.interval_minutes || 60
      : actionBooking.duration_minutes || master?.interval_minutes || 60)
    : 0

  useEffect(() => {
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp.initDataUnsafe?.user
      if (tg) setTgUser(tg)
      const initData = window.Telegram.WebApp.initData || ''
      setTelegramInitData(initData)
      window.Telegram.WebApp.expand()
    }
    const params = new URLSearchParams(window.location.search)
    const userParam = params.get('user')
    setClientSig(params.get('client_sig') || '')
    setAuthTs(params.get('auth_ts') || '')
    const resolvedBotId = params.get('bot_id') ? parseInt(params.get('bot_id'), 10) : null
    const resolvedVkBotId = params.get('vk_bot_id') ? parseInt(params.get('vk_bot_id'), 10) : null
    setMasterBotId(resolvedBotId)
    setVkBotId(resolvedVkBotId)
    const usernameParam = params.get('username')
    const nameParam = params.get('name')
    // Клиент из бота ВКонтакте: авторизация по VK ID.
    const vkUserParam = params.get('vk_user')
    const vkSigParam = params.get('vk_sig')
    if (vkUserParam) {
      setVkUser(vkUserParam)
      setVkSig(vkSigParam || '')
      setTgUser({ id: parseInt(vkUserParam, 10), username: null, first_name: nameParam || 'Клиент', is_vk: true })
    } else if (userParam) {
      setTgUser({
        id: parseInt(userParam, 10),
        username: usernameParam || null,
        first_name: nameParam || 'Клиент'
      })
    }
    const masterParam = parseInt(params.get('master_id') || '1', 10)
    const resolvedMasterId = Number.isFinite(masterParam) && masterParam > 0 ? masterParam : 1
    setMasterId(resolvedMasterId)
    initPage(resolvedMasterId, resolvedBotId, resolvedVkBotId)
  }, [])

  useEffect(() => {
    if (!isDemoMode() && masterId && tgUser?.id && (telegramInitData || clientSig || vkSig)) {
      loadClientBookings()
    }
  }, [masterId, masterBotId, vkBotId, tgUser?.id, telegramInitData, clientSig, vkSig])

  function clientAuthPayload() {
    if (vkUser) {
      return {
        master_id: masterId,
        vk_user: vkUser,
        vk_sig: vkSig || null,
        auth_ts: authTs || null,
      }
    }
    return {
      master_id: masterId,
      master_bot_id: masterBotId,
      telegram_user_id: tgUser?.id || null,
      client_sig: clientSig || null,
      auth_ts: authTs || null,
      telegram_init_data: telegramInitData || null,
    }
  }

  async function loadClientBookings() {
    if (isDemoMode() || !tgUser?.id || (!telegramInitData && !clientSig && !vkSig)) return
    const params = new URLSearchParams({
      master_id: String(masterId),
    })
    if (vkUser) {
      params.set('vk_user', String(vkUser))
      if (vkSig) params.set('vk_sig', vkSig)
      if (authTs) params.set('auth_ts', authTs)
      try {
        const data = await api(`/api/bookings/client?${params}`)
        setClientBookings(data.bookings || [])
      } catch (e) {
        if (isExpiredLinkMessage(e?.message)) setError(e.message)
        console.log('Client bookings are unavailable:', e.message)
      }
      return
    }
    params.set('telegram_user_id', String(tgUser.id))
    if (clientSig) params.set('client_sig', clientSig)
    if (authTs) params.set('auth_ts', authTs)
    if (masterBotId) params.set('master_bot_id', String(masterBotId))
    if (telegramInitData) params.set('telegram_init_data', telegramInitData)
    try {
      const data = await api(`/api/bookings/client?${params}`)
      setClientBookings(data.bookings || [])
    } catch (e) {
      if (isExpiredLinkMessage(e?.message)) setError(e.message)
      console.log('Client bookings are unavailable:', e.message)
    }
  }

  function botAccessQuery(resolvedBotId = masterBotId, resolvedVkBotId = vkBotId) {
    const params = new URLSearchParams()
    const sourceParams = new URLSearchParams(window.location.search)
    if (resolvedBotId) params.set('bot_id', String(resolvedBotId))
    if (resolvedVkBotId) params.set('vk_bot_id', String(resolvedVkBotId))
    ;['vk_user', 'vk_sig', 'auth_ts'].forEach(key => {
      const value = sourceParams.get(key)
      if (value) params.set(key, value)
    })
    return params.toString()
  }

  async function initPage(
    resolvedMasterId = masterId,
    resolvedBotId = masterBotId,
    resolvedVkBotId = vkBotId,
  ) {
    try {
      const access = botAccessQuery(resolvedBotId, resolvedVkBotId)
      const botQuery = access ? `?${access}` : ''
      const m = await api(isDemoMode() ? '/api/demo/master' : `/api/${resolvedMasterId}${botQuery}`)
      setMaster(m)
      const s = await api(isDemoMode() ? '/api/demo/services' : `/api/${resolvedMasterId}/services${botQuery}`)
      setServices(s.services || [])
      const today = new Date()
      setCurrentMonth(today)
      handleDateSelect(null) // Initial load without date selection
    } catch (e) {
      setError(friendlyErrorMessage(e.message))
    } finally {
      setLoading(false)
    }
  }

  async function refreshServices() {
    try {
      const access = botAccessQuery()
      const botQuery = access ? `?${access}` : ''
      const data = await api(isDemoMode() ? '/api/demo/services' : `/api/${masterId}/services${botQuery}`)
      const freshServices = data.services || []
      const activeIds = new Set(freshServices.filter(service => service.active).map(service => service.id))
      setServices(freshServices)
      setSelectedServices(current => current.filter(service => activeIds.has(service.id)))
    } catch (e) {
      console.log('Service refresh failed:', e.message)
    }
  }

  useEffect(() => {
    const handlePageReturn = () => {
      if (document.visibilityState === 'visible') refreshServices()
    }
    window.addEventListener('focus', handlePageReturn)
    document.addEventListener('visibilitychange', handlePageReturn)
    return () => {
      window.removeEventListener('focus', handlePageReturn)
      document.removeEventListener('visibilitychange', handlePageReturn)
    }
  }, [masterId, masterBotId, vkBotId])

  async function handleDateSelect(date) {
    // If no date selected or same date, clear selection
    if (!date) {
      setSelectedDate(null)
      setSlots([])
      return
    }

    const dateStr = format(date, 'yyyy-MM-dd')
    if (selectedDate && format(selectedDate, 'yyyy-MM-dd') === dateStr && slots.length > 0) {
      return
    }

    setSelectedDate(date)
    setSelectedSlot(null)
    setLoading(true)

    try {
      if (useServices && totalDuration === 0) {
        setError('Сначала выберите хотя бы одну услугу')
        return
      }
      const duration = useServices ? totalDuration : (master?.interval_minutes || 60)
      const access = botAccessQuery()
      const data = await api(isDemoMode()
        ? `/api/demo/slots?date_str=${dateStr}&duration=${duration}`
        : `/api/${masterId}/slots?date=${dateStr}&duration=${duration}&${access}`)
      setSlots(uniqueSlots(data.slots))
    } catch {
      setSlots([])
    } finally {
      setLoading(false)
    }
  }

  async function handleSlotSelect(slot) {
    setSelectedSlot(slot)

    const useServices = master?.use_services && services.some(s => s.active)
    if (!isDemoMode() && !master?.is_demo && !telegramInitData && !clientSig && !vkSig) {
      setError('Для записи откройте эту страницу кнопкой «Записаться» в боте мастера.')
      return
    }

    if (useServices && selectedServices.length === 0) {
      setError('Сначала выберите хотя бы одну услугу')
      return
    }
    setBookingStep('comment')
  }

  async function handleServiceConfirm() {
    if (selectedServices.length === 0) return

    setError(null)
    setBookingStep('comment')
  }

  function handleBookInline() {
    if (submittingRef.current) return
    if (isDemoMode() || master?.is_demo) {
      setSuccess(true)
      setBookingStep(null)
      return
    }
    if (!selectedDate || !selectedSlot) {
      console.log('handleBook: Missing date or slot', { selectedDate, selectedSlot })
      setError('Пожалуйста, выберите дату и время')
      return
    }
    if (!telegramInitData && !clientSig && !vkSig) {
      setError('Откройте запись кнопкой из бота мастера')
      return
    }
    if (useServices && selectedServices.length === 0) {
      setError('Выберите хотя бы одну услугу')
      return
    }

    submittingRef.current = true
    setSubmitting(true)
    setError(null)

    const payload = {
      ...clientAuthPayload(),
      master_bot_id: masterBotId,
      service_ids: selectedServices.map(s => s.id),
      service_names: selectedServices.map(s => s.name).join(' + '),
      date: format(selectedDate, 'yyyy-MM-dd'),
      time: `${selectedSlot.time}:00`,
      comment: comment || null,
    }

    console.log('handleBook: Sending payload', payload)
    setError(null)
    fetch(`${API_URL}/api/bookings`, {
      method: 'POST',
      body: JSON.stringify(payload),
      headers: { 'Content-Type': 'application/json' },
    })
      .then(readApiResponse)
      .then(data => {
        console.log('handleBook: Response', data)
        setBookingStep(null)
        setSuccess(true)
        loadClientBookings()
      })
      .catch(e => {
        console.log('handleBook: Error', e.message)
        setError('Ошибка записи: ' + friendlyErrorMessage(e.message))
      })
      .finally(() => {
        submittingRef.current = false
        setSubmitting(false)
      })
  }

  // Подстраховка для Telegram WebView, где обычный onClick иногда не срабатывает.
  // Привязан строго к кнопке записи (data-booking-submit), а не к любому тексту
  // «Записаться» — иначе мог случайно сработать на других кнопках.
  useEffect(() => {
    const handleGlobalClick = (e) => {
      const target = e.target.closest('button')
      if (target && target.dataset?.bookingSubmit === 'true' && !target.disabled) {
        if (isDemoMode() || master?.is_demo) {
          e.preventDefault()
          e.stopPropagation()
          setSuccess(true)
          setBookingStep(null)
          return
        }
        e.preventDefault()
        e.stopPropagation()
        handleBookInline()
      }
    }
    document.addEventListener('click', handleGlobalClick, true)
    return () => document.removeEventListener('click', handleGlobalClick, true)
  }, [selectedDate, selectedSlot, selectedServices, tgUser, comment, master, telegramInitData, clientSig])

  async function handleBook() {
    handleBookInline()
  }

  function closeDialog() {
    setBookingStep(null)
    // Keep selectedSlot and selectedDate - go back to same time
  }

  function openBookingAction(booking, mode) {
    setActionBooking(booking)
    setActionMode(mode)
    setActionComment('')
    setActionDate('')
    setActionSlots([])
    setActionTime('')
    setActionServices(activeServices.filter(service => (booking.service_ids || []).includes(service.id)))
    setActionMonth(new Date(`${booking.date}T00:00:00`))
    setActionAvailableDates({})
  }

  function closeBookingAction() {
    setActionBooking(null)
    setActionMode(null)
    setActionComment('')
    setActionDate('')
    setActionSlots([])
    setActionTime('')
    setActionServices([])
  }

  async function loadRescheduleSlots(dateValue) {
    setActionDate(dateValue)
    setActionTime('')
    if (!dateValue || !actionBooking) return setActionSlots([])
    setActionLoading(true)
    try {
      if (!actionDuration) return setActionSlots([])
      const data = await api(`/api/${masterId}/slots?date=${dateValue}&duration=${actionDuration}&${botAccessQuery()}&exclude_booking_id=${actionBooking.id}`)
      setActionSlots(uniqueSlots(data.slots).filter(slot => slot.available))
    } catch (e) {
      setActionSlots([])
      setError(friendlyErrorMessage(e.message))
    } finally {
      setActionLoading(false)
    }
  }

  async function submitBookingAction() {
    if (!actionBooking) return
    if (actionMode === 'reschedule' && (!actionDate || !actionTime)) {
      setError('Выберите новую дату и время')
      return
    }
    setActionLoading(true)
    setError(null)
    try {
      const payload = {
        ...clientAuthPayload(),
        comment: actionComment || null,
        ...(actionMode === 'reschedule' ? { new_date: actionDate, new_time: actionTime } : {}),
      }
      if (actionMode === 'reschedule' && actionServices.length > 0) {
        payload.service_ids = actionServices.map(service => service.id)
      }
      await api(`/api/bookings/client/${actionBooking.id}/${actionMode === 'cancel' ? 'cancel' : 'reschedule'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      closeBookingAction()
      await loadClientBookings()
    } catch (e) {
      setError(friendlyErrorMessage(e.message))
    } finally {
      setActionLoading(false)
    }
  }

  useEffect(() => {
    if (!master || !useServices || totalDuration === 0) {
      setAvailableDates({})
      return
    }
    let cancelled = false
    const monthStart = startOfMonth(currentMonth)
    const monthEnd = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0)
    const monthDays = eachDayOfInterval({ start: monthStart, end: monthEnd })
    if (isDemoMode()) {
      mapWithConcurrency(monthDays, 4, async day => {
        const dateStr = format(day, 'yyyy-MM-dd')
        try {
          const data = await api(`/api/demo/slots?date_str=${dateStr}&duration=${totalDuration}`)
          return [dateStr, (data.slots || []).some(slot => slot.available)]
        } catch {
          return [dateStr, null]
        }
      }).then(entries => {
        if (!cancelled) setAvailableDates(Object.fromEntries(entries))
      })
    } else {
      const dateFrom = format(monthStart, 'yyyy-MM-dd')
      const dateTo = format(monthEnd, 'yyyy-MM-dd')
      api(`/api/${masterId}/availability?date_from=${dateFrom}&date_to=${dateTo}&duration=${totalDuration}&${botAccessQuery()}`)
        .then(data => {
          if (!cancelled) setAvailableDates(data.availability || {})
        })
        .catch(() => {
          if (!cancelled) setAvailableDates({})
        })
    }
    return () => { cancelled = true }
  }, [master, useServices, totalDuration, currentMonth, masterId, masterBotId, vkBotId])

  useEffect(() => {
    if (actionDate && actionBooking && actionMode === 'reschedule') loadRescheduleSlots(actionDate)
  }, [actionServices])

  useEffect(() => {
    if (!actionBooking || actionMode !== 'reschedule') return
    let cancelled = false
    async function loadActionDates() {
      if (!actionDuration) {
        setActionAvailableDates({})
        return
      }
      setActionLoading(true)
      try {
        const monthStart = startOfMonth(actionMonth)
        const monthEnd = new Date(actionMonth.getFullYear(), actionMonth.getMonth() + 1, 0)
        const dateFrom = format(monthStart, 'yyyy-MM-dd')
        const dateTo = format(monthEnd, 'yyyy-MM-dd')
        const data = await api(
          `/api/${masterId}/availability?date_from=${dateFrom}&date_to=${dateTo}&duration=${actionDuration}` +
          `&${botAccessQuery()}&exclude_booking_id=${actionBooking.id}`
        )
        if (!cancelled) setActionAvailableDates(data.availability || {})
      } finally {
        if (!cancelled) setActionLoading(false)
      }
    }
    loadActionDates()
    return () => { cancelled = true }
  }, [actionBooking, actionMode, actionMonth, actionDuration, masterId, masterBotId, vkBotId])

  if (loading && !master) {
    return (
      <div className="min-h-screen flex items-center justify-center" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="text-center">
          <div className="w-12 h-12 border-4 rounded-full border-t-transparent animate-spin mx-auto mb-4" style={{ borderColor: 'var(--color-accent)', borderTopColor: 'transparent' }} />
          <p style={{ color: 'var(--color-text-secondary)' }}>Загрузка...</p>
        </div>
      </div>
    )
  }

  if (isExpiredLinkMessage(error)) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="card w-full max-w-md rounded-2xl p-6 text-center">
          <div className="text-4xl mb-3">🔗</div>
          <h1 className="text-xl font-bold">Ссылка больше не актуальна</h1>
          <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
            Откройте бота мастера в Telegram и нажмите «Старт» (/start) — бот пришлёт свежую ссылку,
            чтобы зайти и записаться.
          </p>
        </div>
      </div>
    )
  }

  if (error && !master) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="card w-full max-w-md rounded-2xl p-6 text-center">
          <h1 className="text-xl font-bold">Запись недоступна</h1>
          <p className="mt-3 text-sm leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>{error}</p>
        </div>
      </div>
    )
  }

  if (success) {
    return (
      <div className="min-h-screen flex items-center justify-center px-4" style={{ backgroundColor: 'var(--color-bg)' }}>
        <div className="text-center max-w-md">
          <div className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-6" style={{ backgroundColor: 'rgba(74, 222, 128, 0.1)' }}>
            <Check size={40} style={{ color: 'var(--color-success)' }} />
          </div>
          <h1 className="text-2xl font-bold mb-2" style={{ color: 'var(--color-text)' }}>Вы записаны!</h1>
          <p style={{ color: 'var(--color-text-secondary)' }}>
            {selectedDate && format(selectedDate, 'd MMMM', { locale: ru })} в {selectedSlot?.time?.slice(0, 5)}
          </p>
          {selectedServices.length > 0 && (
            <div className="mt-2">
              {selectedServices.map(s => (
                <p key={s.id} className="font-medium" style={{ color: 'var(--color-accent)' }}>{s.name}</p>
              ))}
              {totalDuration > 0 && (
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Всего: {totalDuration} мин</p>
              )}
            </div>
          )}
          {comment && (
            <p className="mt-2 text-sm" style={{ color: 'var(--color-text-muted)' }}>
              "{comment}"
            </p>
          )}
          <button
            onClick={() => {
              setSuccess(false)
              setBookingStep(null)
              setComment('')
              setSelectedServices([])
              setSelectedSlot(null)
              setSelectedDate(null)
              setSlots([])
              loadClientBookings()
            }}
            className="mt-6 px-5 py-3 rounded-xl font-bold"
            style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
          >
            Вернуться к моим записям
          </button>
        </div>
      </div>
    )
  }

  const monthStart = startOfMonth(currentMonth)
  const monthEnd = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + 1, 0)
  const days = eachDayOfInterval({ start: monthStart, end: monthEnd })
  const leadingDays = (monthStart.getDay() + 6) % 7

  const availableSlots = slots.filter(s => s.available)
  // Get avatar URL
  const avatarUrl = master?.avatar_url
    ? resolveMediaUrl(master.avatar_url)
    : null

  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--color-bg)' }}>
      <div className="max-w-md mx-auto px-4 py-8 flex flex-col">
        {/* Header with Avatar */}
        <div className="flex items-center gap-4 mb-6">
          {avatarUrl && !avatarError ? (
            <img src={avatarUrl} alt={master?.name} className="w-16 h-16 rounded-full object-cover" onError={() => setAvatarError(true)} />
          ) : (
            <div className="w-16 h-16 rounded-full flex items-center justify-center" style={{ backgroundColor: 'var(--color-accent-light)' }}>
              <span className="text-2xl font-bold" style={{ color: 'var(--color-accent)' }}>
                {master?.name?.charAt(0) || 'М'}
              </span>
            </div>
          )}
          <div>
            <h1 className="text-xl font-bold" style={{ color: 'var(--color-text)' }}>
              {master?.name || 'Мастер'}
            </h1>
            <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Запись на услуги</p>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-3 rounded-lg text-sm" style={{ backgroundColor: 'rgba(248, 113, 113, 0.1)', color: 'var(--color-error)' }}>
            {error}
          </div>
        )}

        {clientBookings.length > 0 && (
          <div className="mb-5 rounded-2xl p-4" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h2 className="font-bold mb-1" style={{ color: 'var(--color-text)' }}>Ваши записи</h2>
            <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>Здесь можно перенести или отменить визит</p>
            <div className="space-y-3">
              {clientBookings.map(booking => (
                <div key={booking.id} className="p-3 rounded-xl" style={{ backgroundColor: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                  <div className="flex justify-between gap-3">
                    <div>
                      <p className="font-bold" style={{ color: 'var(--color-text)' }}>
                        {format(new Date(`${booking.date}T00:00:00`), 'd MMMM', { locale: ru })} в {booking.time.slice(0, 5)}
                      </p>
                      <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{booking.duration_minutes} мин</p>
                    </div>
                    <span className="text-xs" style={{ color: 'var(--color-success)' }}>Запланировано</span>
                  </div>
                  {master?.use_services && booking.service_name && (
                    <p className="text-sm mt-2" style={{ color: 'var(--color-accent)' }}>{booking.service_name}</p>
                  )}
                  {booking.comment && (
                    <p className="text-xs mt-2" style={{ color: 'var(--color-text-muted)' }}>Комментарий: {booking.comment}</p>
                  )}
                  <div className="flex gap-2 mt-3">
                    <button onClick={() => openBookingAction(booking, 'reschedule')} className="flex-1 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: 'var(--color-accent-light)', color: 'var(--color-accent)' }}>Перенести</button>
                    <button onClick={() => openBookingAction(booking, 'cancel')} className="flex-1 py-2 rounded-lg text-sm font-medium" style={{ backgroundColor: 'rgba(248, 113, 113, 0.1)', color: 'var(--color-error)' }}>Отменить</button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Calendar Card */}
        <div className="order-3 rounded-2xl overflow-hidden min-h-[420px] flex flex-col" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
          {/* Calendar Header */}
          <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
            <button onClick={() => setCurrentMonth(subMonths(currentMonth, 1))} className="p-2 rounded-lg hover:bg-gray-100 transition-colors">
              ‹
            </button>
            <span className="font-semibold">{format(currentMonth, 'LLLL yyyy', { locale: ru })}</span>
            <button onClick={() => setCurrentMonth(addMonths(currentMonth, 1))} className="p-2 rounded-lg hover:bg-gray-100 transition-colors">
              ›
            </button>
          </div>

          {/* Week days */}
          <div className="grid grid-cols-7 py-3" style={{ borderBottom: '1px solid var(--color-border)' }}>
            {weekDays.map(day => (
              <div key={day} className="text-xs font-semibold uppercase py-2 text-center tracking-wide" style={{ color: 'var(--color-text-muted)' }}>
                {day}
              </div>
            ))}
          </div>

          {/* Hint when services are required but not selected */}
          {useServices && totalDuration === 0 && (
            <div className="px-4 py-2 text-center text-sm" style={{ color: 'var(--color-text-muted)' }}>
              Сначала выберите услугу — тогда откроются доступные даты
            </div>
          )}

          {/* Days grid */}
          <div className="grid grid-cols-7">
            {Array.from({ length: leadingDays }).map((_, i) => (
              <div key={`empty-${i}`} className="aspect-square" />
            ))}
            {days.map(day => {
              const isPast = day < new Date() && !isToday(day)
              const isSelected = selectedDate && format(selectedDate, 'yyyy-MM-dd') === format(day, 'yyyy-MM-dd')
              const bookingDays = master?.schedule?.booking_days || 90
              const maxDate = new Date()
              maxDate.setDate(maxDate.getDate() + bookingDays)
              const isBlocked = day > maxDate || isScheduleDateExcluded(day, master?.schedule)
              const dateStr = format(day, 'yyyy-MM-dd')
              const hasRequiredSlot = !useServices || (totalDuration > 0 && availableDates[dateStr] !== false)
              const isUnavailable = isBlocked || !hasRequiredSlot
              return (
                <button
                  key={day.toISOString()}
                  onClick={() => !isPast && !isUnavailable && handleDateSelect(day)}
                  disabled={isPast || isUnavailable}
                  className="aspect-square flex flex-col items-center justify-center text-base transition-all relative font-medium"
                  style={{
                    color: isPast ? 'var(--color-text-muted)' : isUnavailable ? 'var(--color-text-muted)' : isSelected ? '#fff' : 'var(--color-text)',
                    backgroundColor: isSelected ? 'var(--color-accent)' : 'transparent',
                    fontWeight: isToday(day) ? 'bold' : 'normal',
                    opacity: isUnavailable ? 0.4 : 1
                  }}
                >
                  <span className="text-base">{format(day, 'd')}</span>
                  {isToday(day) && !isSelected && (
                    <span className="w-1 h-1 rounded-full absolute bottom-1" style={{ backgroundColor: 'var(--color-accent)' }} />
                  )}
                </button>
              )
            })}
          </div>
        </div>

        {useServices && (
          <div className="order-2 mb-4 rounded-2xl p-4" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <h2 className="font-bold mb-1" style={{ color: 'var(--color-text)' }}>Выберите услуги</h2>
            <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>После выбора календарь покажет только даты, где есть подходящее окно.</p>
            <div className="space-y-2">
              {services.filter(service => service.active).map(service => {
                const isSelected = selectedServices.some(item => item.id === service.id)
                return (
                  <button key={service.id} type="button" onClick={() => {
                    setSelectedServices(isSelected ? selectedServices.filter(item => item.id !== service.id) : [...selectedServices, service])
                    setSelectedDate(null)
                    setSelectedSlot(null)
                    setSlots([])
                  }} className="w-full p-3 rounded-xl border text-left flex justify-between gap-3" style={{ backgroundColor: isSelected ? 'var(--color-accent-light)' : 'var(--color-bg)', borderColor: isSelected ? 'var(--color-accent)' : 'var(--color-border)' }}>
                    <span style={{ color: 'var(--color-text)' }}>{isSelected ? '✓ ' : ''}{service.name}</span>
                    <span className="text-sm whitespace-nowrap" style={{ color: 'var(--color-text-muted)' }}>{service.duration_minutes} мин</span>
                  </button>
                )
              })}
            </div>
            {totalDuration > 0 && <p className="mt-3 text-sm font-medium" style={{ color: 'var(--color-accent)' }}>Общая длительность: {totalDuration} мин</p>}
          </div>
        )}

        {/* Time Slots */}
        {selectedDate && (
          <div className="order-4 mt-4 rounded-2xl p-4" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
            <p className="text-sm font-medium mb-3" style={{ color: 'var(--color-text)' }}>
              {format(selectedDate, 'EEEE, d MMMM', { locale: ru })}
            </p>

            {loading ? (
              <div className="grid grid-cols-4 gap-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="h-10 skeleton rounded-lg" />
                ))}
              </div>
            ) : availableSlots.length > 0 ? (
              <div className="grid grid-cols-4 gap-2">
                {availableSlots.map(slot => (
                  <button
                    key={slot.time}
                    onClick={() => handleSlotSelect(slot)}
                    className="py-2 px-3 rounded-lg border text-sm font-medium transition-all"
                    style={{
                      backgroundColor: selectedSlot?.time === slot.time ? 'var(--color-accent)' : 'transparent',
                      borderColor: selectedSlot?.time === slot.time ? 'var(--color-accent)' : 'var(--color-border)',
                      color: selectedSlot?.time === slot.time ? '#fff' : 'var(--color-text)',
                    }}
                  >
                    {slot.time.slice(0, 5)}
                  </button>
                ))}
              </div>
            ) : (
              <p className="text-sm text-center py-4" style={{ color: 'var(--color-text-muted)' }}>
                Нет свободных слотов
              </p>
            )}
          </div>
        )}

        {/* Service Selection Dialog */}
        {bookingStep === 'service' && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
            <div className="w-full max-w-sm rounded-2xl p-6 max-h-[80vh] overflow-y-auto" style={{ backgroundColor: 'var(--color-surface)' }}>
              <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text)' }}>
                Выберите услуги
              </h3>
              <p className="mb-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {format(selectedDate, 'EEEE, d MMMM', { locale: ru })} в {selectedSlot?.time?.slice(0, 5)}
              </p>

              <div className="space-y-2 mb-4">
                {services.filter(s => s.active).map(service => {
                  const isSelected = selectedServices.some(s => s.id === service.id)
                  return (
                    <button
                      key={service.id}
                      onClick={() => {
                        if (isSelected) {
                          setSelectedServices(selectedServices.filter(s => s.id !== service.id))
                        } else {
                          setSelectedServices([...selectedServices, service])
                        }
                      }}
                      className="w-full p-3 rounded-xl border text-left transition-all flex justify-between items-center"
                      style={{
                        backgroundColor: isSelected ? 'var(--color-accent-light)' : 'var(--color-bg)',
                        borderColor: isSelected ? 'var(--color-accent)' : 'var(--color-border)',
                      }}
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-5 h-5 rounded border flex items-center justify-center"
                          style={{
                            backgroundColor: isSelected ? 'var(--color-accent)' : 'transparent',
                            borderColor: isSelected ? 'var(--color-accent)' : 'var(--color-border)',
                          }}
                        >
                          {isSelected && <Check size={14} style={{ color: '#fff' }} />}
                        </div>
                        <span style={{ color: 'var(--color-text)' }}>{service.name}</span>
                      </div>
                      <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{service.duration_minutes} мин</span>
                    </button>
                  )
                })}
              </div>

              {selectedServices.length > 0 && (
                <div className="mb-4 p-3 rounded-xl" style={{ backgroundColor: 'var(--color-accent-light)' }}>
                  <p style={{ color: 'var(--color-text)' }}>Выбрано услуг: {selectedServices.length}</p>
                  <p className="text-sm" style={{ color: 'var(--color-accent)' }}>Общая длительность: {totalDuration} мин</p>
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={closeDialog}
                  className="flex-1 py-3 rounded-xl border font-medium"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                >
                  Назад
                </button>
                <button
                  onClick={handleServiceConfirm}
                  disabled={selectedServices.length === 0}
                  className="flex-1 py-3 rounded-xl font-bold"
                  style={{
                    backgroundColor: selectedServices.length > 0 ? 'var(--color-accent)' : 'var(--color-border)',
                    color: '#fff',
                  }}
                >
                  Далее
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Comment Dialog */}
        {bookingStep === 'comment' && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
            <div className="w-full max-w-sm rounded-2xl p-6" style={{ backgroundColor: 'var(--color-surface)' }}>
              <h3 className="text-lg font-bold mb-4" style={{ color: 'var(--color-text)' }}>
                Подтверждение записи
              </h3>
              <p className="mb-1" style={{ color: 'var(--color-text-secondary)' }}>
                {format(selectedDate, 'EEEE, d MMMM', { locale: ru })} в {selectedSlot?.time?.slice(0, 5)}
              </p>
              {selectedServices.length > 0 && (
                <div className="mb-4">
                  {selectedServices.map(s => (
                    <p key={s.id} style={{ color: 'var(--color-accent)' }}>{s.name}</p>
                  ))}
                  <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Всего: {totalDuration} мин</p>
                </div>
              )}

              {!isDemoMode() && !master?.is_demo && (
                <p className="text-sm mb-4" style={{ color: 'var(--color-success)' }}>
                  Контактные данные подтверждены {vkUser ? 'в ВКонтакте' : 'в Telegram'}
                </p>
              )}

              <textarea
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Комментарий мастеру (необязательно)..."
                rows={3}
                className="w-full p-3 rounded-xl border resize-none mb-4"
                style={{ backgroundColor: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)', outline: 'none' }}
                autoFocus
              />
              {error && (
                <div className="mb-4 p-3 rounded-lg text-sm" style={{ backgroundColor: 'rgba(248, 113, 113, 0.1)', color: 'var(--color-error)' }}>
                  {error}
                </div>
              )}
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    closeDialog()
                  }}
                  className="flex-1 py-3 rounded-xl border font-medium"
                  style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}
                >
                  Назад
                </button>
                <button
                  type="button"
                  data-booking-submit="true"
                  onClick={handleBookInline}
                  disabled={submitting}
                  className="flex-1 py-3 rounded-xl font-bold"
                  style={{ backgroundColor: 'var(--color-accent)', color: '#fff' }}
                >
                  {submitting ? 'Записываем...' : 'Записаться'}
                </button>
              </div>
            </div>
          </div>
        )}

        {actionBooking && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
            <div className="w-full max-w-sm rounded-2xl p-6 max-h-[85vh] overflow-y-auto" style={{ backgroundColor: 'var(--color-surface)' }}>
              <h3 className="text-lg font-bold mb-2" style={{ color: 'var(--color-text)' }}>
                {actionMode === 'cancel' ? 'Отменить запись?' : 'Перенести запись'}
              </h3>
              <p className="text-sm mb-4" style={{ color: 'var(--color-text-secondary)' }}>
                {format(new Date(`${actionBooking.date}T00:00:00`), 'd MMMM', { locale: ru })} в {actionBooking.time.slice(0, 5)}
              </p>

              {actionMode === 'reschedule' && (
                <>
                  {useServices && (
                    <div className="mb-4">
                      <p className="text-sm font-medium mb-2" style={{ color: 'var(--color-text)' }}>Услуги</p>
                      <div className="space-y-2">
                        {activeServices.map(service => {
                          const isSelected = actionServices.some(item => item.id === service.id)
                          return (
                            <label key={service.id} className="flex items-center gap-2 text-sm">
                              <input type="checkbox" checked={isSelected} onChange={() => {
                                setActionTime('')
                                setActionServices(isSelected ? actionServices.filter(item => item.id !== service.id) : [...actionServices, service])
                              }} />
                              <span>{service.name} ({service.duration_minutes} мин)</span>
                            </label>
                          )
                        })}
                      </div>
                      {actionServices.length === 0 && (
                        <p className="mt-2 text-xs" style={{ color: 'var(--color-text-muted)' }}>
                          Если не выбрать новую услугу, сохранится текущая: {actionBooking.service_name || `${actionBooking.duration_minutes} мин`}.
                        </p>
                      )}
                    </div>
                  )}
                  <div className="text-sm mb-3" style={{ color: 'var(--color-text)' }}>
                    <p className="mb-2">Новая дата</p>
                    <AvailabilityCalendar
                      currentMonth={actionMonth}
                      setCurrentMonth={setActionMonth}
                      selectedDate={actionDate}
                      onSelectDate={loadRescheduleSlots}
                      availableDates={actionAvailableDates}
                      loading={actionLoading}
                      minDate={new Date()}
                    />
                  </div>
                  {actionLoading ? <p className="text-sm mb-3" style={{ color: 'var(--color-text-muted)' }}>Загружаем свободное время...</p> : actionDate && (
                    actionSlots.length > 0 ? <div className="grid grid-cols-4 gap-2 mb-4">
                        {actionSlots.map(slot => (
                          <button key={slot.time} onClick={() => setActionTime(slot.time.slice(0, 5))} className="py-2 rounded-lg border text-sm" style={{ backgroundColor: actionTime === slot.time.slice(0, 5) ? 'var(--color-accent)' : 'transparent', borderColor: actionTime === slot.time.slice(0, 5) ? 'var(--color-accent)' : 'var(--color-border)', color: actionTime === slot.time.slice(0, 5) ? '#fff' : 'var(--color-text)' }}>{slot.time.slice(0, 5)}</button>
                        ))}
                      </div> : <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>На выбранную дату свободного времени нет</p>
                  )}
                </>
              )}

              <textarea value={actionComment} onChange={e => setActionComment(e.target.value)} placeholder="Комментарий мастеру (необязательно)..." maxLength={500} rows={3} className="w-full p-3 rounded-xl border resize-none mb-4" style={{ backgroundColor: 'var(--color-bg)', borderColor: 'var(--color-border)', color: 'var(--color-text)' }} />
              <div className="flex gap-3">
                <button onClick={closeBookingAction} className="flex-1 py-3 rounded-xl border font-medium" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text)' }}>Назад</button>
                <button onClick={submitBookingAction} disabled={actionLoading || (actionMode === 'reschedule' && (!actionTime || !actionDuration))} className="flex-1 py-3 rounded-xl font-bold" style={{ backgroundColor: actionMode === 'cancel' ? 'var(--color-error)' : 'var(--color-accent)', color: '#fff', opacity: actionLoading || (actionMode === 'reschedule' && (!actionTime || !actionDuration)) ? 0.55 : 1 }}>
                  {actionLoading ? 'Сохраняем...' : actionMode === 'cancel' ? 'Отменить' : 'Перенести'}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* User info badge — bottom right */}
      {tgUser && !isDemoMode() && (
        <div className="fixed bottom-4 right-4 z-40 flex items-center gap-2 px-3 py-2 rounded-xl shadow-lg text-sm"
          style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)', maxWidth: 220 }}>
          {tgUser.is_vk ? (
            <>
              <span style={{ color: '#2787F5', fontSize: 18, lineHeight: 1 }}>ВК</span>
              <div className="min-w-0">
                <p className="font-medium truncate" style={{ color: 'var(--color-text)', fontSize: 13 }}>
                  {tgUser.first_name}
                </p>
                <a href={`https://vk.com/id${vkUser}`} target="_blank" rel="noreferrer"
                  className="truncate block" style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                  vk.com/id{vkUser}
                </a>
              </div>
            </>
          ) : (
            <>
              <span style={{ color: '#229ED9', fontSize: 18, lineHeight: 1 }}>✈</span>
              <div className="min-w-0">
                <p className="font-medium truncate" style={{ color: 'var(--color-text)', fontSize: 13 }}>
                  {tgUser.first_name}
                </p>
                {tgUser.username && (
                  <p className="truncate" style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                    @{tgUser.username}
                  </p>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
