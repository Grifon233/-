import { useEffect, useState } from 'react'

const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '')

export default function PaymentResult() {
  const [state, setState] = useState({ loading: true, status: null, error: '' })

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const paymentId = params.get('payment_id') || params.get('payload')
    if (!paymentId) {
      setState({ loading: false, status: null, error: 'Платёж пока обрабатывается. Вернитесь в бот и проверьте подписку через несколько секунд.' })
      return
    }

    fetch(`${API_URL}/api/payments/yookassa/status?payment_id=${encodeURIComponent(paymentId)}`)
      .then(async response => {
        const data = await response.json()
        if (!response.ok) throw new Error(data.detail || 'Не удалось получить статус платежа')
        setState({ loading: false, status: data.status, error: '' })
      })
      .catch(error => setState({ loading: false, status: null, error: error.message }))
  }, [])

  const getText = () => {
    if (state.loading) return 'Проверяем статус оплаты...'
    if (state.status === 'succeeded') return 'Оплата прошла успешно. Подписка уже активируется, можно вернуться в Telegram-бот.'
    if (state.status === 'refunded') return 'По этому платежу оформлен возврат. Подписка больше не активна.'
    if (state.status === 'pending') return 'Платёж ещё обрабатывается. Если вы уже подтвердили оплату, подождите несколько секунд и вернитесь в бота.'
    return state.error || 'Оплата не завершена. Проверьте подписку в боте и при необходимости попробуйте снова.'
  }

  const text = getText()

  return (
    <div className="max-w-xl mx-auto py-16">
      <div className="rounded-3xl p-8" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
        <h1 className="text-2xl font-bold mb-4">Статус оплаты</h1>
        <p className="text-sm leading-7" style={{ color: 'var(--color-text-secondary)' }}>{text}</p>
      </div>
    </div>
  )
}
