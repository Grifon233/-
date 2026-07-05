import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  WarningCircle,
  WarningOctagon,
  Info,
  X,
  ArrowsClockwise,
} from '@phosphor-icons/react'

import { subscribeApiError, type ApiErrorPayload } from '@/services/apiEvents'

const AUTO_DISMISS_MS = 8000

const levelConfig: Record<
  NonNullable<ApiErrorPayload['level']>,
  { icon: typeof WarningCircle; color: string; bg: string; border: string }
> = {
  error: {
    icon: WarningOctagon,
    color: 'text-red-600',
    bg: 'bg-red-500/10',
    border: 'border-red-500/30',
  },
  warning: {
    icon: WarningCircle,
    color: 'text-amber-600',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  info: {
    icon: Info,
    color: 'text-blue-600',
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
  },
}

interface BannerItem extends ApiErrorPayload {
  /** Unique id so AnimatePresence can animate exit transitions. */
  id: string
}

let idCounter = 0
function nextId() {
  idCounter += 1
  return `api-error-${idCounter}`
}

export default function ApiErrorBanner() {
  const [banners, setBanners] = useState<BannerItem[]>([])

  useEffect(() => {
    return subscribeApiError((payload) => {
      const id = nextId()
      setBanners((current) => [...current, { ...payload, id }])
      // Auto-dismiss non-critical errors after a short delay.
      const level = payload.level ?? 'error'
      if (level !== 'error') {
        window.setTimeout(() => {
          setBanners((current) => current.filter((b) => b.id !== id))
        }, AUTO_DISMISS_MS)
      }
    })
  }, [])

  const dismiss = (id: string) =>
    setBanners((current) => current.filter((b) => b.id !== id))

  const retryAll = () => {
    // The simplest thing we can do is reload the page — every page
    // re-fetches on mount, so a reload retries the most recent
    // requests. This avoids trying to coordinate with the 50+
    // different per-page refetch functions.
    window.location.reload()
  }

  return (
    <div
      className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 max-w-md pointer-events-none"
      aria-live="polite"
    >
      <AnimatePresence initial={false}>
        {banners.map((banner) => {
          const level = banner.level ?? 'error'
          const config = levelConfig[level]
          const Icon = config.icon
          return (
            <motion.div
              key={banner.id}
              layout
              initial={{ opacity: 0, x: 80, scale: 0.95 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 80, scale: 0.95 }}
              transition={{ type: 'spring', stiffness: 320, damping: 30 }}
              className={`pointer-events-auto rounded-2xl border ${config.border} ${config.bg} backdrop-blur-sm shadow-xl p-4`}
            >
              <div className="flex items-start gap-3">
                <Icon size={20} weight="fill" className={`${config.color} mt-0.5 flex-shrink-0`} />
                <div className="flex-1 min-w-0">
                  <p className={`font-semibold text-sm ${config.color}`}>
                    {banner.title}
                    {banner.status != null && (
                      <span className="ml-2 text-xs font-mono opacity-70">HTTP {banner.status}</span>
                    )}
                  </p>
                  {banner.detail && (
                    <p className="text-xs text-foreground/80 mt-1 break-words">
                      {banner.detail}
                    </p>
                  )}
                  {banner.request && (
                    <p className="text-[10px] font-mono text-muted-foreground mt-1 truncate">
                      {banner.request}
                    </p>
                  )}
                </div>
                <div className="flex flex-col gap-1">
                  {level === 'error' && (
                    <button
                      onClick={retryAll}
                      className="p-1 rounded-md hover:bg-foreground/10 text-muted-foreground"
                      title="Повторить"
                    >
                      <ArrowsClockwise size={14} />
                    </button>
                  )}
                  <button
                    onClick={() => dismiss(banner.id)}
                    className="p-1 rounded-md hover:bg-foreground/10 text-muted-foreground"
                    title="Закрыть"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
