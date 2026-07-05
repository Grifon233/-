import { useState, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Save, Plus, Trash2, Check, Upload, Image as LucideImage, Camera, X, ChevronDown, User, ArrowLeft } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { resolveMediaUrl } from '../utils/media'

const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')

function getAuthQuery() {
  const params = new URLSearchParams(window.location.search)
  if (isDemoEditingRoute()) {
    const auth = new URLSearchParams()
    ;['user', 'username', 'name', 'sig', 'demo'].forEach(key => {
      const value = params.get(key)
      if (value) auth.set(key, value)
    })
    return auth.toString()
  }
  // Public demo preview uses the demo master's read-only identity.
  if (params.get('demo') === '1') {
    const auth = new URLSearchParams()
    auth.set('user', '999')
    return auth.toString()
  }
  const auth = new URLSearchParams()
  ;['user', 'user_id', 'username', 'name', 'sig', 'master_id', 'bot_id', 'auth_ts', 'vk_user', 'auth_source'].forEach(key => {
    const value = params.get(key)
    if (value) auth.set(key, value)
  })
  return auth.toString()
}

function isDemoRoute() {
  return new URLSearchParams(window.location.search).get('demo') === '1'
}

function isDemoEditingRoute() {
  return false
}

function hasAuthParams() {
  return Boolean(getAuthQuery())
}

async function api(endpoint, options = {}) {
  if (endpoint.startsWith('/api/admin/')) {
    const authQuery = getAuthQuery()
    if (authQuery) endpoint += `${endpoint.includes('?') ? '&' : '?'}${authQuery}`
  }
  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    throw new Error(response.ok ? 'Некорректный ответ сервера' : `Ошибка сервера ${response.status}: ${text || response.statusText}`);
  }
  if (!response.ok || !data?.success) {
    const msg = data?.detail?.[0]?.msg || data?.error?.message || (typeof data?.detail === 'string' ? data.detail : 'API error');
    throw new Error(msg);
  }
  return data.data;
}

