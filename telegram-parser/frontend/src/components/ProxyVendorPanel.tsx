/* Vendor (proxy6.net) panel + bulk-paste textarea for the Proxies page.

The panel renders:

* the operator's proxy6.net balance (with a refresh button);
* a "Импортировать всё" button that pulls the vendor's owned list
  into the local ``proxies`` table (idempotent — refresh, not
  duplicate);
* a buy form with country / count / period / version / type and
  a "confirm" checkbox. The form is disabled until the operator
  ticks the confirmation (real money is being spent);
* a paste textarea that accepts a multi-line blob in any of the
  formats documented in :mod:`app.services.proxy_service`.

Splitting this into a separate file keeps :mod:`Proxies` small
(726 lines already) and lets us add a "Все" tab on the Proxies
page without touching its main grid.
*/
import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import api from '../services/api'
import {
  X,
  Wallet,
  Clipboard,
  ShoppingCart,
  ArrowsClockwise,
  CircleNotch,
  CheckCircle,
  Warning,
  GlobeHemisphereWest,
  Tag
} from '@phosphor-icons/react'

const COUNTRY_NAMES: Record<string, string> = {
  us: 'США', ru: 'Россия', ua: 'Украина', kz: 'Казахстан', by: 'Беларусь',
  de: 'Германия', fr: 'Франция', gb: 'Великобритания', nl: 'Нидерланды',
  lv: 'Латвия', lt: 'Литва', ee: 'Эстония', pl: 'Польша', tr: 'Турция',
  ca: 'Канада', id: 'Индонезия',
  se: 'Швеция', fi: 'Финляндия', no: 'Норвегия', dk: 'Дания',
  at: 'Австрия', ch: 'Швейцария', it: 'Италия', es: 'Испания', pt: 'Португалия',
  ro: 'Румыния', bg: 'Болгария', hu: 'Венгрия', cz: 'Чехия', sk: 'Словакия',
  hr: 'Хорватия', rs: 'Сербия', gr: 'Греция', si: 'Словения',
  md: 'Молдова', ge: 'Грузия', am: 'Армения', az: 'Азербайджан',
  uz: 'Узбекистан', tj: 'Таджикистан', kg: 'Кыргызстан', tm: 'Туркменистан',
  jp: 'Япония', kr: 'Юж. Корея', cn: 'Китай', sg: 'Сингапур', hk: 'Гонконг',
  th: 'Таиланд', vn: 'Вьетнам', my: 'Малайзия', ph: 'Филиппины', in: 'Индия',
  au: 'Австралия', nz: 'Новая Зеландия',
  br: 'Бразилия', mx: 'Мексика', ar: 'Аргентина', co: 'Колумбия',
  za: 'ЮАР', ng: 'Нигерия', eg: 'Египет', ma: 'Марокко',
  il: 'Израиль', ae: 'ОАЭ', sa: 'Саудовская Аравия',
  mn: 'Монголия',
}

interface Balance {
  user_id: string
  email: string
  balance: number
  balance_ref: number
  currency: string
  balance_str: string
}