const getMaster = (telegramId) => {
  // Демо режим - без авторизации
  if (isDemoRoute() && !isDemoEditingRoute()) {
    return api('/api/demo/master');
  }
  return api('/api/admin/master');
};
const getServices = (telegramId) => {
  if (isDemoRoute() && !isDemoEditingRoute()) {
    return api('/api/demo/services');
  }
  return api('/api/admin/services');
};
const getMenuButtons = (telegramId) => {
  if (isDemoRoute() && !isDemoEditingRoute()) {
    return api('/api/demo/menu-buttons');
  }
  return api('/api/admin/menu-buttons');
};
const updateMaster = (data) => api('/api/admin/master', { method: 'PUT', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json' } });
const createService = (data) => api('/api/admin/services', { method: 'POST', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json' } });
const updateService = (id, data) => api(`/api/admin/services/${id}`, { method: 'PUT', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json' } });
const deleteService = (id) => api(`/api/admin/services/${id}`, { method: 'DELETE' });
const updateMenuButton = (type, data) => api(`/api/admin/menu-buttons/${type}`, { method: 'PUT', body: JSON.stringify(data), headers: { 'Content-Type': 'application/json' } });

const shortenUrl = (url) => {
  const authQuery = getAuthQuery()
  const endpoint = `/api/shorten${authQuery ? '?' + authQuery : ''}`
  return api(endpoint, {
    method: 'POST',
    body: JSON.stringify(url),
    headers: { 'Content-Type': 'application/json' },
  })
}

const TABS = ['Профиль', 'Меню бота']
const RUSSIAN_TIMEZONES = [
  ['Europe/Kaliningrad', 'Калининград (UTC+2)'],
  ['Europe/Moscow', 'Москва (UTC+3)'],
  ['Europe/Samara', 'Самара (UTC+4)'],
  ['Asia/Yekaterinburg', 'Екатеринбург (UTC+5)'],
  ['Asia/Omsk', 'Омск (UTC+6)'],
  ['Asia/Krasnoyarsk', 'Красноярск (UTC+7)'],
  ['Asia/Irkutsk', 'Иркутск (UTC+8)'],
  ['Asia/Yakutsk', 'Якутск (UTC+9)'],
  ['Asia/Vladivostok', 'Владивосток (UTC+10)'],
  ['Asia/Magadan', 'Магадан (UTC+11)'],
  ['Asia/Kamchatka', 'Камчатка (UTC+12)'],
]
const REMINDER_HOURS = Array.from({ length: 24 }, (_, hour) => `${String(hour).padStart(2, '0')}:00`)

const graphemeSegmenter = typeof Intl !== 'undefined' && Intl.Segmenter
  ? new Intl.Segmenter('ru', { granularity: 'grapheme' })
  : null

function getTrailingEmoji(value) {
  if (!value) return null
  const normalized = value.trim()
  if (!normalized) return null
  const segments = graphemeSegmenter
    ? Array.from(graphemeSegmenter.segment(normalized), item => item.segment)
    : Array.from(normalized)
  const last = segments.at(-1) || ''
  return /\p{Extended_Pictographic}/u.test(last) ? last : null
}

function DemoReadOnlySettings({ master, services, menuButtons, tab, setTab, navigate }) {
  const scheduleDays = master?.schedule?.days || []
  const menuEntries = Object.entries(menuButtons || {})

  return (
    <div className="animate-fade-slide space-y-6">
      <div className="p-4 rounded-2xl border" style={{ background: 'rgba(212, 168, 83, 0.12)', borderColor: 'var(--color-accent)', color: 'var(--color-text-primary)' }}>
        <div className="font-bold mb-1">Демо-режим только для просмотра</div>
        <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
          Редактирование текстов, фото, услуг, расписания и включение/отключение кнопок заблокировано.
        </div>
      </div>

      <div className="flex justify-center">
        <div className="inline-flex p-1 rounded-xl" style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-6 py-2 text-sm font-semibold rounded-lg transition-all ${tab === t ? 'tab-active' : 'tab-inactive'}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {tab === 'Профиль' && (
        <div className="card overflow-hidden">
          <div className="px-8 py-6 flex items-center gap-5" style={{ background: 'linear-gradient(135deg, var(--color-accent) 0%, #b8953f 100%)' }}>
            <button onClick={() => navigate(`/calendar${window.location.search}`)} className="p-2.5 rounded-2xl btn-press" style={{ background: 'rgba(0,0,0,0.2)' }}>
              <ArrowLeft className="w-6 h-6 text-white" />
            </button>
            <h1 className="text-white text-2xl font-bold tracking-tight">Профиль мастера</h1>
          </div>

          <div className="p-4 sm:p-6 md:p-8 space-y-6">
            <div className="flex flex-col sm:flex-row items-center gap-5">
              {master.avatar_url ? (
                <img src={resolveMediaUrl(master.avatar_url)} alt="Аватарка" className="w-24 h-24 sm:w-32 sm:h-32 rounded-3xl object-cover avatar-ring" />
              ) : (
                <div className="w-24 h-24 sm:w-32 sm:h-32 rounded-3xl flex items-center justify-center" style={{ background: 'var(--color-accent-light)' }}>
                  <User size={48} style={{ color: 'var(--color-accent)' }} />
                </div>
              )}
              <div className="flex-1 text-center sm:text-left">
                <h2 className="text-2xl font-extrabold">{master.name || 'Мастер'}</h2>
                <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>Интервал: {master.interval_minutes || 60} мин · режим: {master.use_services ? 'услуги' : 'простой'}</p>
              </div>
            </div>

            <div className="card-elevated p-5">
              <h3 className="font-bold text-lg mb-3">Услуги</h3>
              {services.length ? (
                <div className="grid gap-2">
                  {services.map(service => (
                    <div key={service.id} className="flex items-center justify-between gap-3 p-3 rounded-xl" style={{ background: 'var(--color-surface)' }}>
                      <span className="font-medium">{service.name}</span>
                      <span className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{service.price} · {service.duration_minutes} мин</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Услуги не добавлены</p>
              )}
            </div>

            <div className="card-elevated p-5">
              <h3 className="font-bold text-lg mb-3">Расписание</h3>
              <div className="grid gap-2">
                {scheduleDays.map((day, index) => (
                  <div key={`${day.day}-${index}`} className="flex flex-wrap items-center justify-between gap-2 p-3 rounded-xl" style={{ background: 'var(--color-surface)' }}>
                    <span className="font-medium">{day.day}</span>
                    <span className="text-sm" style={{ color: day.active ? 'var(--color-text-secondary)' : 'var(--color-text-muted)' }}>
                      {day.active ? `${day.work_start}–${day.work_end}${day.break_start && day.break_end ? `, перерыв ${day.break_start}–${day.break_end}` : ''}` : 'выходной'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'Меню бота' && (
        <div className="space-y-4">
          {menuEntries.map(([type, button]) => (
            <DemoMenuCard key={type} type={type} button={button} />
          ))}
        </div>
      )}
    </div>
  )
}

function DemoMenuCard({ type, button }) {
  const content = button?.content || {}
  const labels = {
    price: 'Прайс',
    faq: 'Частые вопросы',
    address: 'Адрес',
    portfolio: 'Портфолио',
    custom: 'Кастомные кнопки',
  }

  return (
    <div className="card-elevated p-5">
      <div className="flex items-center justify-between gap-3 mb-4">
        <h3 className="font-bold text-lg">{labels[type] || type}</h3>
        <span className="text-xs px-2 py-1 rounded-lg" style={{ background: button?.active ? 'rgba(74, 222, 128, 0.12)' : 'rgba(248, 113, 113, 0.12)', color: button?.active ? 'var(--color-success)' : 'var(--color-error)' }}>
          {button?.active ? 'включена' : 'выключена'}
        </span>
      </div>

      {type === 'price' && (
        <div className="grid gap-2">
          {(content.items || []).map((item, index) => (
            <div key={index} className="flex justify-between gap-3 p-3 rounded-xl" style={{ background: 'var(--color-surface)' }}>
              <span>{item.name}</span>
              <span style={{ color: 'var(--color-text-secondary)' }}>{item.price}</span>
            </div>
          ))}
        </div>
      )}

      {type === 'faq' && (
        <div className="grid gap-3">
          {(content.items || []).map((item, index) => (
            <div key={index} className="p-3 rounded-xl" style={{ background: 'var(--color-surface)' }}>
              <div className="font-semibold">{item.question}</div>
              <div className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>{item.answer}</div>
            </div>
          ))}
        </div>
      )}

      {type === 'address' && (
        <div className="space-y-3">
          {content.text && <p className="whitespace-pre-wrap text-sm" style={{ color: 'var(--color-text-secondary)' }}>{content.text}</p>}
          {content.photo && <img src={resolveMediaUrl(content.photo)} alt="" className="max-h-64 rounded-xl object-cover" />}
        </div>
      )}

      {type === 'portfolio' && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
          {(content.photos || []).map((photo, index) => (
            <img key={index} src={resolveMediaUrl(photo)} alt="" className="w-full aspect-square rounded-xl object-cover" />
          ))}
        </div>
      )}

      {type === 'custom' && (
        <div className="grid gap-3">
          {(content.custom_buttons || []).map((custom, index) => (
            <div key={index} className="p-3 rounded-xl" style={{ background: 'var(--color-surface)' }}>
              <div className="font-semibold">{custom.icon ? `${custom.icon} ` : ''}{custom.name}</div>
              {(custom.texts || []).map((text, i) => (
                <p key={i} className="text-sm mt-1 whitespace-pre-wrap" style={{ color: 'var(--color-text-secondary)' }}>{text}</p>
              ))}
              {(custom.links || []).map((link, i) => (
                <a key={i} href={link.url} className="block text-sm mt-2 underline" style={{ color: 'var(--color-accent)' }}>{link.text || link.url}</a>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

async function compressImage(file, maxWidth = 1200, maxHeight = 1200, quality = 0.8) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      const img = document.createElement('img')
      img.onload = () => {
        const canvas = document.createElement('canvas')
        let width = img.width
        let height = img.height
        if (width > height && width > maxWidth) {
          height = Math.round((height * maxWidth) / width)
          width = maxWidth
        } else if (height > maxHeight) {
          width = Math.round((width * maxHeight) / height)
          height = maxHeight
        }
        canvas.width = width
        canvas.height = height
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0, width, height)
        canvas.toBlob(resolve, 'image/jpeg', quality)
      }
      img.src = e.target.result
    }
    reader.readAsDataURL(file)
  })
}

const EMOJI_LIST = [
  // Красота/бьюти
  '💇', '💇‍♀️', '💇‍♂️', '💅', '💅‍♀️', '💅‍♂️', '👁', '🧴', '💄', '💋', '👰', '💆', '💆‍♀️', '💆‍♂️', '✨', '🌟', '💎', '👑', '👒', '🦷', '🧖', '🧖‍♀️', '🧖‍♂️', '👠', '👡', '👢', '💍', '💈', '🪒', '✂️', '🪮', '🧴', '🧽', '🧼', '🛁', '🚿', '🪥', '💇‍♀️', '💇‍♂️',
  // Спорт/фитнес
  '💪', '🏋️', '🤸', '🏃', '🧘', '⛹️', '🤺', '⛷️', '🏄', '🏂', '🎾', '🏐', '⚽', '🏀', '🎳', '🏋️‍♀️', '🏋️‍♂️', '🧗', '🏇', '🤼',
  // Образование
  '📚', '🎓', '✏️', '📖', '📝', '📒', '📕', '📗', '📘', '🖊️', '🖋️', '✒️', '📐', '📏', '📊', '📈', '🔬', '🔭', '🧪', '🧬',
  // Еда/рестораны
  '🍽️', '🍜', '🍝', '🍕', '🍔', '🍟', '🍣', '🍱', '🥗', '☕', '🍵', '🧁', '🍰', '🍩', '🍪', '🍫', '🍿', '🥤', '🍴', '🍳',
  // Ремонт/строительство/быт
  '🔧', '🔨', '🛠️', '⚒️', '🔩', '⚙️', '🔪', '🪚', '🪛', '🪜', '🏠', '🏡', '🏢', '🏗️', '🚧', '🔌', '💡', '🔋', '🔔', '🧲',
  // Медицина/здоровье
  '🏥', '🩺', '💊', '🩹', '🩸', '🩼', '⚕️', '💉', '🫀', '🧠', '🦴', '💒', '🧬', '🩻',
  // Туризм/путешествия
  '🌍', '🗺️', '🧳', '🏖️', '🏕️', '🏔️', '⛰️', '🌅', '🌄', '🏝️', '🏜️', '🌋', '🏰', '⛪', '🗼', '🗽', '🏟️', '🗻', '🌊',
  // Искусство/творчество
  '🎨', '🖼️', '🎭', '🎪', '🎯', '🎰', '🎲', '🀄', '♟️', '🎸', '🎹', '🎺', '🎻', '🥁', '🎙️', '🎚️', '🎛️', '🎞️', '🎟️',
  // Другое
  '🎁', '👥', '📋', '📸', '📍', '🕐', '📞', '✅', '💰', '🔥', '⭐', '❤️', '🎉', '🎊', '🥳', '🎈', '🎆', '🎇', '💯', '🌸', '🌺', '🌹', '🌷', '🌻', '🌼', '🥀', '💐', '🍃', '🦋', '🐾', '🐶', '🐱'
]

function HelpTooltip({ title, children }) {
  const [show, setShow] = useState(false)
  return (
    <>
      <div
        role="button"
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setShow(true) }}
        onMouseDown={(e) => { e.stopPropagation(); e.preventDefault() }}
        onTouchStart={(e) => { e.stopPropagation(); e.preventDefault() }}
        className="w-6 h-6 rounded-full flex items-center justify-center text-sm flex-shrink-0 cursor-pointer"
        style={{ background: 'var(--color-accent-light)', color: 'var(--color-accent)' }}
      >
        ?
      </div>
      {show && createPortal(
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center p-4"
          style={{ background: 'rgba(0,0,0,0.85)', pointerEvents: 'all' }}
          onClick={(e) => { e.stopPropagation(); setShow(false) }}
        >
          <div
            className="w-full max-w-3xl max-h-[70vh] overflow-y-auto rounded-2xl"
            style={{ background: '#1a1a1a', border: '1px solid #333', pointerEvents: 'all' }}
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between p-5 pb-4" style={{ background: '#1a1a1a', borderBottom: '1px solid #333' }}>
              <h4 className="font-bold text-lg m-0" style={{ color: '#fff' }}>{title}</h4>
              <button onClick={(e) => { e.stopPropagation(); setShow(false) }} style={{ background: 'var(--color-accent)', border: 'none', borderRadius: '50%', width: 32, height: 32, cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <X size={18} style={{ color: '#fff' }} />
              </button>
            </div>
            <div className="p-5 text-sm" style={{ color: '#ccc', lineHeight: 1.6 }}>
              {children}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  )
}

function EmojiPicker({ onSelect, onClose }) {
  const ref = useRef(null)
  useEffect(() => {
    function handleClick(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose()
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [onClose])
  return (
    <div ref={ref} className="absolute z-50 mt-1 p-2 rounded-xl shadow-lg max-w-48 max-h-40 overflow-y-auto" style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
      <div className="grid grid-cols-8 gap-1">
        {EMOJI_LIST.map(e => (
          <button key={e} onClick={() => onSelect(e)} className="p-1 text-lg rounded hover:bg-[var(--color-border)] transition-colors">{e}</button>
        ))}
      </div>
    </div>
  )
}

function TextWithEmoji({ value, onChange, placeholder, rows, maxLength }) {
  const [showPicker, setShowPicker] = useState(false)
  const handleChange = (v) => onChange(maxLength ? v.slice(0, maxLength) : v)
  return (
    <div className="relative">
      {rows ? (
        <textarea value={value} onChange={e => handleChange(e.target.value)} placeholder={placeholder} rows={rows} maxLength={maxLength} className="w-full resize-none px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]" />
      ) : (
        <input type="text" value={value} onChange={e => handleChange(e.target.value)} placeholder={placeholder} maxLength={maxLength} className="w-full px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]" />
      )}
      <button onClick={() => setShowPicker(!showPicker)} type="button" className="absolute right-2 top-1/2 -translate-y-1/2 w-8 h-8 rounded-lg flex items-center justify-center transition-all hover:scale-110" style={{ background: showPicker ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showPicker ? '#fff' : 'var(--color-accent)' }}>
        😀
      </button>
      {showPicker && <EmojiPicker onSelect={e => { onChange(value + e); setShowPicker(false) }} onClose={() => setShowPicker(false)} />}
    </div>
  )
}

function ServiceItem({ service, onUpdate, onDelete }) {
  const [showEmoji, setShowEmoji] = useState(false)
  const trailingEmoji = getTrailingEmoji(service.name)

  return (
    <div className="service-mobile-card group">
      <div className="service-mobile-top">
        <button
          onClick={() => onUpdate(service.id, { active: !service.active })}
          className={`service-mobile-toggle btn-press ${service.active ? 'btn-primary' : ''}`}
          style={!service.active ? { border: '1px solid var(--color-border)' } : {}}
        >
          {service.active && <Check className="w-3 h-3" />}
        </button>
        <div className="relative service-mobile-name-wrap">
          <input
            type="text"
            value={service.name}
            onChange={e => onUpdate(service.id, { name: e.target.value.slice(0, 50) })}
            placeholder="Название услуги"
            maxLength={50}
            className="service-mobile-name-input"
            style={{ minWidth: 0 }}
          />
          {showEmoji && (
            <EmojiPicker onSelect={(e) => { onUpdate(service.id, { name: service.name + e }); setShowEmoji(false) }} onClose={() => setShowEmoji(false)} />
          )}
        </div>
        <button
          onClick={() => setShowEmoji(!showEmoji)}
          type="button"
          className="service-mobile-emoji"
          style={{ background: showEmoji ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showEmoji ? '#fff' : 'var(--color-accent)' }}
        >
          {trailingEmoji || '😊'}
        </button>
      </div>

      <div className="service-mobile-bottom">
        <div className="service-mobile-field service-mobile-field-price">
          <input
            type="text"
            value={service.price}
            onChange={(e) => {
              const val = e.target.value.replace(/[^0-9]/g, '')
              onUpdate(service.id, { price: val ? `${val} ₽` : '' })
            }}
            onBlur={(e) => {
              const val = e.target.value.replace(/[^0-9]/g, '')
              onUpdate(service.id, { price: val ? `${val} ₽` : '' })
            }}
            placeholder="0 ₽"
            className="service-mobile-price"
          />
        </div>
        <div className="service-mobile-field service-mobile-field-duration">
          <select
            value={service.duration_minutes || 60}
            onChange={e => onUpdate(service.id, { duration_minutes: parseInt(e.target.value) })}
            className="service-mobile-duration"
          >
            <option value="15">15м</option>
            <option value="30">30м</option>
            <option value="45">45м</option>
            <option value="60">1ч</option>
            <option value="90">1.5ч</option>
            <option value="120">2ч</option>
          </select>
        </div>
        <button onClick={() => onDelete(service.id)} className="service-mobile-delete btn-ghost" style={{ color: 'var(--color-error)' }}>
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  )
}

function PriceItem({ item, index, onUpdate, onDelete }) {
  const [showEmoji, setShowEmoji] = useState(false)
  const trailingEmoji = getTrailingEmoji(item.name)

  return (
    <div className="relative group">
      <button onClick={() => onDelete(index)} className="absolute -right-2 -top-6 p-2 rounded-lg transition-all opacity-0 group-hover:opacity-100 btn-ghost" style={{ color: 'var(--color-error)' }}>
        <Trash2 className="w-4 h-4" />
      </button>
      <div className="flex items-center gap-2 p-3 rounded-xl max-md:p-2 max-md:gap-1.5" style={{ background: 'var(--color-surface)' }}>
        <span className="text-xs w-5 text-center flex-shrink-0 max-md:!text-[10px]" style={{ color: 'var(--color-text-muted)' }}>{index + 1}</span>
        <div className="relative flex-1 flex items-center gap-1 min-w-[100px]">
          <input
            type="text"
            value={item.name}
            onChange={e => onUpdate(index, 'name', e.target.value.slice(0, 120))}
            placeholder="Услуга"
            maxLength={120}
            className="flex-1 text-sm font-medium px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)] max-md:text-xs max-md:px-2 max-md:py-1.5 max-md:!text-[11px]"
          />
          <button
            onClick={() => setShowEmoji(!showEmoji)}
            type="button"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all hover:scale-110 flex-shrink-0 max-md:w-7 max-md:h-7"
            style={{ background: showEmoji ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showEmoji ? '#fff' : 'var(--color-accent)' }}
          >
            {trailingEmoji || '😀'}
          </button>
          {showEmoji && (
            <EmojiPicker onSelect={(e) => { onUpdate(index, 'name', item.name + e); setShowEmoji(false) }} onClose={() => setShowEmoji(false)} />
          )}
        </div>
        <input
          type="text"
          value={item.price}
          onChange={e => {
            const val = e.target.value.replace(/[^0-9]/g, '')
            onUpdate(index, 'price', val ? `${val} ₽` : '')
          }}
          onBlur={e => {
            const val = e.target.value.replace(/[^0-9]/g, '')
            onUpdate(index, 'price', val ? `${val} ₽` : '')
          }}
          placeholder="0 ₽"
          className="w-20 bg-[var(--color-surface-elevated)] border border-[var(--color-border)] rounded-lg px-2 py-1.5 text-sm font-bold text-right max-md:w-16 max-md:text-xs max-md:!text-[11px] max-md:px-1 max-md:py-1"
        />
      </div>
    </div>
  )
}

function FAQItem({ item, index, onUpdate, onDelete }) {
  const [showQ, setShowQ] = useState(false)
  const [showA, setShowA] = useState(false)
  const questionEmoji = getTrailingEmoji(item.question)
  const answerEmoji = getTrailingEmoji(item.answer)

  return (
    <div className="relative group">
      <button onClick={() => onDelete(index)} className="absolute -right-2 -top-6 p-2 rounded-lg transition-all opacity-0 group-hover:opacity-100 btn-ghost z-10" style={{ color: 'var(--color-error)' }}>
        <Trash2 className="w-4 h-4" />
      </button>
      <div className="space-y-3">
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>{index + 1}. Вопрос</label>
          <div className="relative flex items-center gap-1">
            <input
              type="text"
              value={item.question}
              onChange={e => onUpdate(index, 'question', e.target.value.slice(0, 500))}
              placeholder="Как записаться?"
              maxLength={500}
              className="flex-1 text-sm px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
            />
            <button
              onClick={() => setShowQ(!showQ)}
              type="button"
              className="w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all hover:scale-110 flex-shrink-0"
              style={{ background: showQ ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showQ ? '#fff' : 'var(--color-accent)' }}
            >
              {questionEmoji || '😀'}
            </button>
            {showQ && (
              <EmojiPicker onSelect={(e) => { onUpdate(index, 'question', item.question + e); setShowQ(false) }} onClose={() => setShowQ(false)} />
            )}
          </div>
        </div>
        <div>
          <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Ответ</label>
          <div className="relative">
            <textarea
              value={item.answer}
              onChange={e => onUpdate(index, 'answer', e.target.value.slice(0, 3000))}
              placeholder="Напишите в бот"
              rows={3}
              maxLength={3000}
              className="w-full resize-none px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
            />
            <button
              onClick={() => setShowA(!showA)}
              type="button"
              className="absolute right-2 top-2 w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all hover:scale-110"
              style={{ background: showA ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showA ? '#fff' : 'var(--color-accent)' }}
            >
              {answerEmoji || '😀'}
            </button>
            {showA && (
              <EmojiPicker onSelect={(e) => { onUpdate(index, 'answer', item.answer + e); setShowA(false) }} onClose={() => setShowA(false)} />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function AddressTextArea({ content, field, placeholder }) {
  const [showEmoji, setShowEmoji] = useState(false)
  const trailingEmoji = getTrailingEmoji(content[field])

  return (
    <div className="relative">
      <textarea
        value={content[field] || ''}
        onChange={e => onUpdate({ [field]: e.target.value.slice(0, 3000) })}
        placeholder={placeholder}
        rows={3}
        maxLength={3000}
        className="w-full resize-none px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
      />
      <button
        onClick={() => setShowEmoji(!showEmoji)}
        type="button"
        className="absolute right-2 top-2 w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all hover:scale-110"
        style={{ background: showEmoji ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showEmoji ? '#fff' : 'var(--color-accent)' }}
      >
        {trailingEmoji || '😀'}
      </button>
      {showEmoji && (
        <EmojiPicker onSelect={(e) => { onUpdate({ [field]: (content[field] || '') + e }); setShowEmoji(false) }} onClose={() => setShowEmoji(false)} />
      )}
    </div>
  )
}

function CustomButtonItem({ button, index, onUpdate, onDelete, onUpload, uploading }) {
  const [showIconPicker, setShowIconPicker] = useState(false)
  const [showEmoji, setShowEmoji] = useState(false)
  const trailingEmoji = getTrailingEmoji(button.name)
  const hasIcon = button.icon && button.icon.length > 0

  function handleUpdate(data) {
    onUpdate(index, data)
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="space-y-4 p-4 rounded-xl" style={{ background: 'var(--color-surface)' }}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>Кнопка {index + 1}</span>
        <button onClick={() => onDelete(index)} className="p-1.5 rounded-lg btn-ghost" style={{ color: 'var(--color-error)' }}>
          <Trash2 className="w-4 h-4" />
        </button>
      </div>

      {/* Иконка для Telegram */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Иконка в Telegram</label>
        <div className="relative flex items-center gap-1">
          <button
            onClick={() => setShowIconPicker(!showIconPicker)}
            type="button"
            className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl transition-all hover:scale-105"
            style={{ background: showIconPicker ? 'var(--color-accent)' : 'var(--color-surface-elevated)', border: '1px solid var(--color-border)', color: showIconPicker ? '#fff' : 'var(--color-text)' }}
          >
            {hasIcon ? button.icon : '🎯'}
          </button>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Выберите иконку для кнопки в Telegram</span>
          {showIconPicker && (
            <EmojiPicker onSelect={(e) => { handleUpdate({ icon: e }); setShowIconPicker(false) }} onClose={() => setShowIconPicker(false)} />
          )}
        </div>
      </div>

      {/* Название кнопки */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Название кнопки</label>
        <div className="relative flex items-center gap-1">
          <input
            type="text"
            value={button.name || ''}
            onChange={e => handleUpdate({ name: e.target.value.slice(0, 30) })}
            placeholder="Например: Мои работы"
            maxLength={30}
            className="flex-1 text-sm px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
          />
          <button
            onClick={() => setShowEmoji(!showEmoji)}
            type="button"
            className="w-8 h-8 rounded-lg flex items-center justify-center text-sm transition-all hover:scale-110 flex-shrink-0"
            style={{ background: showEmoji ? 'var(--color-accent)' : 'var(--color-accent-light)', color: showEmoji ? '#fff' : 'var(--color-accent)' }}
          >
            {trailingEmoji || '😀'}
          </button>
          {showEmoji && (
            <EmojiPicker onSelect={(e) => { handleUpdate({ name: (button.name || '') + e }); setShowEmoji(false) }} onClose={() => setShowEmoji(false)} />
          )}
        </div>
      </div>

      {/* Текст кнопки */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Текст кнопки</label>
        <input
          type="text"
          value={button.text || ''}
          onChange={e => handleUpdate({ text: e.target.value.slice(0, 64) })}
          placeholder="Текст для кнопки в Telegram"
          maxLength={64}
          className="w-full text-sm px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
        />
      </div>

      {/* Ссылка */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Ссылка</label>
        <input
          type="text"
          value={button.url || ''}
          onChange={e => handleUpdate({ url: e.target.value })}
          onBlur={async e => {
            const url = e.target.value
            if (url.startsWith('http') && url.length > 50) {
              try {
                const result = await shortenUrl(url)
                handleUpdate({ url: `${window.location.origin}/s/${result.code}` })
              } catch {}
            }
          }}
          placeholder="https://example.com (автосокращение)"
          className="w-full text-sm px-3 py-2 rounded-lg bg-[var(--color-surface-elevated)] border border-[var(--color-border)]"
        />
      </div>

      {/* Фото (до 3) */}
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Фото (до 3)</label>
        <div className="flex flex-wrap gap-2">
          {(button.photos || []).map((photo, i) => (
            <div key={i} className="relative w-16 h-16 rounded-lg overflow-hidden" style={{ background: 'var(--color-surface-elevated)' }}>
              <img src={resolveMediaUrl(photo)} alt="" className="w-full h-full object-cover" />
              <button onClick={() => handleUpdate({ photos: (button.photos || []).filter((_, idx) => idx !== i) })} className="absolute top-1 right-1 p-1 rounded-lg" style={{ background: 'rgba(0,0,0,0.5)', color: 'var(--color-error)' }}>
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
          <label className="w-16 h-16 border-2 border-dashed rounded-lg flex items-center justify-center cursor-pointer transition-all" style={{ borderColor: 'var(--color-border)' }}>
            {uploading ? (
              <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>...</span>
            ) : (
              <Plus className="w-5 h-5" style={{ color: 'var(--color-text-muted)' }} />
            )}
            <input type="file" accept="image/*" className="hidden" onChange={handleFileChange} disabled={uploading} />
          </label>
        </div>
      </div>
    </div>
  )
}

export default function Settings() {
  const navigate = useNavigate()
  const readOnlyDemo = isDemoRoute() && !isDemoEditingRoute()
  const [tab, setTab] = useState('Профиль')
  const [saving, setSaving] = useState(false)
  const [master, setMaster] = useState(null)
  const [services, setServices] = useState([])
  const [menuButtons, setMenuButtons] = useState({})
  const [uploadingAvatar, setUploadingAvatar] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [showSchedule, setShowSchedule] = useState(false)
  const [showWorkMode, setShowWorkMode] = useState(false)
  const [showServices, setShowServices] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [showReminderPicker, setShowReminderPicker] = useState(false)
  const [tgUser, setTgUser] = useState(null)
  const [isAdmin, setIsAdmin] = useState(false)
  const avatarInputRef = useRef(null)
  const saveTimersRef = useRef({})

  function blockDemoEdit() {
    alert('Демо-режим сейчас доступен только для просмотра. Редактирование отключено.')
  }

  useEffect(() => {
    // Read Telegram WebApp user data
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp.initDataUnsafe?.user
      if (tg) setTgUser(tg)
      window.Telegram.WebApp.expand()
    }
    // Also check URL params (for web login)
    const params = new URLSearchParams(window.location.search)
    const userParam = params.get('user')
    const nameParam = params.get('name')
    const usernameParam = params.get('username')
    if (userParam && !tgUser) {
      // Try JSON format first (base64 encoded)
      if (userParam.startsWith('{')) {
        try {
          const userData = JSON.parse(decodeURIComponent(userParam))
          setTgUser(userData)
          return
        } catch {}
      }
      // Fall back to separate params (old format from Architect)
      setTgUser({
        id: parseInt(userParam, 10),
        first_name: nameParam || 'Пользователь',
        username: usernameParam || null
      })
    }
  }, [])

  async function loadData(telegramId = null) {
    try {
      setError(null)
      const [m, s, mb] = await Promise.all([
        getMaster(telegramId),
        getServices(telegramId),
        getMenuButtons(telegramId)
      ])
      setIsAdmin(isDemoEditingRoute() || (telegramId && m?.telegram_id === telegramId))
      setMaster(m)
      setServices(s?.services || [])
      setMenuButtons(mb?.buttons || {})
    } catch (e) {
      console.error('Load error:', e)
      setError('Ошибка загрузки: ' + e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Read Telegram WebApp user data
    if (window.Telegram?.WebApp) {
      const tg = window.Telegram.WebApp.initDataUnsafe?.user
      if (tg) setTgUser(tg)
      window.Telegram.WebApp.expand()
    }
    // Also check URL params (for web login)
    const params = new URLSearchParams(window.location.search)
    const userParam = params.get('user')
    const nameParam = params.get('name')
    const usernameParam = params.get('username')
    if (userParam && !tgUser) {
      if (userParam.startsWith('{')) {
        try {
          const userData = JSON.parse(decodeURIComponent(userParam))
          setTgUser(userData)
        } catch {}
      } else {
        setTgUser({
          id: parseInt(userParam, 10),
          first_name: nameParam || 'Пользователь',
          username: usernameParam || null
        })
      }
    }
  }, [])

  useEffect(() => {
    if (isDemoRoute()) {
      loadData()
    } else if (tgUser?.id) {
      loadData(tgUser.id)
    } else if (!hasAuthParams()) {
      setLoading(false)
      setError('Настройки открываются только из вашего бота или календаря. Откройте созданного бота, нажмите /start → «Календарь» → «Настройки».')
    } else {
      loadData(null)
    }
  }, [tgUser])

  // Force load for demo mode even without tgUser
  useEffect(() => {
    if (isDemoRoute() && !master) {
      loadData()
    }
  }, [])

  async function uploadFile(file, type = 'image') {
    if (readOnlyDemo) {
      blockDemoEdit()
      throw new Error('Демо-режим доступен только для просмотра')
    }
    const compressed = await compressImage(file)
    const formData = new FormData()
    formData.append('file', compressed, file.name)
    formData.append('file_type', type)
    const authQuery = getAuthQuery()
    const endpoint = `/api/admin/upload${authQuery ? '?' + authQuery : ''}`
    const resp = await fetch(`${API_URL}${endpoint}`, { method: 'POST', body: formData })
    const text = await resp.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      throw new Error(resp.ok ? 'Некорректный ответ сервера' : `Ошибка сервера ${resp.status}: ${text || resp.statusText}`)
    }
    if (!resp.ok || !data?.success) {
      const msg = data?.detail?.[0]?.msg || data?.error?.message || (typeof data?.detail === 'string' ? data.detail : 'Upload failed')
      throw new Error(msg)
    }
    return data.data.url
  }

  async function saveMaster(data) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    setSaving(true)
    try {
      await updateMaster(data)
      setMaster({ ...master, ...data })
    } catch (e) {
      alert('Ошибка: ' + e.message)
    } finally {
      setSaving(false)
    }
  }

  async function handleAvatarChange(e) {
    if (readOnlyDemo) {
      blockDemoEdit()
      e.target.value = ''
      return
    }
    const file = e.target.files?.[0]
    if (!file) return
    setUploadingAvatar(true)
    try {
      const url = await uploadFile(file, 'avatar')
      await saveMaster({ avatar_url: url })
    } catch (e) {
      alert('Ошибка загрузки: ' + e.message)
    } finally {
      setUploadingAvatar(false)
    }
  }

  async function handleAddService() {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    try {
      const created = await createService({ name: '', price: '', duration_minutes: 60, active: true })
      setServices([...services, created])
      // Focus the new service input
      setTimeout(() => {
        const inputs = document.querySelectorAll('input[placeholder="Услуга"]')
        const lastInput = inputs[inputs.length - 1]
        if (lastInput) lastInput.focus()
      }, 100)
    } catch (e) {
      alert('Ошибка: ' + e.message)
    }
  }

  async function handleToggleService(id, active) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    try {
      await updateService(id, { active: !active })
      setServices(services.map(s => s.id === id ? { ...s, active: !active } : s))
    } catch (e) {
      alert('Ошибка: ' + e.message)
    }
  }

  async function handleDeleteService(id) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    try {
      await deleteService(id)
      setServices(services.filter(s => s.id !== id))
    } catch (e) {
      alert('Ошибка: ' + e.message)
    }
  }

  async function handleUpdateService(id, data) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    if (typeof data.name === 'string' && data.name.trim() === '') {
      setServices(services.map(s => s.id === id ? { ...s, ...data } : s))
      return
    }
    try {
      setServices(services.map(s => s.id === id ? { ...s, ...data } : s))
      await updateService(id, data)
    } catch (e) {
      alert('Ошибка: ' + e.message)
    }
  }

  async function handleToggle(type, active) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    const current = menuButtons[type] || { active: false, content: {} }
    setMenuButtons(prev => ({ ...prev, [type]: { ...current, active } }))
    try {
      await updateMenuButton(type, { active, content: current.content })
    } catch (e) {
      alert('Ошибка при сохранении статуса: ' + e.message)
      setMenuButtons(prev => ({ ...prev, [type]: current }))
    }
  }

  function handleUpdateContent(type, newContent) {
    if (readOnlyDemo) {
      blockDemoEdit()
      return
    }
    setMenuButtons(prev => {
      const current = prev[type] || { active: false, content: {} }
      // Preserve existing content but merge with newContent
      const updatedContent = { ...current.content, ...newContent }
      const nextState = { ...prev, [type]: { ...current, content: updatedContent } }
      const active = current.active
      // Debounce: раньше PUT уходил на КАЖДУЮ нажатую клавишу — гонки и лишняя
      // нагрузка. Теперь сохраняем через паузу после последнего изменения.
      if (saveTimersRef.current[type]) clearTimeout(saveTimersRef.current[type])
      saveTimersRef.current[type] = setTimeout(() => {
        updateMenuButton(type, { active, content: updatedContent })
          .catch(e => alert('Не удалось сохранить: ' + e.message))
      }, 700)
      return nextState
    })
  }

  function selectReminderTime(value) {
    setMaster(current => ({ ...current, reminder_time: value }))
    setShowReminderPicker(false)
    saveMaster({ reminder_time: value })
  }

  if (loading) {
    return <div className="text-center py-20 animate-pulse" style={{ color: 'var(--color-text-secondary)' }}>Загрузка...</div>
  }

  return (
    <div className={`animate-fade-slide ${readOnlyDemo ? 'demo-readonly' : ''}`}>
      {showReminderPicker && master?.notify_reminders !== false && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 time-picker-modal"
          style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}
          onClick={() => setShowReminderPicker(false)}
        >
          <div
            className="rounded-2xl p-4 w-72 max-h-80 overflow-y-auto"
            style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}
            onClick={event => event.stopPropagation()}
          >
            <div className="mb-3 pb-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
              <div className="flex items-center justify-between text-xs" style={{ color: 'var(--color-text-muted)' }}>
                <span>Выберите время:</span>
                <button type="button" onClick={() => setShowReminderPicker(false)} className="hover:opacity-70">✕</button>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-1">
              {REMINDER_HOURS.map(value => {
                const isSelected = (master.reminder_time || '18:00') === value
                return (
                  <button
                    key={value}
                    type="button"
                    onClick={() => selectReminderTime(value)}
                    className="px-2 py-1.5 text-xs rounded-lg transition-all hover:opacity-80"
                    style={{
                      background: isSelected ? 'var(--color-accent)' : 'var(--color-surface)',
                      color: isSelected ? '#0a0a0a' : 'var(--color-text)',
                    }}
                  >
                    {value}
                  </button>
                )
              })}
            </div>
          </div>
        </div>
      )}
      {error && (
        <div className="mb-6 p-4 rounded-xl border" style={{ background: 'rgba(248, 113, 113, 0.1)', borderColor: 'var(--color-error)', color: 'var(--color-error)' }}>
          {error}
          <button onClick={() => loadData(tgUser?.id || null)} className="ml-4 underline">Повторить</button>
        </div>
      )}

      {/* Tabs - Premium Dark */}
      <div className="flex justify-center mb-10">
        <div className="inline-flex p-1 rounded-xl" style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-6 py-2 text-sm font-semibold rounded-lg transition-all ${tab === t ? 'tab-active' : 'tab-inactive'}`}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {tab === 'Профиль' && master && (
        <div className="card overflow-hidden animate-fade-slide">
          {/* Header - Gold Gradient */}
          <div className="px-8 py-6 flex items-center gap-5" style={{ background: 'linear-gradient(135deg, var(--color-accent) 0%, #b8953f 100%)' }}>
            <button onClick={() => navigate(`/calendar${window.location.search}`)} className="p-2.5 rounded-2xl btn-press" style={{ background: 'rgba(0,0,0,0.2)' }}>
              <ArrowLeft className="w-6 h-6 text-white" />
            </button>
            <h1 className="text-white text-2xl font-bold tracking-tight">Профиль мастера</h1>
          </div>

          <div className="p-4 sm:p-6 md:p-8 space-y-6 sm:space-y-8">
            {/* Avatar Section */}
            <div className="flex flex-col sm:flex-row items-center sm:items-start gap-4 sm:gap-6">
              <div className="relative group">
                {master.avatar_url ? (
                  <img
                    src={resolveMediaUrl(master.avatar_url)}
                    alt="Аватарка"
                    className="w-24 h-24 sm:w-32 sm:h-32 rounded-2xl sm:rounded-3xl object-cover avatar-ring"
                  />
                ) : (
                  <div className="w-32 h-32 rounded-3xl flex items-center justify-center" style={{ background: 'var(--color-accent-light)' }}>
                    <User size={48} style={{ color: 'var(--color-accent)' }} />
                  </div>
                )}
                <button
                  onClick={() => avatarInputRef.current?.click()}
                  disabled={uploadingAvatar || readOnlyDemo}
                  className="absolute -bottom-2 -right-2 p-3 rounded-2xl btn-primary btn-press shadow-lg"
                >
                  {uploadingAvatar ? <span className="text-xs">...</span> : <Camera className="w-5 h-5" />}
                </button>
                <input ref={avatarInputRef} type="file" accept="image/*" onChange={handleAvatarChange} className="hidden" />
              </div>
              <div className="flex-1 w-full space-y-3 text-center md:text-left">
                <h2 className="text-2xl font-extrabold text-left pl-2">{master.name || 'Мастер'}</h2>
                <p className="text-sm text-left pl-2" style={{ color: 'var(--color-text-muted)' }}>Нажмите на иконку для загрузки фото</p>
                <input
                  type="text"
                  value={master.name || ''}
                  onChange={e => { setMaster({ ...master, name: e.target.value.slice(0, 50) }) }}
                  onBlur={() => saveMaster({ name: master.name })}
                  placeholder="Введите имя"
                  maxLength={50}
                  className="w-full text-left pl-2"
                />
              </div>
            </div>

            {!readOnlyDemo && !master.profile_link_warning_dismissed && (
              <div className="profile-link-notice">
                <div className="profile-link-notice-copy">
                  <div className="profile-link-notice-title">Не передавайте ссылку от своего профиля</div>
                  <p className="profile-link-notice-text">
                    По этой ссылке открывается ваш личный кабинет мастера с управлением записями и настройками.
                    Храните её только у себя.
                  </p>
                </div>
                <button
                  type="button"
                  aria-label="Скрыть предупреждение"
                  className="profile-link-notice-close"
                  onClick={() => {
                    setMaster({ ...master, profile_link_warning_dismissed: true })
                    saveMaster({ profile_link_warning_dismissed: true })
                  }}
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}

            <div className="space-y-5">
              {/* Schedule Settings */}
              <div className="card-elevated p-5">
                <button
                  onClick={() => setShowSchedule(!showSchedule)}
                  className="settings-section-toggle w-full flex justify-between items-start gap-3 cursor-pointer hover:opacity-80 transition-opacity"
                >
                  <div className="settings-section-title-wrap min-w-0 text-left" onClick={(e) => e.stopPropagation()}>
                    <span className="font-bold text-lg block">Расписание работы</span>
                    <span className="settings-section-subtitle">Рабочие дни, время, обед и исключения</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <HelpTooltip title="Расписание и запись">
                      <p><strong>Запись открыта на:</strong> Сколько дней вперёд клиент может выбрать дату. Например, 14 дней — с сегодня и до +14 дней.</p>
                      <p className="mt-2"><strong>Время начала:</strong> Когда вы начинаете работать. Запись возможна только после этого времени.</p>
                      <p className="mt-2"><strong>Время конца:</strong> Когда заканчиваете. Последний слот зависит от времени услуги. Если работаете до 18:00, а услуга 1 час — последний слот в 17:00.</p>
                      <p className="mt-2"><strong>Обед:</strong> Перерыв, когда запись недоступна. Уберите, если не нужен.</p>
                    </HelpTooltip>
                    <ChevronDown className={`w-5 h-5 transition-transform ${showSchedule ? 'rotate-180' : ''}`} style={{ color: 'var(--color-accent)' }} />
                  </div>
                </button>
                {showSchedule && (
                  <div className="mt-5" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <ScheduleEditor
                      schedule={master.schedule || { days: [] }}
                      onSave={(schedule) => saveMaster({ schedule_json: schedule })}
                    />
                  </div>
                )}
              </div>

              {/* Work Mode */}
              <div className="card-elevated p-5">
                <button onClick={() => setShowWorkMode(!showWorkMode)} className="settings-section-toggle w-full flex items-start justify-between gap-3">
                  <div className="settings-section-title-wrap min-w-0 text-left flex-1">
                    <span className="font-bold text-lg block">Режим работы</span>
                    <span className="settings-section-subtitle">Услуги или фиксированные интервалы записи</span>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <HelpTooltip title="Режимы работы">
                      <p><strong>Простой:</strong> Вы указываете интервал (30, 45, 60 минут). У клиента в записях будут доступны слоты этого интервала. Подходит если все ваши услуги одинаковой длительности.</p>
                      <p className="mt-3"><strong>Услуги:</strong> Вы добавляете услуги и указываете время их выполнения. Если услуга занимает 90 минут, а клиент записался на 12:00 — следующий сможет записаться только на 13:30. Клиент может выбрать несколько услуг — время суммируется.</p>
                    </HelpTooltip>
                    <ChevronDown className={`w-5 h-5 transition-transform ${showWorkMode ? 'rotate-180' : ''}`} style={{ color: 'var(--color-accent)' }} />
                  </div>
                </button>
                {showWorkMode && (
                  <div className="mt-5 pt-5" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div className="flex items-center gap-4">
                      <div>
                        <p className="font-semibold">{master.use_services ? 'Режим услуг' : 'Режим интервалов'}</p>
                        <p className="text-xs mt-1" style={{ color: 'var(--color-text-muted)' }}>{master.use_services ? 'Услуги с ценой и длительностью' : 'Фиксированная длительность записи'}</p>
                      </div>
                      <div className="relative inline-block w-11 h-6 align-middle select-none ml-auto">
                        <input
                          id="use-services-toggle"
                          checked={master.use_services || false}
                          onChange={(e) => {
                            setMaster({ ...master, use_services: e.target.checked })
                            saveMaster({ use_services: e.target.checked })
                          }}
                          className="toggle-checkbox absolute block w-5 h-5 mt-0.5 rounded-full bg-white border-none appearance-none cursor-pointer z-10"
                          type="checkbox"
                        />
                        <label className="toggle-label block overflow-hidden h-6 rounded-full cursor-pointer" onClick={() => document.getElementById('use-services-toggle')?.click()} />
                      </div>
                    </div>
                    <p className="text-xs mt-3" style={{ color: 'var(--color-text-muted)' }}>При смене режима существующие записи сохраняются без изменений.</p>
                  </div>
                )}
              </div>

              {/* Services or interval */}
              {!master.use_services && (
                <div className="card-elevated p-5">
                  <button onClick={() => setShowServices(!showServices)} className="settings-section-toggle w-full flex items-start justify-between gap-3">
                    <div className="settings-section-title-wrap min-w-0 text-left">
                      <span className="font-bold text-lg block">Интервалы</span>
                      <span className="settings-section-subtitle">Длительность одной стандартной записи</span>
                    </div>
                    <ChevronDown className={`w-5 h-5 transition-transform ${showServices ? 'rotate-180' : ''}`} style={{ color: 'var(--color-accent)' }} />
                  </button>
                  {showServices && (
                    <div className="mt-5 pt-5" style={{ borderTop: '1px solid var(--color-border)' }}>
                      <label className="block text-sm font-semibold mb-3">Длительность одной записи</label>
                      <select value={master.interval_minutes || 60} onChange={e => saveMaster({ interval_minutes: parseInt(e.target.value) })} className="w-full">
                        {[15, 30, 45, 60, 90, 120].map(v => <option key={v} value={v}>{v} мин</option>)}
                      </select>
                    </div>
                  )}
                </div>
              )}

              {/* Services */}
              {master.use_services && (
                <div className="card-elevated p-5 max-md:p-4">
                  <button onClick={() => setShowServices(!showServices)} className="settings-section-toggle w-full flex items-start justify-between gap-3">
                    <div className="settings-section-title-wrap min-w-0 text-left">
                      <span className="font-bold text-lg block max-md:text-base">Ваши услуги ({services.length})</span>
                      <span className="settings-section-subtitle max-md:text-[11px]">
                        Настройте название, стоимость и длительность каждой услуги
                      </span>
                    </div>
                    <ChevronDown className={`w-5 h-5 transition-transform ${showServices ? 'rotate-180' : ''}`} style={{ color: 'var(--color-accent)' }} />
                  </button>
                  {showServices && (
                    <div className="mt-4 pt-4" style={{ borderTop: '1px solid var(--color-border)' }}>
                      <div className="space-y-3">
                        {services.length === 0 && (
                          <p className="text-sm py-3 text-center" style={{ color: 'var(--color-text-muted)' }}>Услуги не добавлены</p>
                        )}
                        {services.map(s => (
                          <ServiceItem key={s.id} service={s} onUpdate={handleUpdateService} onDelete={handleDeleteService} />
                        ))}
                      </div>
                      <button onClick={handleAddService} className="w-full sm:w-auto inline-flex items-center justify-center gap-2 font-bold text-sm mt-4 px-4 py-3 rounded-xl border transition-all hover:scale-[1.01]" style={{ color: 'var(--color-accent)', borderColor: 'var(--color-border)', background: 'var(--color-surface)' }}>
                        <Plus className="w-4 h-4" />
                        Добавить услугу
                      </button>
                    </div>
                  )}
                </div>
              )}

              {/* Advanced settings */}
              <div className="card-elevated p-5">
                <button onClick={() => setShowAdvanced(!showAdvanced)} className="settings-section-toggle w-full flex items-start justify-between gap-3">
                  <div className="settings-section-title-wrap min-w-0 text-left">
                    <span className="font-bold text-lg block">Дополнительные настройки</span>
                    <span className="settings-section-subtitle">Часовой пояс, напоминания и отчёты</span>
                  </div>
                  <ChevronDown className={`w-5 h-5 transition-transform ${showAdvanced ? 'rotate-180' : ''}`} style={{ color: 'var(--color-accent)' }} />
                </button>
                {showAdvanced && (
                  <div className="mt-5 pt-5 space-y-4" style={{ borderTop: '1px solid var(--color-border)' }}>
                    <div className="rounded-xl p-4 space-y-3" style={{ background: 'var(--color-surface)' }}>
                      <label className="block font-semibold">Часовой пояс</label>
                      <select value={master.timezone || 'Europe/Moscow'} onChange={e => saveMaster({ timezone: e.target.value })} className="w-full">
                        {RUSSIAN_TIMEZONES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                    </div>
                    <div className="rounded-xl p-4 space-y-3" style={{ background: 'var(--color-surface)' }}>
                      <label className="flex gap-3 items-center text-sm font-medium">
                        <input type="checkbox" checked={master.notify_reminders ?? true} onChange={e => saveMaster({ notify_reminders: e.target.checked })} />
                        За сутки напомнить клиентам о записи
                      </label>
                      <div>
                        <label className="block text-sm font-semibold mb-2">Время напоминания</label>
                        <div>
                          <button
                            type="button"
                            disabled={master.notify_reminders === false}
                            onClick={() => setShowReminderPicker(v => !v)}
                            className="w-full sm:w-56 rounded-xl px-4 py-3 flex items-center justify-between transition-all"
                            style={{
                              background: 'var(--color-surface-elevated)',
                              border: '1px solid var(--color-border)',
                              color: 'var(--color-text)',
                              opacity: master.notify_reminders === false ? 0.45 : 1,
                              cursor: master.notify_reminders === false ? 'not-allowed' : 'pointer',
                            }}
                          >
                            <span className="text-sm font-semibold">{master.reminder_time || '18:00'}</span>
                            <ChevronDown
                              className={`w-4 h-4 transition-transform ${showReminderPicker ? 'rotate-180' : ''}`}
                              style={{ color: 'var(--color-accent)' }}
                            />
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="rounded-xl p-4 space-y-2" style={{ background: 'var(--color-surface)' }}>
                      <label className="flex gap-3 items-center text-sm font-medium">
                        <input type="checkbox" checked={master.weekly_report_enabled || false} onChange={e => saveMaster({ weekly_report_enabled: e.target.checked })} />
                        Отправлять в конце недели отчёт
                      </label>
                      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Отчёт приходит в воскресенье в 18:00 по выбранному часовому поясу.</p>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'Меню бота' && (
        <div className="space-y-6">
          <MenuButtonEditor type="price" label="Прайс" icon="💰" description="Список услуг и цены" buttons={menuButtons} onToggle={handleToggle} onUpdate={handleUpdateContent} uploadFile={uploadFile} />
          <MenuButtonEditor type="faq" label="Частые вопросы" icon="❓" description="Вопросы и ответы" buttons={menuButtons} onToggle={handleToggle} onUpdate={handleUpdateContent} uploadFile={uploadFile} />
          <MenuButtonEditor type="address" label="Адрес" icon="📍" description="Местоположение и карта" buttons={menuButtons} onToggle={handleToggle} onUpdate={handleUpdateContent} uploadFile={uploadFile} />
          <MenuButtonEditor type="portfolio" label="Портфолио" icon="🖼" description="Галерея ваших работ" buttons={menuButtons} onToggle={handleToggle} onUpdate={handleUpdateContent} uploadFile={uploadFile} />
          <CustomButtonsEditor buttons={menuButtons} onUpdate={handleUpdateContent} uploadFile={uploadFile} />
        </div>
      )}

      </div>
  )
}

function MenuButtonEditor({ type, label, icon, description, buttons, onToggle, onUpdate, uploadFile }) {
  const button = buttons[type] || { active: false, content: {} }
  const active = button.active
  const content = button.content || {}
  const [uploading, setUploading] = useState(false)

  async function handleUpload(file) {
    setUploading(true)
    try {
      const url = await uploadFile(file, 'menu')
      if (type === 'portfolio') {
        const photos = [...(content.photos || []), url].slice(0, 10)
        onUpdate(type, { ...content, photos })
      } else if (type === 'address') {
        onUpdate(type, { ...content, photo: url })
      } else if (type === 'custom') {
        const photos = [...(content.photos || []), url].slice(0, 5)
        onUpdate(type, { ...content, photos })
      }
    } catch (e) {
      console.error('Upload error:', e)
    } finally {
      setUploading(false)
    }
  }

  function removePhoto(index) {
    if (type === 'portfolio') {
      onUpdate(type, { ...content, photos: (content.photos || []).filter((_, i) => i !== index) })
    } else if (type === 'address') {
      onUpdate(type, { ...content, photo: null })
    } else if (type === 'custom') {
      onUpdate(type, { ...content, photos: (content.photos || []).filter((_, i) => i !== index) })
    }
  }

  return (
    <div className="card flex flex-col flex-shrink-0">
      <div className="p-5 flex items-center gap-4">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl flex-shrink-0" style={{ background: 'var(--color-accent-light)' }}>{icon}</div>
        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-base leading-tight truncate">{label}</h3>
          <p className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>{description}</p>
        </div>
        <div className="relative inline-block w-10 h-5 align-middle select-none flex-shrink-0">
          <input
            id={`toggle-${type}`}
            checked={active}
            onChange={() => onToggle(type, !active)}
            className="toggle-checkbox absolute block w-4 h-4 mt-0.5 rounded-full bg-white border-none appearance-none cursor-pointer z-10"
            type="checkbox"
          />
          <label className="toggle-label block overflow-hidden h-5 rounded-full cursor-pointer" onClick={() => document.getElementById(`toggle-${type}`)?.click()} />
        </div>
      </div>
      {active && (
        <div className="px-5 pb-5 pt-4 space-y-4 border-t" style={{ borderColor: 'var(--color-border)' }}>
          {type === 'portfolio' && <PortfolioEditor content={content} onUpdate={(c) => onUpdate(type, c)} onUpload={handleUpload} removePhoto={removePhoto} uploading={uploading} />}
          {type === 'price' && <PriceEditor content={content} onUpdate={(c) => onUpdate(type, c)} buttons={buttons} onToggle={onToggle} />}
          {type === 'faq' && <FAQEditor content={content} onUpdate={(c) => onUpdate(type, c)} />}
          {type === 'address' && <AddressEditor content={content} onUpdate={(c) => onUpdate(type, c)} onUpload={handleUpload} removePhoto={removePhoto} uploading={uploading} />}
          {type === 'custom' && <CustomEditor content={content} onUpdate={(c) => onUpdate(type, c)} onUpload={handleUpload} removePhoto={removePhoto} uploading={uploading} />}
        </div>
      )}
    </div>
  )
}

function PortfolioEditor({ content, onUpdate, onUpload, removePhoto, uploading }) {
  const photoInputRef = useRef(null)

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div>
      <div className="flex justify-between items-center mb-4">
        <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>Фотографии ({(content.photos?.length || 0)}/10)</label>
      </div>
      <div className="grid grid-cols-4 gap-4">
        {(content.photos || []).map((photo, i) => (
          <div key={i} className="relative aspect-square rounded-2xl overflow-hidden" style={{ background: 'var(--color-surface-elevated)' }}>
            <img src={resolveMediaUrl(photo)} alt="" className="w-full h-full object-cover" />
            <button onClick={() => removePhoto(i)} className="absolute top-2 right-2 p-2 rounded-lg transition-colors btn-press" style={{ background: 'rgba(0,0,0,0.5)', color: 'var(--color-error)' }}>
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
        {(content.photos?.length || 0) < 10 && (
          <div className="relative">
            <label className="aspect-square border-2 border-dashed rounded-2xl flex flex-col items-center justify-center cursor-pointer transition-all group" style={{ borderColor: 'var(--color-border)' }}>
              {uploading ? (
                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>...</span>
              ) : (
                <>
                  <div className="w-8 h-8 rounded-full flex items-center justify-center mb-1 group-hover:opacity-80 transition-colors" style={{ background: 'var(--color-accent-light)' }}>
                    <Plus className="w-5 h-5" style={{ color: 'var(--color-accent)' }} />
                  </div>
                  <span className="text-[10px] font-bold uppercase tracking-tight" style={{ color: 'var(--color-text-muted)' }}>Добавить</span>
                </>
              )}
            </label>
            <input onChange={handleFileChange} accept="image/*" className="absolute top-0 left-0 w-full h-full opacity-0 cursor-pointer" type="file" disabled={uploading} />
          </div>
        )}
      </div>
    </div>
  )
}

function PriceEditor({ content, onUpdate }) {
  const [items, setItems] = useState(content.items || [])

  useEffect(() => { setItems(content.items || []) }, [content.items])

  function addItem() {
    const newItems = [...items, { name: '', price: '' }]
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  function updateItem(i, field, val) {
    const newItems = items.map((x, idx) => idx === i ? { ...x, [field]: val } : x)
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  function removeItem(i) {
    const newItems = items.filter((_, idx) => idx !== i)
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  return (
    <div className="space-y-3">
      <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>Список услуг</p>
      <div className="space-y-2">
        {items.length === 0 && <p className="text-sm py-2" style={{ color: 'var(--color-text-muted)' }}>Нажмите "Добавить услугу"</p>}
        {items.map((item, i) => (
          <PriceItem key={i} item={item} index={i} onUpdate={updateItem} onDelete={removeItem} />
        ))}
      </div>
      <button onClick={addItem} className="flex items-center gap-2 font-bold text-sm hover:underline" style={{ color: 'var(--color-accent)' }}>
        <Plus className="w-4 h-4" />
        Добавить услугу
      </button>
    </div>
  )
}

function FAQEditor({ content, onUpdate }) {
  const [items, setItems] = useState(content.items || [])

  useEffect(() => { setItems(content.items || []) }, [content.items])

  function addItem() {
    const newItems = [...items, { question: '', answer: '' }]
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  function updateItem(i, field, val) {
    const newItems = items.map((x, idx) => idx === i ? { ...x, [field]: val } : x)
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  function removeItem(i) {
    const newItems = items.filter((_, idx) => idx !== i)
    setItems(newItems)
    onUpdate({ items: newItems })
  }

  return (
    <div className="space-y-6">
      {items.map((item, i) => (
        <FAQItem key={i} item={item} index={i} onUpdate={updateItem} onDelete={removeItem} />
      ))}
      <button onClick={addItem} className="flex items-center gap-2 font-bold text-sm hover:underline" style={{ color: 'var(--color-accent)' }}>
        <Plus className="w-5 h-5" />
        Добавить вопрос
      </button>
    </div>
  )
}

function AddressEditor({ content, onUpdate, onUpload, removePhoto, uploading }) {
  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="space-y-6">
      <div>
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Точный адрес</label>
        <textarea
          value={content.text || ''}
          onChange={e => onUpdate({ text: e.target.value })}
          placeholder="г. Москва, ул. Примерная, д. 42"
          rows={3}
          className="w-full resize-none"
        />
      </div>
      <div>
        <div className="flex justify-between items-center mb-2">
          <label className="text-xs font-semibold uppercase tracking-wider" style={{ color: 'var(--color-text-muted)' }}>Фото</label>
        </div>
        {content.photo ? (
          <div className="relative w-40 h-40 mx-auto rounded-2xl overflow-hidden" style={{ background: 'var(--color-surface)' }}>
            <img src={resolveMediaUrl(content.photo)} alt="" className="w-full h-full object-cover" />
            <button onClick={() => removePhoto(0)} className="absolute top-2 right-2 p-1.5 rounded-lg transition-colors btn-press" style={{ background: 'rgba(0,0,0,0.5)', color: 'var(--color-error)' }}>
              <X className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <label className="w-40 h-40 mx-auto border-2 border-dashed rounded-2xl flex flex-col items-center justify-center cursor-pointer transition-all group relative" style={{ borderColor: 'var(--color-border)' }}>
            {uploading ? (
              <span className="text-sm" style={{ color: 'var(--color-text-muted)' }}>...</span>
            ) : (
              <>
                <div className="w-12 h-12 rounded-full flex items-center justify-center mb-3" style={{ background: 'var(--color-surface)' }}>
                  <LucideImage className="w-6 h-6" style={{ color: 'var(--color-text-muted)' }} />
                </div>
                <span className="text-sm font-semibold" style={{ color: 'var(--color-text-secondary)' }}>Загрузить</span>
              </>
            )}
            <input onChange={handleFileChange} accept="image/*" className="absolute inset-0 w-full h-full opacity-0 cursor-pointer" type="file" disabled={uploading} />
          </label>
        )}
      </div>
    </div>
  )
}

function CustomEditor({ content, onUpdate, onUpload, removePhoto, uploading }) {
  const [showEmoji, setShowEmoji] = useState(false)
  function addText() {
    onUpdate({ ...content, texts: [...(content.texts || []), ''] })
  }

  function updateText(i, val) {
    onUpdate({ ...content, texts: (content.texts || []).map((x, idx) => idx === i ? val : x) })
  }

  function removeText(i) {
    onUpdate({ ...content, texts: (content.texts || []).filter((_, idx) => idx !== i) })
  }

  function addLink() {
    onUpdate({ ...content, links: [...(content.links || []), { text: '', url: '' }] })
  }

  function updateLink(i, field, val) {
    onUpdate({ ...content, links: (content.links || []).map((x, idx) => idx === i ? { ...x, [field]: val } : x) })
  }

  function removeLink(i) {
    onUpdate({ ...content, links: (content.links || []).filter((_, idx) => idx !== i) })
  }

  function handleFileChange(e) {
    const file = e.target.files?.[0]
    if (file) onUpload(file)
    e.target.value = ''
  }

  return (
    <div className="space-y-6">
      <div className="relative">
        <label className="text-xs font-semibold uppercase tracking-wider block mb-2" style={{ color: 'var(--color-text-muted)' }}>Название кнопки</label>
        <div className="relative">
          <input
            type="text"
            value={content.name || ''}
            onChange={e => onUpdate({ ...content, name: e.target.value })}
            placeholder="Например: Мои работы, Отзывы"
            className="w-full pr-16"
          />
          <button onClick={() => setShowEmoji(!showEmoji)} type="button" className="absolute right-2 top-1/2 -translate-y-1/2 px-2 py-1 rounded" style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
            {content.icon || '😀'}
          </button>
          {showEmoji && (
            <EmojiPicker onSelect={(e) => { onUpdate({ ...content, icon: e }) ; setShowEmoji(false) }} onClose={() => setShowEmoji(false)} />
          )}
        </div>
      </div>
      <div className="space-y-4">
        <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Текстовые блоки</span>
          <button onClick={addText} className="text-xs font-bold flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors btn-ghost" style={{ color: 'var(--color-accent)' }}>
            <Plus className="w-3.5 h-3.5" />
            Добавить
          </button>
        </div>
        {(content.texts || []).map((text, i) => (
          <div key={i} className="space-y-2">
            <TextWithEmoji
              value={text}
              onChange={val => updateText(i, val)}
              placeholder="Текст..."
              rows={2}
            />
            <div className="flex justify-end">
              <button onClick={() => removeText(i)} className="p-2 rounded-lg transition-colors btn-ghost flex-shrink-0" style={{ color: 'var(--color-error)' }}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>
        ))}

        <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Фотографии ({(content.photos?.length || 0)}/5)</span>
          <label className="text-xs font-bold flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors cursor-pointer btn-ghost" style={{ color: 'var(--color-accent)' }}>
            <Plus className="w-3.5 h-3.5" />
            Добавить
            <input type="file" accept="image/*" className="hidden" onChange={handleFileChange} disabled={uploading} />
          </label>
        </div>
        <div className="grid grid-cols-5 gap-3">
          {(content.photos || []).map((photo, i) => (
            <div key={i} className="relative aspect-square rounded-xl overflow-hidden" style={{ background: 'var(--color-surface)' }}>
              <img src={resolveMediaUrl(photo)} alt="" className="w-full h-full object-cover" />
              <button onClick={() => removePhoto(i)} className="absolute top-1 right-1 p-1.5 rounded-lg transition-colors btn-press" style={{ background: 'rgba(0,0,0,0.5)', color: 'var(--color-error)' }}>
                <X className="w-4 h-4" />
              </button>
            </div>
          ))}
        </div>

        <div className="flex justify-between items-center py-2" style={{ borderBottom: '1px solid var(--color-border-subtle)' }}>
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-secondary)' }}>Ссылки</span>
          <button onClick={addLink} className="text-xs font-bold flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors btn-ghost" style={{ color: 'var(--color-accent)' }}>
            <Plus className="w-3.5 h-3.5" />
            Добавить
          </button>
        </div>
        {(content.links || []).map((link, i) => (
          <div key={i} className="p-3 rounded-xl space-y-2" style={{ background: 'var(--color-surface)' }}>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={link.text}
                onChange={e => updateLink(i, 'text', e.target.value)}
                placeholder="Текст ссылки"
                className="flex-1"
              />
              <button onClick={() => removeLink(i)} className="p-2 rounded-lg transition-colors btn-ghost flex-shrink-0" style={{ color: 'var(--color-error)' }}>
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={link.url}
                onChange={e => updateLink(i, 'url', e.target.value)}
                onBlur={async e => {
                  const url = e.target.value
                  if (url.startsWith('http') && url.length > 50) {
                    try {
                      const result = await shortenUrl(url)
                      updateLink(i, 'url', `${window.location.origin}/s/${result.code}`)
                    } catch {}
                  }
                }}
                placeholder="https://..."
                className="flex-1"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function CustomButtonsEditor({ buttons, onUpdate, uploadFile }) {
  const customButtons = buttons.custom?.content?.custom_buttons || buttons.custom_buttons || []
  const [uploading, setUploading] = useState({})

  function addButton() {
    if (customButtons.length >= 3) return
    onUpdate('custom', { custom_buttons: [...customButtons, { name: '', icon: '', texts: [], photos: [], links: [], active: true }] })
  }

  function updateButton(index, data) {
    const newButtons = customButtons.map((b, i) => i === index ? { ...b, ...data } : b)
    onUpdate('custom', { custom_buttons: newButtons })
  }

  function deleteButton(index) {
    const newButtons = customButtons.filter((_, i) => i !== index)
    onUpdate('custom', { custom_buttons: newButtons })
  }

  function handleUpload(file, btnIndex) {
    setUploading(prev => ({ ...prev, [btnIndex]: true }))
    uploadFile(file, 'menu').then(url => {
      const photos = [...(customButtons[btnIndex].photos || []), url].slice(0, 3)
      updateButton(btnIndex, { photos })
      setUploading(prev => ({ ...prev, [btnIndex]: false }))
    }).catch(() => setUploading(prev => ({ ...prev, [btnIndex]: false })))
  }

  return (
    <div className="card">
      <div className="p-5 flex items-center gap-4">
        <div className="w-10 h-10 rounded-xl flex items-center justify-center text-xl flex-shrink-0" style={{ background: 'var(--color-accent-light)' }}>💬</div>
        <div className="flex-1 min-w-0">
          <h3 className="font-bold text-base leading-tight">Кастомные кнопки</h3>
          <p className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>До 3 дополнительных разделов меню</p>
        </div>
        <span className="text-xs font-medium px-2 py-1 rounded-full" style={{ background: 'var(--color-surface-elevated)', color: 'var(--color-text-muted)' }}>
          {customButtons.length}/3
        </span>
      </div>
      <div className="px-5 pb-5 pt-4 border-t space-y-4" style={{ borderColor: 'var(--color-border)' }}>
        {customButtons.map((btn, i) => (
          <CustomButtonItem
            key={i}
            button={btn}
            index={i}
            onUpdate={updateButton}
            onDelete={deleteButton}
            onUpload={(file) => handleUpload(file, i)}
            uploading={uploading[i]}
          />
        ))}
        {customButtons.length < 3 && (
          <button onClick={addButton} className="w-full py-3 rounded-xl border-2 border-dashed flex items-center justify-center gap-2 font-medium transition-all hover:border-[var(--color-accent)]" style={{ borderColor: 'var(--color-border)', color: 'var(--color-text-secondary)' }}>
            <Plus className="w-5 h-5" />
            Добавить кнопку
          </button>
        )}
      </div>
    </div>
  )
}

const DAYS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']

function ScheduleEditor({ schedule, onSave }) {
  const [days, setDays] = useState(schedule.days || [])
  const [bookingDays, setBookingDays] = useState(schedule.booking_days || 90)
  const [exceptions, setExceptions] = useState(schedule.exceptions || [])
  const [exceptionStart, setExceptionStart] = useState('')
  const [exceptionEnd, setExceptionEnd] = useState('')
  const [openTimePicker, setOpenTimePicker] = useState(null)
  const saveTimeoutRef = useRef(null)
  const pickerRef = useRef(null)

  useEffect(() => {
    function handleClick(e) {
      if (!openTimePicker) return

      const picker = pickerRef.current
      if (!picker) { setOpenTimePicker(null); return }

      // Click on backdrop closes picker
      if (e.target === picker) {
        setOpenTimePicker(null)
        return
      }

      // Click on time cell buttons - don't close
      const isTimeCell = e.target.closest('[data-time-cell]')
      if (isTimeCell) return

      // Click outside picker content closes
      if (!picker.contains(e.target)) setOpenTimePicker(null)
    }
    if (openTimePicker) {
      setTimeout(() => document.addEventListener('click', handleClick), 0)
    }
    return () => document.removeEventListener('click', handleClick)
  }, [openTimePicker])

  const toggleDay = (index) => {
    const newDays = [...days]
    newDays[index] = { ...newDays[index], active: !newDays[index]?.active }
    setDays(newDays)
    scheduleAutoSave(newDays)
  }

  const updateDay = (index, field, value) => {
    const newDays = [...days]
    newDays[index] = { ...newDays[index], [field]: value }
    setDays(newDays)
    scheduleAutoSave(newDays)
  }

  const toggleBreak = (index) => {
    const newDays = [...days]
    const hasBreak = newDays[index]?.break_active !== false
    newDays[index] = { ...newDays[index], break_active: !hasBreak }
    setDays(newDays)
    scheduleAutoSave(newDays)
  }

  const scheduleAutoSave = (newDays) => {
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => {
      onSave({ ...schedule, days: newDays, booking_days: bookingDays, exceptions })
    }, 800)
  }

  const updateBookingDays = (value) => {
    setBookingDays(value)
    if (saveTimeoutRef.current) clearTimeout(saveTimeoutRef.current)
    saveTimeoutRef.current = setTimeout(() => {
      onSave({ ...schedule, days: days, booking_days: value, exceptions })
    }, 800)
  }

  const saveExceptions = (items) => {
    setExceptions(items)
    onSave({ ...schedule, days, booking_days: bookingDays, exceptions: items })
  }

  const addException = () => {
    if (!exceptionStart) return
    const end = exceptionEnd || exceptionStart
    if (end < exceptionStart) return
    saveExceptions([...exceptions, { start: exceptionStart, end }])
    setExceptionStart('')
    setExceptionEnd('')
  }

  const openPicker = (index, field) => {
    setOpenTimePicker({ index, field })
  }

  const selectTime = (time) => {
    if (openTimePicker) {
      updateDay(openTimePicker.index, openTimePicker.field, time)
      setOpenTimePicker(null)
    }
  }

  const timeOptions = Array.from({ length: 48 }, (_, i) => {
    const hour = Math.floor(i / 2)
    const min = (i % 2) * 30
    return `${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}`
  })

  const renderTimeCell = (dayIndex, field, value) => (
    <button
      onClick={() => openPicker(dayIndex, field)}
      data-time-cell
      className="px-2 py-1 rounded-lg text-xs inline-flex flex-nowrap shrink-0 items-center justify-center gap-1 whitespace-nowrap transition-all hover:opacity-80 min-w-[76px] max-md:min-w-[68px] max-md:px-1.5 max-md:py-0.5 max-md:text-[10px]"
      style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}
    >
      <span className="whitespace-nowrap tabular-nums leading-none">{value || 'не указано'}</span>
      <svg className="w-3 h-3 max-md:!w-2.5 max-md:!h-2.5" style={{ color: 'var(--color-text-muted)' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    </button>
  )

  return (
    <div className="space-y-3 pr-2">
      {openTimePicker && (
        <div ref={pickerRef} className="fixed inset-0 z-50 flex items-center justify-center time-picker-modal" style={{ backgroundColor: 'rgba(0,0,0,0.7)' }}>
          <div className="rounded-2xl p-4 w-72 max-h-80 overflow-y-auto" style={{ background: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
            <div className="mb-3 pb-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
              <div className="flex items-center justify-between text-xs" style={{ color: 'var(--color-text-muted)' }}>
                <span>Выберите время:</span>
                <button onClick={() => setOpenTimePicker(null)} className="hover:opacity-70">✕</button>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-1">
              <button
                onClick={() => selectTime('')}
                className="col-span-4 px-2 py-1.5 text-xs rounded-lg transition-all hover:opacity-80"
                style={{
                  background: days[openTimePicker.index]?.[openTimePicker.field] === '' ? 'var(--color-accent)' : 'var(--color-surface)',
                  color: days[openTimePicker.index]?.[openTimePicker.field] === '' ? '#0a0a0a' : 'var(--color-text)'
                }}
              >
                Не указано
              </button>
              {timeOptions.map(time => (
                <button
                  key={time}
                  onClick={() => selectTime(time)}
                  className="px-2 py-1.5 text-xs rounded-lg transition-all hover:opacity-80"
                  style={{
                    background: days[openTimePicker.index]?.[openTimePicker.field] === time ? 'var(--color-accent)' : 'var(--color-surface)',
                    color: days[openTimePicker.index]?.[openTimePicker.field] === time ? '#0a0a0a' : 'var(--color-text)'
                  }}
                >
                  {time}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Header with booking days setting */}
      <div className="p-4 rounded-2xl" style={{ background: 'var(--color-surface)' }}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium" style={{ color: 'var(--color-text-muted)' }}>Запись открыта на:</span>
          <span className="text-sm font-bold" style={{ color: 'var(--color-accent)' }}>{bookingDays} дней</span>
        </div>
        <input
          type="range"
          min="1"
          max="90"
          value={bookingDays}
          onChange={(e) => updateBookingDays(parseInt(e.target.value))}
          className="w-full h-2 rounded-lg appearance-none cursor-pointer"
          style={{
            background: `linear-gradient(to right, var(--color-accent) 0%, var(--color-accent) ${(bookingDays - 1) / 89 * 100}%, var(--color-border) ${(bookingDays - 1) / 89 * 100}%, var(--color-border) 100%)`
          }}
        />
      </div>

      <div className="p-4 rounded-2xl" style={{ background: 'var(--color-surface)' }}>
        <p className="text-sm font-medium mb-2">Недоступные даты</p>
        <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>Исключите один день или диапазон дат из онлайн-записи.</p>
        <div className="grid grid-cols-2 gap-2">
          <input type="date" value={exceptionStart} onChange={e => setExceptionStart(e.target.value)} aria-label="Начало диапазона" />
          <input type="date" value={exceptionEnd} min={exceptionStart} onChange={e => setExceptionEnd(e.target.value)} aria-label="Конец диапазона" />
        </div>
        <button onClick={addException} disabled={!exceptionStart} className="btn-primary w-full mt-2 py-2 rounded-xl text-sm font-semibold disabled:opacity-50">
          Добавить исключение
        </button>
        {exceptions.length > 0 && (
          <div className="space-y-2 mt-3">
            {exceptions.map((item, index) => {
              const start = typeof item === 'string' ? item : (item.start || item.date)
              const end = typeof item === 'string' ? item : (item.end || start)
              return (
                <div key={`${start}-${end}-${index}`} className="flex items-center justify-between gap-2 text-sm">
                  <span>{start === end ? start : `${start} - ${end}`}</span>
                  <button onClick={() => saveExceptions(exceptions.filter((_, itemIndex) => itemIndex !== index))} aria-label="Удалить исключение" className="p-1">
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {DAYS.map((dayName, i) => {
        const day = days[i] || { day: dayName, active: false, work_start: '09:00', work_end: '18:00', break_start: '13:00', break_end: '14:00', break_active: true }
        const dayData = { ...day, day: dayName }

        return (
          <div key={dayName} className="p-4 rounded-2xl max-md:p-3" style={{ background: 'var(--color-surface)' }}>
            <div className="flex items-center gap-2 flex-wrap max-md:gap-1.5">
              <button
                onClick={() => toggleDay(i)}
                className={`w-6 h-6 rounded-lg flex items-center justify-center transition-all btn-press flex-shrink-0 max-md:w-5 max-md:h-5 ${dayData.active ? 'btn-primary' : ''}`}
                style={!dayData.active ? { border: '2px solid var(--color-border)' } : {}}
              >
                {dayData.active && <Check className="w-3.5 h-3.5 max-md:!w-3 max-md:!h-3" />}
              </button>
              <span className="w-10 text-sm font-semibold max-md:text-xs max-md:w-8">{dayName}</span>
              {dayData.active ? (
                <>
                  <div className="flex items-center gap-1 max-md:gap-0.5">
                    <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>с</span>
                    {renderTimeCell(i, 'work_start', dayData.work_start)}
                  </div>
                  <div className="flex items-center gap-1 max-md:gap-0.5">
                    <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>до</span>
                    {renderTimeCell(i, 'work_end', dayData.work_end)}
                  </div>
                  <div className="h-5 w-px mx-1 max-md:mx-0.5 max-md:!h-4" style={{ background: 'var(--color-border)' }} />
                  <div className="flex items-center gap-1 max-md:gap-0.5">
                    <button
                      onClick={() => toggleBreak(i)}
                      className={`w-4 h-4 rounded flex items-center justify-center text-xs flex-shrink-0 max-md:w-3.5 max-md:h-3.5 ${dayData.break_active !== false ? 'btn-primary' : ''}`}
                      style={dayData.break_active === false ? { border: '1px solid var(--color-border)' } : {}}
                    >
                      {dayData.break_active !== false && <Check className="w-2.5 h-2.5 max-md:!w-2 max-md:!h-2" />}
                    </button>
                    <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>Обед</span>
                  </div>
                  {dayData.break_active !== false && (
                    <>
                      <div className="flex items-center gap-1 max-md:gap-0.5">
                        <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>c</span>
                        {renderTimeCell(i, 'break_start', dayData.break_start)}
                      </div>
                      <div className="flex items-center gap-1 max-md:gap-0.5">
                        <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>до</span>
                        {renderTimeCell(i, 'break_end', dayData.break_end)}
                      </div>
                    </>
                  )}
                </>
              ) : (
                <span className="text-xs max-md:text-[10px]" style={{ color: 'var(--color-text-muted)' }}>выходной</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