export function ProxyVendorPanel({ onAfterImport }: { onAfterImport?: () => void }) {
  const [open, setOpen] = useState(false)
  const [balance, setBalance] = useState<Balance | null>(null)
  const [balanceErr, setBalanceErr] = useState('')
  const [loadingBalance, setLoadingBalance] = useState(false)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [pasteText, setPasteText] = useState('')
  const [pasteReport, setPasteReport] = useState<any>(null)
  const [pasteErr, setPasteErr] = useState('')
  const [pasteBusy, setPasteBusy] = useState(false)

  // Buy form
  const [buyCountry, setBuyCountry] = useState('us')
  const [buyCount, setBuyCount] = useState('1')
  const [buyPeriod, setBuyPeriod] = useState('30')
  const [buyVersion, setBuyVersion] = useState('4')
  const [countries, setCountries] = useState<string[]>([])
  const [countriesBusy, setCountriesBusy] = useState(false)
  const [buyConfirm, setBuyConfirm] = useState(false)
  const [buyBusy, setBuyBusy] = useState(false)
  const [buyErr, setBuyErr] = useState('')
  const [buyResult, setBuyResult] = useState<any>(null)

  // Import-all
  const [importingAll, setImportingAll] = useState(false)
  const [importAllErr, setImportAllErr] = useState('')
  const [importAllResult, setImportAllResult] = useState<any>(null)

  const loadBalance = async () => {
    setLoadingBalance(true)
    setBalanceErr('')
    try {
      const res = await api.get('/api/v1/proxy-vendor/balance')
      setBalance(res.data)
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setBalanceErr(typeof detail === 'string' ? detail : 'Не удалось получить баланс')
    } finally {
      setLoadingBalance(false)
    }
  }

  useEffect(() => {
    if (open && !balance) loadBalance()
  }, [open])

  const loadCountries = async (version = buyVersion) => {
    setCountriesBusy(true)
    try {
      const res = await api.get('/api/v1/proxy-vendor/countries', { params: { version } })
      const list = Array.isArray(res.data?.countries) ? res.data.countries : []
      setCountries(list)
      if (list.length > 0 && !list.includes(buyCountry)) {
        setBuyCountry(list.includes('us') ? 'us' : list[0])
      }
    } catch (e) {
      console.error('Не удалось получить страны proxy6', e)
      setCountries([])
    } finally {
      setCountriesBusy(false)
    }
  }

  useEffect(() => {
    if (open) loadCountries(buyVersion)
  }, [open, buyVersion])

  const importAll = async () => {
    setImportingAll(true)
    setImportAllErr('')
    setImportAllResult(null)
    try {
      const res = await api.post('/api/v1/proxy-vendor/import-all')
      setImportAllResult(res.data)
      onAfterImport?.()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setImportAllErr(typeof detail === 'string' ? detail : 'Не удалось импортировать')
    } finally {
      setImportingAll(false)
    }
  }

  const buy = async () => {
    setBuyErr('')
    setBuyResult(null)
    if (!buyConfirm) {
      setBuyErr('Поставьте галочку «Подтверждаю покупку» — функция тратит реальные деньги.')
      return
    }
    setBuyBusy(true)
    try {
      const res = await api.post('/api/v1/proxy-vendor/buy', {
        country: buyCountry,
        count: Number(buyCount),
        period: Number(buyPeriod),
        version: buyVersion,
        type_: 'socks',
        confirm: true,
        auto_import: true,
      })
      setBuyResult(res.data)
      onAfterImport?.()
      loadBalance()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setBuyErr(typeof detail === 'string' ? detail : 'Ошибка покупки')
    } finally {
      setBuyBusy(false)
    }
  }

  const paste = async () => {
    if (!pasteText.trim()) {
      setPasteErr('Вставьте хотя бы одну строку')
      return
    }
    setPasteBusy(true)
    setPasteErr('')
    setPasteReport(null)
    try {
      const res = await api.post('/api/v1/proxies/paste', {
        text: pasteText,
        default_source: 'pasted',
      })
      setPasteReport(res.data)
      if (res.data?.imported > 0) onAfterImport?.()
    } catch (e: any) {
      const detail = e.response?.data?.detail
      setPasteErr(typeof detail === 'string' ? detail : 'Ошибка вставки')
    } finally {
      setPasteBusy(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => setPasteOpen(true)}
        title="Вставить прокси: host:port:user:pass построчно"
        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-border hover:bg-muted transition-colors font-medium"
      >
        <Clipboard size={18} />
        Paste
      </button>
      <button
        onClick={() => setOpen(true)}
        title="proxy6.net: баланс, покупка, импорт"
        className="inline-flex items-center gap-2 px-4 py-2.5 rounded-xl border border-primary/40 text-primary hover:bg-primary/10 transition-colors font-medium"
      >
        <Wallet size={18} weight="duotone" />
        Vendor
      </button>

      {/* Vendor modal */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            onClick={() => setOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-6 border-b border-border/50">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Wallet size={22} weight="duotone" />
                  proxy6.net
                </h2>
                <button onClick={() => setOpen(false)} className="p-2 rounded-xl hover:bg-muted">
                  <X size={20} />
                </button>
              </div>

              <div className="p-6 space-y-6">
                {/* Balance */}
                <div className="rounded-2xl border border-border/50 p-4 bg-muted/30">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs text-muted-foreground">Баланс</p>
                      {loadingBalance ? (
                        <p className="text-2xl font-bold flex items-center gap-2">
                          <CircleNotch size={18} className="animate-spin" /> ...
                        </p>
                      ) : balance ? (
                        <p className="text-2xl font-bold">{balance.balance_str}</p>
                      ) : (
                        <p className="text-sm text-red-500">{balanceErr || '—'}</p>
                      )}
                      {balance && (
                        <p className="text-xs text-muted-foreground">
                          {balance.email} · uid {balance.user_id}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={loadBalance}
                      className="p-2 rounded-xl border border-border hover:bg-muted"
                      title="Обновить баланс"
                    >
                      <ArrowsClockwise size={18} />
                    </button>
                  </div>
                </div>

                {/* Import all */}
                <div className="rounded-2xl border border-border/50 p-4">
                  <h3 className="text-sm font-medium mb-2">Импортировать всё из proxy6.net</h3>
                  <p className="text-xs text-muted-foreground mb-3">
                    Перенесёт все купленные прокси в локальную базу. Дубликаты по vendor_id обновятся,
                    не создадутся повторно.
                  </p>
                  <button
                    onClick={importAll}
                    disabled={importingAll}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border hover:bg-muted disabled:opacity-50"
                  >
                    {importingAll ? <CircleNotch size={16} className="animate-spin" /> : <GlobeHemisphereWest size={16} />}
                    {importingAll ? 'Импорт…' : 'Импортировать'}
                  </button>
                  {importAllErr && (
                    <p className="text-sm text-red-500 mt-2">{importAllErr}</p>
                  )}
                  {importAllResult && (
                    <p className="text-sm text-emerald-600 mt-2 flex items-center gap-1">
                      <CheckCircle size={16} weight="bold" />
                      Импортировано {importAllResult.imported}, обновлено {importAllResult.updated}
                    </p>
                  )}
                </div>

                {/* Buy form */}
                <div className="rounded-2xl border border-amber-500/40 bg-amber-500/5 p-4">
                  <h3 className="text-sm font-medium flex items-center gap-2 mb-2">
                    <ShoppingCart size={16} weight="bold" />
                    Купить прокси
                    <span className="text-xs text-amber-600 font-normal">(списывает реальные деньги)</span>
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                    <div>
                      <label className="text-xs text-muted-foreground">Страна</label>
                      <select
                        value={buyCountry}
                        onChange={(e) => setBuyCountry(e.target.value)}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background"
                      >
                        {countries.length === 0 && (
                          <option value={buyCountry}>{countriesBusy ? 'Загрузка…' : COUNTRY_NAMES[buyCountry] || buyCountry.toUpperCase()}</option>
                        )}
                        {countries.map((country) => (
                          <option key={country} value={country}>
                            {COUNTRY_NAMES[country] || country.toUpperCase()}
                          </option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">Кол-во</label>
                      <input
                        type="number"
                        min="1"
                        max="100"
                        value={buyCount}
                        onChange={(e) => setBuyCount(e.target.value)}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">Период (дней)</label>
                      <input
                        type="number"
                        min="1"
                        max="365"
                        value={buyPeriod}
                        onChange={(e) => setBuyPeriod(e.target.value)}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background"
                      />
                    </div>
                    <div>
                      <label className="text-xs text-muted-foreground">IP</label>
                      <select
                        value={buyVersion}
                        onChange={(e) => setBuyVersion(e.target.value)}
                        className="w-full mt-1 px-3 py-2 rounded-lg border border-border bg-background"
                      >
                        <option value="4">IPv4</option>
                        <option value="6">IPv6</option>
                      </select>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground mb-3">
                    Покупка ограничена обычными приватными IPv4/IPv6. IPv4 Shared и MTProto заблокированы на backend.
                    Тип подключения: SOCKS5.
                  </p>
                  <label className="flex items-center gap-2 text-sm mb-3 select-none cursor-pointer">
                    <input
                      type="checkbox"
                      checked={buyConfirm}
                      onChange={(e) => setBuyConfirm(e.target.checked)}
                      className="rounded"
                    />
                    <span>Подтверждаю покупку, спишу с баланса proxy6.net</span>
                  </label>
                  <button
                    onClick={buy}
                    disabled={buyBusy || !buyConfirm}
                    className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground disabled:opacity-50"
                  >
                    {buyBusy ? <CircleNotch size={16} className="animate-spin" /> : <ShoppingCart size={16} />}
                    Купить и импортировать
                  </button>
                  {buyErr && <p className="text-sm text-red-500 mt-2">{buyErr}</p>}
                  {buyResult && (
                    <div className="text-sm text-emerald-600 mt-2 space-y-1">
                      <p className="flex items-center gap-1">
                        <CheckCircle size={16} weight="bold" />
                        Куплено {buyResult.bought}, импортировано автоматически: {buyResult.auto_imported ? 'да' : 'нет'}
                      </p>
                      <ul className="text-xs list-disc list-inside text-muted-foreground">
                        {buyResult.proxies?.slice(0, 5).map((p: any, i: number) => (
                          <li key={i}>{p.ip}:{p.port} ({COUNTRY_NAMES[String(p.country || '').toLowerCase()] || p.country}) до {p.date_end?.split('T')[0]}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Paste modal */}
      <AnimatePresence>
        {pasteOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
            onClick={() => setPasteOpen(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              className="bg-card rounded-3xl border border-border shadow-2xl w-full max-w-2xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-6 border-b border-border/50">
                <h2 className="text-xl font-semibold flex items-center gap-2">
                  <Clipboard size={22} />
                  Вставить прокси
                </h2>
                <button onClick={() => setPasteOpen(false)} className="p-2 rounded-xl hover:bg-muted">
                  <X size={20} />
                </button>
              </div>
              <div className="p-6 space-y-4">
                <p className="text-xs text-muted-foreground">
                  По одной строке на прокси. Поддерживаются форматы:
                  <code className="font-mono"> 38.154.19.220:8000:F6keWS:wMSRMa</code>,
                  <code className="font-mono"> socks5://u:p@1.2.3.4:1080</code>,
                  <code className="font-mono"> 1.2.3.4:1080</code>.
                </p>
                <textarea
                  value={pasteText}
                  onChange={(e) => setPasteText(e.target.value)}
                  rows={10}
                  placeholder={'38.154.19.220:8000:F6keWS:wMSRMa\n1.2.3.4:1080\nsocks5://u:p@5.6.7.8:1080'}
                  className="w-full px-3 py-2 rounded-xl border border-border bg-background font-mono text-sm"
                />
                {pasteErr && <p className="text-sm text-red-500">{pasteErr}</p>}
                {pasteReport && (
                  <div className="text-sm bg-emerald-500/10 text-emerald-700 p-3 rounded-xl space-y-1">
                    <p className="flex items-center gap-2 font-medium">
                      <CheckCircle size={16} weight="bold" />
                      Импортировано: {pasteReport.imported}, дубликатов: {pasteReport.duplicates}
                    </p>
                    {pasteReport.errors?.length > 0 && (
                      <details className="text-xs text-amber-700">
                        <summary>Ошибки ({pasteReport.errors.length})</summary>
                        <ul className="list-disc list-inside">
                          {pasteReport.errors.slice(0, 5).map((e: any, i: number) => (
                            <li key={i}>Строка {e.row}: {e.reason}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                )}
                <div className="flex gap-3 pt-2">
                  <button
                    onClick={() => setPasteOpen(false)}
                    className="flex-1 py-3 rounded-xl border border-border hover:bg-muted"
                  >
                    Закрыть
                  </button>
                  <button
                    onClick={paste}
                    disabled={pasteBusy}
                    className="flex-1 py-3 rounded-xl bg-primary text-primary-foreground disabled:opacity-50 flex items-center justify-center gap-2"
                  >
                    {pasteBusy ? <CircleNotch size={16} className="animate-spin" /> : null}
                    {pasteBusy ? 'Импорт…' : 'Импортировать'}
                  </button>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
