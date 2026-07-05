import { useEffect, useMemo, useRef, useState } from 'react';

const API_URL = import.meta.env.DEV ? '' : (import.meta.env.VITE_API_URL || '');

function getAuthQuery() {
  const source = new URLSearchParams(window.location.search);
  const auth = new URLSearchParams();
  ['user', 'user_id', 'auth_ts', 'username', 'name', 'sig'].forEach(key => {
    if (source.get(key)) auth.set(key, source.get(key));
  });
  return auth.toString();
}

async function request(path, options = {}) {
  const auth = getAuthQuery();
  const separator = path.includes('?') ? '&' : '?';
  const response = await fetch(`${API_URL}${path}${auth ? separator + auth : ''}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Ошибка запроса');
  return data;
}

const dateTime = value => value ? new Date(value).toLocaleString('ru-RU') : '—';
const dateOnly = value => value ? new Date(value).toLocaleDateString('ru-RU') : '—';
const money = value => `${Number(value || 0).toLocaleString('ru-RU')} ₽`;
const externalHref = value => {
  const link = String(value || '').trim();
  if (!link) return '';
  return /^https?:\/\//i.test(link) ? link : `https://${link}`;
};

const STATUS_LABELS = {
  active: 'Активна',
  running: 'Работает',
  upcoming: 'Предстоит',
  confirmed: 'Подтверждена',
  pending: 'Ожидает оплаты',
  frozen: 'Заморожена',
  expired: 'Истекла',
  refunded: 'Возвращена',
  cancelled: 'Отменена',
  completed: 'Завершена',
  error: 'Ошибка',
  crashed: 'Сбой',
  stopped: 'Остановлена',
  creating: 'Создаётся',
  none: 'Нет',
  'нет': 'Нет',
  demo: 'Демо',
  пожизненная: 'Пожизненная',
};

const PAYMENT_PROVIDER_LABELS = {
  yookassa_checkout: 'ЮKassa',
  yookassa: 'ЮKassa',
  telegram_invoice: 'Telegram',
  manual: 'Вручную',
};

function humanizeStatus(value) {
  if (!value) return 'Нет';
  return STATUS_LABELS[value] || value;
}

function humanizePaymentProvider(value) {
  if (!value) return '—';
  return PAYMENT_PROVIDER_LABELS[value] || value;
}

function Badge({ value, kind }) {
  const colors = {
    active: ['rgba(74,222,128,.14)', 'var(--color-success)'],
    running: ['rgba(74,222,128,.14)', 'var(--color-success)'],
    upcoming: ['rgba(56,189,248,.14)', '#38bdf8'],
    confirmed: ['rgba(56,189,248,.14)', '#38bdf8'],
    pending: ['rgba(251,191,36,.14)', 'var(--color-warning)'],
    frozen: ['rgba(251,191,36,.14)', 'var(--color-warning)'],
    expired: ['rgba(248,113,113,.14)', 'var(--color-error)'],
    refunded: ['rgba(248,113,113,.14)', 'var(--color-error)'],
    cancelled: ['rgba(248,113,113,.14)', 'var(--color-error)'],
    error: ['rgba(248,113,113,.14)', 'var(--color-error)'],
    crashed: ['rgba(248,113,113,.14)', 'var(--color-error)'],
    пожизненная: ['rgba(212,168,83,.18)', 'var(--color-accent)'],
  };
  const [bg, color] = colors[kind || value] || ['var(--color-border)', 'var(--color-text-muted)'];
  return <span className="shrink-0 whitespace-nowrap h-fit px-2 py-1 rounded-full text-xs font-medium" style={{ backgroundColor: bg, color }}>{humanizeStatus(value)}</span>;
}

function Button({ children, onClick, tone = 'default', disabled = false }) {
  const tones = {
    default: ['var(--color-surface-elevated)', 'var(--color-text)', 'var(--color-border)'],
    primary: ['var(--color-accent)', '#07110c', 'var(--color-accent)'],
    success: ['rgba(74,222,128,.12)', 'var(--color-success)', 'rgba(74,222,128,.3)'],
    warning: ['rgba(251,191,36,.12)', 'var(--color-warning)', 'rgba(251,191,36,.3)'],
    danger: ['rgba(248,113,113,.12)', 'var(--color-error)', 'rgba(248,113,113,.3)'],
  };
  const [backgroundColor, color, borderColor] = tones[tone];
  return (
    <button disabled={disabled} onClick={onClick} className="px-3 py-2 rounded-lg text-sm font-medium transition-opacity disabled:opacity-40 hover:opacity-80" style={{ backgroundColor, color, border: `1px solid ${borderColor}` }}>
      {children}
    </button>
  );
}

function useLoad(loader, deps = []) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true);
    loader().then(value => active && setData(value)).catch(err => active && setError(err.message)).finally(() => active && setLoading(false));
    return () => { active = false; };
  }, deps);
  return { data, loading, error };
}

function Loading() {
  return <div className="p-10 text-center" style={{ color: 'var(--color-text-muted)' }}>Загрузка...</div>;
}

function Modal({ title, children, onClose }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ backgroundColor: 'rgba(0,0,0,.72)' }}>
      <div className="w-full max-w-lg max-h-[calc(100dvh-2rem)] overflow-y-auto rounded-2xl p-6" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
        <div className="flex justify-between items-center mb-5">
          <h3 className="text-lg font-bold">{title}</h3>
          <button onClick={onClose} style={{ color: 'var(--color-text-muted)' }}>✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

function Stat({ label, value, note, tone = 'var(--color-accent)' }) {
  return (
    <div className="card p-4 rounded-xl">
      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{label}</p>
      <p className="text-2xl font-bold mt-1" style={{ color: tone }}>{value}</p>
      {note && <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{note}</p>}
    </div>
  );
}

const tabs = [
  ['dashboard', 'Обзор', '◫'],
  ['utm', 'Продвижение', '↗'],
  ['masters', 'Мастера', '♙'],
  ['bookings', 'Записи', '▣'],
  ['subscriptions', 'Подписки', '◈'],
  ['payments', 'Платежи', '₽'],
  ['events', 'События', '≡'],
];

const SUPERADMIN_LIGHT_THEME = {
  '--color-bg': '#f7f3ea',
  '--color-surface': '#ffffff',
  '--color-surface-elevated': '#fff8ec',
  '--color-border': 'rgba(74, 57, 32, 0.14)',
  '--color-border-subtle': 'rgba(74, 57, 32, 0.08)',
  '--color-text': '#19130c',
  '--color-text-secondary': '#514635',
  '--color-text-muted': '#8a7b63',
  '--color-accent': '#b97813',
  '--color-accent-light': 'rgba(185, 120, 19, 0.12)',
  '--color-accent-hover': '#a7660f',
  '--color-accent-muted': '#9d762f',
  '--color-primary': '#b97813',
  '--color-primary-light': 'rgba(185, 120, 19, 0.12)',
  '--color-primary-hover': '#a7660f',
  '--color-success': '#15803d',
  '--color-warning': '#b45309',
  '--color-error': '#b91c1c',
  '--shadow-sm': '0 1px 2px rgba(41, 31, 17, 0.08)',
  '--shadow-md': '0 8px 22px rgba(41, 31, 17, 0.08)',
  '--shadow-lg': '0 18px 44px rgba(41, 31, 17, 0.12)',
  color: 'var(--color-text)',
  background: 'linear-gradient(180deg, #fffaf0 0%, #f7f3ea 48%, #f5f7fb 100%)',
};

export default function Superadmin() {
  const [authorized, setAuthorized] = useState(null);
  const [tab, setTab] = useState('dashboard');
  const [version, setVersion] = useState(0);
  const [toast, setToast] = useState('');
  useEffect(() => { request('/api/superadmin/auth-check').then(() => setAuthorized(true)).catch(() => setAuthorized(false)); }, []);
  const refresh = () => setVersion(value => value + 1);
  const notify = message => { setToast(message); setTimeout(() => setToast(''), 3200); };

  if (authorized === null) return <Loading />;
  if (!authorized) return <div className="p-12 text-center text-xl">Доступ запрещён</div>;

  return (
    <div className="min-h-screen flex gap-5 max-md:flex-col" style={SUPERADMIN_LIGHT_THEME}>
      <aside className="w-56 shrink-0 rounded-2xl p-4 h-fit sticky top-4 max-md:w-full max-md:static" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
        <h1 className="text-xl font-bold" style={{ color: 'var(--color-accent)' }}>Супер-Админ</h1>
        <p className="text-xs mb-6 mt-1" style={{ color: 'var(--color-text-muted)' }}>Операционный центр</p>
        <nav className="space-y-1 max-md:grid max-md:grid-cols-3 max-md:gap-2 max-md:space-y-0">
          {tabs.map(([id, label, icon]) => (
            <button key={id} onClick={() => setTab(id)} className="w-full flex gap-3 px-3 py-2.5 rounded-lg text-left max-md:justify-center max-md:gap-1.5 max-md:px-2 max-md:text-xs" style={{ backgroundColor: tab === id ? 'var(--color-surface-elevated)' : 'transparent', color: tab === id ? 'var(--color-accent)' : 'var(--color-text-secondary)' }}>
              <span>{icon}</span><span>{label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <main className="flex-1 min-w-0">
        <div className="flex justify-between items-center mb-5">
          <div>
            <p className="text-xs uppercase tracking-widest" style={{ color: 'var(--color-text-muted)' }}>Master Booking</p>
            <h2 className="text-2xl font-bold">{tabs.find(item => item[0] === tab)?.[1]}</h2>
          </div>
          <Button onClick={refresh}>↻ Обновить</Button>
        </div>
        {tab === 'dashboard' && <Dashboard version={version} />}
        {tab === 'masters' && <Masters version={version} refresh={refresh} notify={notify} />}
        {tab === 'bookings' && <Bookings version={version} />}
        {tab === 'subscriptions' && <Subscriptions version={version} refresh={refresh} notify={notify} />}
        {tab === 'payments' && <Payments version={version} />}
        {tab === 'utm' && <UtmCampaigns version={version} refresh={refresh} notify={notify} />}
        {tab === 'events' && <Events version={version} />}
      </main>
      {toast && <div className="fixed right-5 bottom-5 z-50 px-4 py-3 rounded-xl shadow-xl" style={{ backgroundColor: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>{toast}</div>}
    </div>
  );
}

function VkArchitectTokenSection() {
  const { data: status } = useLoad(() => request('/api/superadmin/architect-vk-status'), []);
  const [token, setToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');

  const save = async () => {
    setSaving(true); setMsg('');
    try {
      const res = await request('/api/superadmin/architect-vk-token', { method: 'PUT', body: JSON.stringify({ token }) });
      setMsg(`✅ Обновлено: ${res.group_name} (club${res.group_id})`);
      setToken('');
    } catch (e) { setMsg(`❌ ${e.message}`); }
    finally { setSaving(false); }
  };

  const isError = status && status.status === 'error';
  const bgColor = isError ? 'rgba(248,113,113,.08)' : 'var(--color-surface)';
  const borderColor = isError ? 'rgba(248,113,113,.4)' : 'var(--color-border)';

  return (
    <section className="card p-5 rounded-xl" style={{ backgroundColor: bgColor, border: `1px solid ${borderColor}` }}>
      <h3 className="font-bold mb-1">VK Архитектор-бот</h3>
      {status?.exists ? (
        <p className="text-sm mb-3" style={{ color: isError ? 'var(--color-error)' : 'var(--color-text-muted)' }}>
          club{status.group_id} · статус: <b>{status.status}</b>
          {isError && ' — токен истёк, обновите ключ'}
        </p>
      ) : <p className="text-sm mb-3" style={{ color: 'var(--color-warning)' }}>Бот не найден</p>}
      <div className="flex gap-2">
        <input className="flex-1" value={token} onChange={e => setToken(e.target.value)} placeholder="vk1.a...." />
        <Button tone="primary" onClick={save} disabled={saving || !token}>{saving ? '...' : 'Обновить токен'}</Button>
      </div>
      {msg && <p className="text-sm mt-2" style={{ color: msg.startsWith('✅') ? 'var(--color-success)' : 'var(--color-error)' }}>{msg}</p>}
    </section>
  );
}

const PERIOD_OPTIONS = [
  ['all', 'Всё время'],
  ['6m', '6 месяцев'],
  ['1m', 'Месяц'],
  ['1w', 'Неделя'],
  ['1d', 'День'],
];

function Dashboard({ version }) {
  const [period, setPeriod] = useState('all');
  const { data, loading } = useLoad(() => request(`/api/superadmin/metrics?period=${period}`), [version, period]);
  const [resetting, setResetting] = useState(false);
  if (loading || !data) return <Loading />;
  const periodLabel = PERIOD_OPTIONS.find(([k]) => k === period)?.[1] || '';
  const attention = [
    [data.bots.errors, 'Боты с ошибками', 'Проверьте токены и webhook', 'var(--color-error)'],
    [data.subscriptions.pending, 'Ожидают оплаты', 'Незавершённые счета YooKassa', 'var(--color-warning)'],
    [data.bookings.upcoming, 'Будущие записи', 'Текущая нагрузка мастеров', '#38bdf8'],
  ];

  const handleResetFunnel = async () => {
    if (!confirm('Сбросить всю статистику воронки (конверсия, UTM)? Это действие необратимо.')) return;
    setResetting(true);
    try {
      await request('/api/superadmin/funnel-events', { method: 'DELETE' });
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex gap-2 flex-wrap items-center">
        <span className="text-xs shrink-0 mr-1" style={{ color: 'var(--color-text-muted)' }}>Статистика за:</span>
        {PERIOD_OPTIONS.map(([key, label]) => (
          <Button key={key} tone={period === key ? 'primary' : 'default'} onClick={() => setPeriod(key)}>{label}</Button>
        ))}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Мастеров" value={data.masters.total} note={`Новых за ${periodLabel.toLowerCase()}: ${data.masters.newInPeriod}`} />
        <Stat label={`Доход · ${periodLabel}`} value={money(data.subscriptions.revenue)} tone="var(--color-success)" />
        <Stat label="Активных подписок" value={data.subscriptions.active} />
        <Stat label="Заморожено" value={data.subscriptions.frozen} tone="var(--color-warning)" />
      </div>
      <section className="card p-5 rounded-xl">
        <div className="flex justify-between items-center mb-3">
          <h3 className="font-bold">Конверсия Architect Bot · {periodLabel}</h3>
          <Button tone="danger" onClick={handleResetFunnel} disabled={resetting}>{resetting ? '...' : '🗑 Сбросить статистику'}</Button>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat label="Нажали /start" value={data.conversion?.started || 0} note={`Не создали бота: ${data.conversion?.startNoBot || 0}`} />
          <Stat label="Создали бота" value={data.conversion?.created || 0} note={`Конверсия: ${data.conversion?.createRate || 0}%`} tone="#38bdf8" />
          <Stat label="Удалены без оплаты" value={data.conversion?.createdNoPaidDeleted || 0} tone="var(--color-warning)" />
          <Stat label="Оплатили" value={data.conversion?.paid || 0} note={`${data.conversion?.payRateFromStart || 0}% от стартов · ${data.conversion?.payRateFromCreated || 0}% от созданных`} tone="var(--color-success)" />
        </div>
      </section>
      <VkArchitectTokenSection />
      <section className="card p-5 rounded-xl">
        <h3 className="font-bold mb-3">Требует внимания</h3>
        <div className="grid md:grid-cols-3 gap-3">
          {attention.map(([value, label, note, color]) => <div key={label} className="p-4 rounded-xl" style={{ backgroundColor: 'var(--color-surface-elevated)' }}><b style={{ color }}>{value}</b><p className="font-medium">{label}</p><p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>{note}</p></div>)}
        </div>
      </section>
    </div>
  );
}

function UtmCampaigns({ version, refresh, notify }) {
  const { data, loading } = useLoad(() => request('/api/superadmin/utm-campaigns'), [version]);
  const [mode, setMode] = useState('utm');
  const [name, setName] = useState('');
  const [targetUrl, setTargetUrl] = useState('https://architektor.online/services/');
  const [groupId, setGroupId] = useState('');
  const [groupName, setGroupName] = useState('');
  const [collapsedGroups, setCollapsedGroups] = useState({});
  const [saving, setSaving] = useState(false);
  const [savingGroup, setSavingGroup] = useState(false);
  const [groups, setGroups] = useState([]);
  const [campaigns, setCampaigns] = useState([]);
  const collapsedInitialized = useRef(false);
  useEffect(() => {
    setGroups(data?.groups || []);
    setCampaigns(data?.campaigns || []);
    if (data && !collapsedInitialized.current) {
      const nextCollapsed = { ungrouped: true };
      (data.groups || []).forEach(group => { nextCollapsed[`group:${group.id}`] = true; });
      setCollapsedGroups(nextCollapsed);
      collapsedInitialized.current = true;
    }
  }, [data]);
  const organicCampaign = campaigns.find(campaign => campaign.source === 'organic');
  const utmCampaigns = campaigns.filter(campaign => campaign.source !== 'organic');
  const groupedCampaigns = useMemo(() => {
    const byGroup = new Map(groups.map(group => [String(group.id), []]));
    const ungrouped = [];
    utmCampaigns.forEach(campaign => {
      const key = campaign.group_id ? String(campaign.group_id) : '';
      if (key && byGroup.has(key)) byGroup.get(key).push(campaign);
      else ungrouped.push(campaign);
    });
    return { byGroup, ungrouped };
  }, [utmCampaigns, groups]);
  const updateCampaign = updated => setCampaigns(rows => rows.map(item => item.id === updated.id ? { ...item, ...updated } : item));
  const removeCampaign = campaignId => setCampaigns(rows => rows.filter(item => item.id !== campaignId));
  const updateGroup = updated => setGroups(rows => rows.map(item => item.id === updated.id ? { ...item, ...updated } : item));
  const removeGroup = groupId => {
    setGroups(rows => rows.filter(item => item.id !== groupId));
    setCampaigns(rows => rows.map(item => item.group_id === groupId ? { ...item, group_id: null, group_name: null } : item));
  };

  const createCampaign = async () => {
    const cleanName = name.trim();
    const cleanTarget = targetUrl.trim();
    if (!cleanName || !cleanTarget) {
      notify('Укажите название рекламы и ссылку');
      return;
    }
    setSaving(true);
    try {
      const created = await request('/api/superadmin/utm-campaigns', {
        method: 'POST',
        body: JSON.stringify({ name: cleanName, target_url: cleanTarget, group_id: groupId ? Number(groupId) : null }),
      });
      try {
        await navigator.clipboard?.writeText(created.utm_url);
        notify('UTM-ссылка создана и скопирована');
      } catch {
        notify('UTM-ссылка создана');
      }
      setName('');
      setTargetUrl('https://architektor.online/services/');
      setCampaigns(rows => [...rows, created]);
    } catch (error) {
      notify(error.message);
    } finally {
      setSaving(false);
    }
  };

  const createGroup = async () => {
    const cleanName = groupName.trim();
    if (!cleanName) {
      notify('Укажите название группы');
      return;
    }
    setSavingGroup(true);
    try {
      const created = await request('/api/superadmin/utm-groups', {
        method: 'POST',
        body: JSON.stringify({ name: cleanName }),
      });
      setGroupName('');
      setGroups(rows => [...rows, created]);
      setCollapsedGroups(value => ({ ...value, [`group:${created.id}`]: true }));
      notify('Группа создана');
    } catch (error) {
      notify(error.message);
    } finally {
      setSavingGroup(false);
    }
  };

  const toggleGroup = key => setCollapsedGroups(value => ({ ...value, [key]: !value[key] }));

  if (loading) return <Loading />;

  return (
    <div className="space-y-5">
      <section className="card p-5 rounded-xl">
        <h3 className="font-bold mb-1">Продвижение сайта</h3>
        <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
          Здесь отдельно живут рекламные UTM-ссылки и органические переходы на сайт. Так проще видеть, что пришло из рекламы, а что пришло напрямую или из поиска.
        </p>
        <div className="grid md:grid-cols-2 gap-3">
          <PromotionModeCard
            active={mode === 'utm'}
            title="UTM-ссылки"
            value={utmCampaigns.length}
            note="Рекламные ссылки, группы, каналы размещения и счётчики переходов."
            onClick={() => setMode('utm')}
          />
          <PromotionModeCard
            active={mode === 'organic'}
            title="Органика сайта"
            value={organicCampaign?.clicks || 0}
            note="Прямые заходы, поисковый трафик и переходы без рекламной UTM-ссылки."
            onClick={() => setMode('organic')}
          />
        </div>
      </section>

      {mode === 'utm' ? (
        <>
          <section className="card p-5 rounded-xl">
            <h3 className="font-bold mb-1">Группы кампаний</h3>
            <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
              Создавайте группы, чтобы сворачивать блоки ссылок и не держать весь список раскрытым.
            </p>
            <div className="grid md:grid-cols-[1fr_auto] gap-3 items-end">
              <label className="block">
                <span className="text-xs mb-1 block" style={{ color: 'var(--color-text-muted)' }}>Название группы</span>
                <input value={groupName} onChange={event => setGroupName(event.target.value)} placeholder="Блоги и статьи" />
              </label>
              <Button tone="primary" onClick={createGroup} disabled={savingGroup}>{savingGroup ? 'Создаю...' : 'Создать группу'}</Button>
            </div>
          </section>

          <section className="card p-5 rounded-xl">
            <h3 className="font-bold mb-1">Новая UTM-ссылка</h3>
            <p className="text-sm mb-4" style={{ color: 'var(--color-text-muted)' }}>
              Укажите название рекламы и страницу, куда должен попасть человек. Сервис сам создаст короткую ссылку, скопирует её и начнёт считать переходы.
            </p>
            <div className="grid md:grid-cols-[minmax(180px,260px)_1fr_minmax(180px,240px)_auto] gap-3 items-end">
              <label className="block">
                <span className="text-xs mb-1 block" style={{ color: 'var(--color-text-muted)' }}>Название рекламы</span>
                <input value={name} onChange={event => setName(event.target.value)} placeholder="Реклама 4" />
              </label>
              <label className="block">
                <span className="text-xs mb-1 block" style={{ color: 'var(--color-text-muted)' }}>Куда ведёт</span>
                <input value={targetUrl} onChange={event => setTargetUrl(event.target.value)} placeholder="https://architektor.online/services/" />
              </label>
              <label className="block">
                <span className="text-xs mb-1 block" style={{ color: 'var(--color-text-muted)' }}>Группа</span>
                <select value={groupId} onChange={event => setGroupId(event.target.value)}>
                  <option value="">Без группы</option>
                  {groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
                </select>
              </label>
              <Button tone="primary" onClick={createCampaign} disabled={saving}>{saving ? 'Создаю...' : 'Добавить'}</Button>
            </div>
          </section>

          <section className="card p-5 rounded-xl">
            <h3 className="font-bold mb-4">UTM-ссылки</h3>
            <div className="space-y-4">
              {groups.map(group => (
                <UtmGroupSection
                  key={group.id}
                  group={group}
                  groups={groups}
                  campaigns={groupedCampaigns.byGroup.get(String(group.id)) || []}
                  collapsed={!!collapsedGroups[`group:${group.id}`]}
                  toggle={() => toggleGroup(`group:${group.id}`)}
                  refresh={refresh}
                  updateGroup={updateGroup}
                  removeGroup={removeGroup}
                  updateCampaign={updateCampaign}
                  removeCampaign={removeCampaign}
                  notify={notify}
                />
              ))}
              <UtmGroupSection
                group={null}
                groups={groups}
                campaigns={groupedCampaigns.ungrouped}
                collapsed={!!collapsedGroups.ungrouped}
                toggle={() => toggleGroup('ungrouped')}
                refresh={refresh}
                updateGroup={updateGroup}
                removeGroup={removeGroup}
                updateCampaign={updateCampaign}
                removeCampaign={removeCampaign}
                notify={notify}
              />
              {!utmCampaigns.length && !groups.length && (
                <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>UTM-ссылок пока нет.</p>
              )}
            </div>
          </section>
        </>
      ) : (
        <OrganicDashboard organic={organicCampaign} updateCampaign={updateCampaign} notify={notify} />
      )}
    </div>
  );
}

function PromotionModeCard({ active, title, value, note, onClick }) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-2xl p-4 transition hover:-translate-y-0.5"
      style={{
        backgroundColor: active ? 'var(--color-accent-light)' : 'var(--color-surface-elevated)',
        border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
        boxShadow: active ? 'var(--shadow-md)' : 'none',
      }}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-bold">{title}</p>
          <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>{note}</p>
        </div>
        <span className="text-2xl font-bold" style={{ color: 'var(--color-accent)' }}>{value}</span>
      </div>
    </button>
  );
}

function OrganicDashboard({ organic, updateCampaign, notify }) {
  const [resetting, setResetting] = useState(false);
  const paths = organic?.path_stats || [];
  const referrers = organic?.referrer_stats || [];

  const resetOrganic = async () => {
    if (!organic) return;
    setResetting(true);
    try {
      await request(`/api/superadmin/utm-campaigns/${organic.id}/stats`, { method: 'DELETE' });
      updateCampaign({ ...organic, clicks: 0, path_stats: [], referrer_stats: [] });
      notify('Органика обнулена');
    } catch (error) {
      notify(error.message);
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="space-y-5">
      <section className="grid md:grid-cols-3 gap-3">
        <Stat label="Органических переходов" value={organic?.clicks || 0} note="Без рекламной UTM-ссылки" tone="var(--color-success)" />
        <Stat label="Страниц с трафиком" value={paths.length} note="Какие страницы реально открывали" />
        <Stat label="Источников" value={referrers.length || 1} note="Рефереры, прямые заходы и поиск" tone="#2563eb" />
      </section>

      <section className="card p-5 rounded-xl">
        <div className="flex justify-between gap-3 items-start mb-4 max-md:flex-col">
          <div>
            <h3 className="font-bold">Органика сайта</h3>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-muted)' }}>
              Сюда попадают открытия сайта без UTM-редиректа: прямые заходы, поиск, закладки и переходы из мест, где не использовалась рекламная ссылка.
            </p>
          </div>
          <Button tone="warning" onClick={resetOrganic} disabled={resetting || !organic}>{resetting ? '...' : 'Обнулить'}</Button>
        </div>
        <div className="grid lg:grid-cols-2 gap-4">
          <OrganicBreakdown title="Страницы сайта" empty="Переходов по страницам пока нет." rows={paths} labelKey="path" />
          <OrganicBreakdown title="Источники переходов" empty="Источников пока нет." rows={referrers} labelKey="referrer" />
        </div>
      </section>
    </div>
  );
}

function OrganicBreakdown({ title, rows, labelKey, empty }) {
  const total = rows.reduce((sum, row) => sum + (row.clicks || 0), 0);
  return (
    <div className="rounded-xl p-4" style={{ backgroundColor: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
      <h4 className="font-bold mb-3">{title}</h4>
      <div className="space-y-2">
        {rows.map(row => {
          const percent = total ? Math.round((row.clicks / total) * 100) : 0;
          return (
            <div key={`${labelKey}-${row[labelKey]}`} className="rounded-lg p-3" style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}>
              <div className="flex justify-between gap-3 text-sm">
                <span className="font-medium">{row[labelKey]}</span>
                <b style={{ color: 'var(--color-accent)' }}>{row.clicks}</b>
              </div>
              <div className="h-2 rounded-full mt-2 overflow-hidden" style={{ backgroundColor: 'var(--color-border-subtle)' }}>
                <div className="h-full rounded-full" style={{ width: `${percent}%`, backgroundColor: 'var(--color-accent)' }} />
              </div>
            </div>
          );
        })}
        {!rows.length && <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{empty}</p>}
      </div>
    </div>
  );
}

function UtmGroupSection({ group, groups, campaigns, collapsed, toggle, updateGroup, removeGroup: removeGroupFromList, updateCampaign, removeCampaign, notify }) {
  const isUngrouped = !group;
  const [name, setName] = useState(group?.name || 'Без группы');
  const [deleting, setDeleting] = useState(false);
  const skipInitialSave = useRef(true);

  useEffect(() => {
    setName(group?.name || 'Без группы');
  }, [group?.name]);

  useEffect(() => {
    if (isUngrouped) return undefined;
    if (skipInitialSave.current) {
      skipInitialSave.current = false;
      return undefined;
    }
    const cleanName = name.trim();
    if (!cleanName || cleanName === group.name) return undefined;
    const timer = setTimeout(async () => {
      try {
        const updated = await request(`/api/superadmin/utm-groups/${group.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ name: cleanName }),
        });
        updateGroup(updated);
      } catch (error) {
        notify(error.message);
      }
    }, 550);
    return () => clearTimeout(timer);
  }, [name, group?.id, group?.name, isUngrouped]);

  const deleteGroup = async () => {
    if (isUngrouped) return;
    if (!confirm(`Удалить группу «${group.name}»? Ссылки внутри группы останутся и перейдут в «Без группы».`)) return;
    setDeleting(true);
    try {
      await request(`/api/superadmin/utm-groups/${group.id}`, { method: 'DELETE' });
      notify('Группа удалена');
      removeGroupFromList(group.id);
    } catch (error) {
      notify(error.message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="rounded-xl p-3" style={{ backgroundColor: 'var(--color-surface-elevated)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center gap-2 max-md:flex-col max-md:items-stretch">
        <button onClick={toggle} className="px-2.5 py-2 rounded-lg text-left font-bold" style={{ backgroundColor: 'var(--color-bg)', color: 'var(--color-accent)' }}>
          {collapsed ? '▸' : '▾'} {campaigns.length}
        </button>
        {isUngrouped ? (
          <div className="flex-1">
            <b>Без группы</b>
            <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Ссылки, которые пока не объединены в рекламную кампанию.</p>
          </div>
        ) : (
          <input className="flex-1" value={name} onChange={event => setName(event.target.value)} />
        )}
        {!isUngrouped && (
          <div className="flex gap-2 max-md:flex-col">
            <Button onClick={deleteGroup} tone="danger" disabled={deleting}>{deleting ? 'Удаляю...' : 'Удалить группу'}</Button>
          </div>
        )}
      </div>
      {!collapsed && (
        <div className="space-y-2 mt-3">
          {campaigns.map(campaign => (
            <UtmCampaignCard key={campaign.id} campaign={campaign} groups={groups} updateCampaign={updateCampaign} removeCampaign={removeCampaign} notify={notify} />
          ))}
          {!campaigns.length && (
            <p className="text-sm px-2" style={{ color: 'var(--color-text-muted)' }}>В этой группе пока нет ссылок.</p>
          )}
        </div>
      )}
    </div>
  );
}

function UtmCampaignCard({ campaign, groups, updateCampaign, removeCampaign, notify }) {
  const [editName, setEditName] = useState(campaign.name || '');
  const [placementUrl, setPlacementUrl] = useState(campaign.placement_url || '');
  const [editGroupId, setEditGroupId] = useState(campaign.group_id ? String(campaign.group_id) : '');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [resetting, setResetting] = useState(false);
  const skipInitialSave = useRef(true);

  useEffect(() => {
    setEditName(campaign.name || '');
    setPlacementUrl(campaign.placement_url || '');
    setEditGroupId(campaign.group_id ? String(campaign.group_id) : '');
    skipInitialSave.current = true;
  }, [campaign.name, campaign.placement_url, campaign.group_id]);

  const savePatch = async (patch = {}) => {
    const body = {
      name: editName.trim(),
      placement_url: placementUrl.trim() || null,
      group_id: editGroupId ? Number(editGroupId) : null,
      ...patch,
    };
    if (!body.name) {
      notify('Укажите название рекламы');
      return null;
    }
    setSaving(true);
    try {
      const updated = await request(`/api/superadmin/utm-campaigns/${campaign.id}`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      });
      updateCampaign(updated);
      return updated;
    } catch (error) {
      notify(error.message);
      return null;
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (skipInitialSave.current) {
      skipInitialSave.current = false;
      return undefined;
    }
    const cleanName = editName.trim();
    const cleanPlacement = placementUrl.trim();
    if (!cleanName) return undefined;
    if (cleanName === campaign.name && cleanPlacement === (campaign.placement_url || '')) return undefined;
    const timer = setTimeout(() => {
      savePatch({ name: cleanName, placement_url: cleanPlacement || null });
    }, 650);
    return () => clearTimeout(timer);
  }, [editName, placementUrl]);

  const changeGroup = async event => {
    const nextGroupId = event.target.value;
    setEditGroupId(nextGroupId);
    await savePatch({ group_id: nextGroupId ? Number(nextGroupId) : null });
  };

  const remove = async () => {
    if (!confirm(`Удалить UTM-ссылку «${campaign.name}»? Редирект перестанет работать.`)) return;
    setDeleting(true);
    try {
      await request(`/api/superadmin/utm-campaigns/${campaign.id}`, { method: 'DELETE' });
      notify('UTM-ссылка удалена');
      removeCampaign(campaign.id);
    } catch (error) {
      notify(error.message);
    } finally {
      setDeleting(false);
    }
  };

  const resetStats = async () => {
    setResetting(true);
    try {
      await request(`/api/superadmin/utm-campaigns/${campaign.id}/stats`, { method: 'DELETE' });
      updateCampaign({ ...campaign, clicks: 0 });
      notify('Счётчик обнулён');
    } catch (error) {
      notify(error.message);
    } finally {
      setResetting(false);
    }
  };

  return (
    <div className="rounded-xl p-3 space-y-3" style={{ backgroundColor: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
      <div className="grid lg:grid-cols-[1.1fr_auto_180px_auto] gap-2 items-center">
        <input value={editName} onChange={event => setEditName(event.target.value)} placeholder="Название" />
        <Button onClick={() => { navigator.clipboard.writeText(campaign.utm_url); notify('UTM-ссылка скопирована'); }}>Копировать ссылку</Button>
        <select value={editGroupId} onChange={changeGroup}>
          <option value="">Без группы</option>
          {groups.map(group => <option key={group.id} value={group.id}>{group.name}</option>)}
        </select>
        <div className="flex items-center gap-2 justify-end">
          <span className="text-xs whitespace-nowrap" style={{ color: 'var(--color-text-muted)' }}>Переходов: <b style={{ color: 'var(--color-accent)' }}>{campaign.clicks}</b></span>
          <Button onClick={resetStats} tone="warning" disabled={resetting}>{resetting ? '...' : 'Обнулить'}</Button>
          <Button onClick={remove} tone="danger" disabled={deleting}>{deleting ? '...' : 'Удалить'}</Button>
        </div>
      </div>
      <div className="grid lg:grid-cols-[1fr_1fr_auto_auto] gap-2 items-center">
        <input value={placementUrl} onChange={event => setPlacementUrl(event.target.value)} placeholder="Где размещена реклама: t.me/nail_forum" />
        <code className="text-xs px-3 py-2 rounded-lg overflow-auto" style={{ backgroundColor: 'var(--color-surface)', color: 'var(--color-text-muted)' }}>Ведёт на: {campaign.target_url}</code>
        {campaign.placement_url ? (
          <a className="px-3 py-2 rounded-lg text-sm font-medium text-center hover:opacity-80" href={externalHref(campaign.placement_url)} target="_blank" rel="noreferrer" style={{ backgroundColor: 'var(--color-surface)', color: 'var(--color-accent)', border: '1px solid var(--color-border)' }}>
            Открыть канал
          </a>
        ) : <span className="text-xs text-center" style={{ color: 'var(--color-text-muted)' }}>Канал не указан</span>}
        <span className="text-xs text-center" style={{ color: saving ? 'var(--color-warning)' : 'var(--color-text-muted)' }}>{saving ? 'Сохраняю...' : 'Автосохранение'}</span>
      </div>
    </div>
  );
}

function Masters({ version, refresh, notify }) {
  const { data, loading } = useLoad(() => request('/api/superadmin/masters'), [version]);
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('all');
  const [selected, setSelected] = useState(null);
  const [subscriptionMaster, setSubscriptionMaster] = useState(null);
  const masters = data?.masters || [];
  const filtered = masters.filter(master => {
    const text = `${master.name} ${master.telegram_id || ''} ${(master.bots || []).map(bot => bot.username).join(' ')}`.toLowerCase();
    return text.includes(search.toLowerCase()) && (status === 'all' || (status === 'none' ? !master.subscription : master.subscription?.status === status));
  });
  const mutate = async (path, message, options = { method: 'POST' }) => {
    try { await request(path, options); notify(message); setSelected(null); refresh(); } catch (error) { notify(error.message); }
  };
  return (
    <>
      <div className="flex flex-wrap gap-3 mb-4">
        <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Имя, Telegram ID или бот" className="flex-1 min-w-64" />
        <select value={status} onChange={e => setStatus(e.target.value)}><option value="all">Все статусы</option><option value="active">Активные</option><option value="pending">Ожидают оплаты</option><option value="frozen">Замороженные</option><option value="expired">Истёкшие</option><option value="refunded">Возвращённые</option><option value="none">Без подписки</option></select>
      </div>
      <div className="grid gap-3 md:hidden">
        {loading ? <Loading /> : filtered.length === 0 ? <div className="card rounded-xl p-6 text-center" style={{ color: 'var(--color-text-muted)' }}>Мастеров не найдено</div> : filtered.map(master => (
          <div key={master.id} className="card rounded-xl p-4 space-y-3">
            <div className="flex justify-between gap-3">
              <div className="min-w-0"><b className="block leading-tight">{master.name}</b>{master.is_demo && <span className="block mt-1"><Badge value="demo" /></span>}<small className="block mt-1">ID {master.id} · TG {master.telegram_id || '—'}</small></div>
              <Badge value={master.bot?.status || 'нет бота'} />
            </div>
            {(master.bots || []).length > 0 && <pre className="text-xs whitespace-pre-wrap leading-6 rounded-xl p-3 overflow-x-auto" style={{ backgroundColor: 'var(--color-surface-elevated)', color: 'var(--color-text-secondary)' }}>{renderBotTree(master)}</pre>}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div><small>Бот</small><p>{master.bot?.username ? `@${master.bot.username}` : 'Не создан'}</p></div>
              <div><small>Подписка</small><p className="font-bold" style={{ color: 'var(--color-accent)' }}>{master.subscription ? (master.subscription.lifetime ? 'Пожизненная' : `${master.subscription.days_left ?? '—'} дней`) : 'Нет'}</p></div>
              <div><small>Клиенты</small><p>{master.clients_count}</p></div>
              <div><small>Записи</small><p>{master.upcoming_bookings_count} будущих · {master.bookings_count} всего</p></div>
            </div>
            <Button onClick={() => setSelected(master.id)}>Открыть карточку</Button>
          </div>
        ))}
      </div>
      <div className="card rounded-xl overflow-auto max-md:hidden">
        {loading ? <Loading /> : <table className="w-full text-sm">
          <thead><tr><th>Мастер</th><th>Бот</th><th>Подписка</th><th>Активность</th><th></th></tr></thead>
          <tbody>{filtered.map(master => <tr key={master.id}>
            <td><b>{master.name}</b>{master.is_demo && <small><Badge value="demo" /></small>}<small>ID {master.id} · TG {master.telegram_id || '—'}</small><small style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{renderBotTree(master)}</small></td>
            <td>{master.bot ? <><span>@{master.bot.username}</span><small><Badge value={master.bot.status} /></small></> : 'Нет бота'}</td>
            <td>{master.subscription ? <><Badge value={master.subscription.lifetime ? 'пожизненная' : master.subscription.status} /><small><span className="font-bold" style={{ color: 'var(--color-accent)' }}>{master.subscription.lifetime ? 'Пожизненная' : `${master.subscription.days_left ?? '—'} дней`}</span> · {money(master.subscription.price)}</small></> : <Badge value="нет" />}</td>
            <td><span>{master.clients_count} клиентов</span><small>{master.upcoming_bookings_count} будущих · {master.bookings_count} всего</small></td>
            <td><Button onClick={() => setSelected(master.id)}>Открыть</Button></td>
          </tr>)}</tbody>
        </table>}
      </div>
      {selected && <MasterDrawer id={selected} close={() => setSelected(null)} setSubscriptionMaster={setSubscriptionMaster} mutate={mutate} />}
      {subscriptionMaster && <SubscriptionModal master={subscriptionMaster} close={() => setSubscriptionMaster(null)} refresh={refresh} notify={notify} />}
    </>
  );
}

function renderBotTree(master) {
  const owner = `${master.name}${master.telegram_username ? ` (@${master.telegram_username})` : ''}`
  const bots = master.bots || []
  if (!bots.length) return `${owner}\n│`
  return [
    owner,
    '│',
    ...bots.map((bot, index) => `${index === bots.length - 1 ? '└─' : '├─'} ${bot.username ? `@${bot.username}` : `Бот #${bot.id}`}`),
  ].join('\n')
}

function MasterDrawer({ id, close, setSubscriptionMaster, mutate }) {
  const { data: master, loading } = useLoad(() => request(`/api/superadmin/masters/${id}`), [id]);
  if (loading || !master) return <Modal title="Карточка мастера" onClose={close}><Loading /></Modal>;
  return <Modal title={master.name} onClose={close}>
    <div className="space-y-4 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <div><small>Telegram ID</small><p>{master.telegram_id || '—'}</p></div>
        <div><small>Создан</small><p>{dateOnly(master.created_at)}</p></div>
        <div><small>Клиенты</small><p>{master.clients_count}</p></div>
        <div><small>Будущие записи</small><p>{master.upcoming_bookings_count}</p></div>
      </div>
      <div><h4 className="font-bold mb-2">Боты мастера</h4>
        {(master.bots || []).length === 0 ? <small>Боты не созданы</small> : (master.bots || []).map(bot => (
          <div key={bot.id} className="p-3 rounded-xl mb-2 space-y-2" style={{ backgroundColor: 'var(--color-surface-elevated)' }}>
            <div className="flex justify-between gap-2"><p className="font-medium">@{bot.username || bot.id}</p><Badge value={bot.status} /></div>
            <p className="text-xs">Подписка: <Badge value={bot.subscription?.lifetime ? 'пожизненная' : bot.subscription?.status || 'none'} /></p>
            {bot.subscription && <small>{bot.subscription.lifetime ? 'Без ограничения срока' : `${bot.subscription.days_left ?? '—'} дней`} · {money(bot.subscription.price)} · {bot.subscription.payment_provider}</small>}
            {!master.is_demo && <div className="flex flex-wrap gap-2 pt-1">
              <Button tone="primary" onClick={() => setSubscriptionMaster({ ...master, bot, subscription: bot.subscription })}>Настроить подписку</Button>
              <Button tone="danger" onClick={() => confirm(`Удалить @${bot.username || bot.id}? Данные мастера сохранятся.`) && mutate(`/api/superadmin/bots/${bot.id}`, 'Бот удалён', { method: 'DELETE' })}>Удалить бот</Button>
            </div>}
          </div>
        ))}
      </div>
      {master.is_demo && <small>Демо-профиль используется как безопасный тестовый стенд. Операции управления для него отключены.</small>}
      <div><h4 className="font-bold mb-2">Последние записи</h4>{master.recent_bookings?.length ? master.recent_bookings.map(item => <div key={item.id} className="py-2 border-t text-xs" style={{ borderColor: 'var(--color-border)' }}>{item.date} {item.time} · {item.client_name} · {item.service_name || `${item.duration_minutes} мин`}</div>) : <small>Записей нет</small>}</div>
    </div>
  </Modal>;
}

function SubscriptionModal({ master, close, refresh, notify }) {
  const [days, setDays] = useState(master.subscription?.period_days || 30);
  const [price, setPrice] = useState(master.subscription?.price || 0);
  const [status, setStatus] = useState(master.subscription?.status || 'active');
  const [lifetime, setLifetime] = useState(master.subscription?.lifetime || false);
  const save = async () => {
    try {
      await request(`/api/superadmin/masters/${master.id}/subscription`, { method: 'PUT', body: JSON.stringify({ period_days: Number(days), price: Number(price), status, lifetime, master_bot_id: master.bot?.id || null }) });
      notify('Подписка сохранена'); close(); refresh();
    } catch (error) { notify(error.message); }
  };
  return <Modal title={`Подписка: ${master.bot?.username ? `@${master.bot.username}` : master.name}`} onClose={close}>
    <div className="space-y-4">
      <label><small>Статус</small><select className="w-full mt-1" value={status} onChange={e => setStatus(e.target.value)}><option value="active">Активна</option><option value="frozen">Заморожена</option><option value="expired">Истекла</option></select></label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={lifetime} onChange={e => setLifetime(e.target.checked)} /> Пожизненная подписка</label>
      <label><small>Период, дней</small><input disabled={lifetime} className="w-full mt-1" type="number" min="1" max="3650" value={days} onChange={e => setDays(e.target.value)} /></label>
      <label><small>Стоимость для учёта, ₽</small><input className="w-full mt-1" type="number" min="0" value={price} onChange={e => setPrice(e.target.value)} /></label>
      <p className="text-xs" style={{ color: 'var(--color-text-muted)' }}>Будет создана новая ручная запись подписки. История предыдущих оплат сохранится.</p>
      <div className="flex gap-2 justify-end"><Button onClick={close}>Отмена</Button><Button tone="primary" onClick={save}>Сохранить</Button></div>
    </div>
  </Modal>;
}

function Bookings({ version }) {
  const [days, setDays] = useState('30');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [masterId, setMasterId] = useState('');
  const [includeDemo, setIncludeDemo] = useState(false);
  const { data, loading } = useLoad(() => request(`/api/superadmin/bookings?days=${days}&include_demo=${includeDemo}${status ? `&status=${status}` : ''}${masterId ? `&master_id=${encodeURIComponent(masterId)}` : ''}`), [version, days, status, includeDemo, masterId]);
  const rows = (data?.bookings || []).filter(row => `${row.master_name} ${row.client_name} ${row.client_phone || ''} ${row.service_name || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <div className="flex flex-wrap gap-3 mb-4"><input className="flex-1 min-w-64" value={search} onChange={e => setSearch(e.target.value)} placeholder="Мастер, клиент, телефон или услуга" /><input value={masterId} onChange={e => setMasterId(e.target.value.replace(/\D/g, ''))} placeholder="ID мастера" className="w-36" /><select value={days} onChange={e => setDays(e.target.value)}><option value="7">История 7 дней + будущие</option><option value="30">История 30 дней + будущие</option><option value="90">История 90 дней + будущие</option><option value="365">История за год + будущие</option></select><select value={status} onChange={e => setStatus(e.target.value)}><option value="">Все статусы</option><option value="upcoming">Будущие</option><option value="cancelled">Отменённые</option><option value="completed">Завершённые</option></select><label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={includeDemo} onChange={e => setIncludeDemo(e.target.checked)} /> Показать демо</label></div>
    <div className="grid gap-3 md:hidden">{loading ? <Loading /> : rows.length === 0 ? <div className="card rounded-xl p-8 text-center" style={{ color: 'var(--color-text-muted)' }}>Записей не найдено</div> : rows.map(row => <div key={row.id} className="card rounded-xl p-4 space-y-2 text-sm"><div className="flex justify-between gap-3"><b>{row.date} · {row.time}</b><Badge value={row.status} /></div><p>{row.client_name}<small>{row.client_phone || 'Телефон не указан'}</small></p><p>{row.service_name || 'Без услуги'} · {row.duration_minutes} мин</p>{row.comment && <small>Комментарий: {row.comment}</small>}<small>Мастер: {row.master_name}</small></div>)}</div>
    <div className="card rounded-xl overflow-auto max-md:hidden">{loading ? <Loading /> : rows.length === 0 ? <div className="p-10 text-center" style={{ color: 'var(--color-text-muted)' }}>Записей не найдено</div> : <table className="w-full text-sm"><thead><tr><th>Дата</th><th>Мастер</th><th>Клиент</th><th>Услуга</th><th>Статус</th></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td>{row.date}<small>{row.time} · {row.duration_minutes} мин</small></td><td>{row.master_name}</td><td>{row.client_name}<small>{row.client_phone || '—'}</small></td><td>{row.service_name || 'Без услуги'}{row.comment && <small>{row.comment}</small>}</td><td><Badge value={row.status} /></td></tr>)}</tbody></table>}</div>
  </>;
}

function Subscriptions({ version, refresh, notify }) {
  const { data, loading } = useLoad(() => request('/api/superadmin/masters'), [version]);
  const [filter, setFilter] = useState('all');
  const [selected, setSelected] = useState(null);
  const masters = data?.masters || [];
  const rows = masters
    .filter(master => !master.is_demo)
    .flatMap(master => (master.bots || []).map(bot => ({ ...master, bot, subscription: bot.subscription })))
    .filter(master => filter === 'all' || (filter === 'none' ? !master.subscription : filter === 'lifetime' ? master.subscription?.lifetime : master.subscription?.status === filter));
  const filterLabels = { all: 'Все', active: 'Активные', lifetime: 'Пожизненные', pending: 'Ожидают оплаты', frozen: 'Замороженные', expired: 'Истёкшие', refunded: 'Возвращённые', none: 'Без подписки' };
  return <>
    <div className="flex gap-2 mb-4 flex-wrap">{['all', 'active', 'lifetime', 'pending', 'frozen', 'expired', 'refunded', 'none'].map(value => <Button key={value} tone={filter === value ? 'primary' : 'default'} onClick={() => setFilter(value)}>{filterLabels[value]}</Button>)}</div>
    <div className="grid md:grid-cols-2 gap-3">{loading ? <Loading /> : rows.map(master => <div key={`${master.id}-${master.bot.id}`} className="card rounded-xl p-4"><div className="flex justify-between"><b>{master.name}</b><Badge value={master.subscription?.lifetime ? 'пожизненная' : master.subscription?.status || 'none'} /></div><small>@{master.bot.username || master.bot.id}</small><div className="mt-3 text-sm">{master.subscription ? `${master.subscription.lifetime ? 'Без ограничения срока' : `${master.subscription.days_left ?? '—'} дней`} · ${money(master.subscription.price)}` : 'Подписки ещё нет'}</div><div className="mt-3"><Button tone="primary" onClick={() => setSelected(master)}>Настроить</Button></div></div>)}</div>
    {selected && <SubscriptionModal master={selected} close={() => setSelected(null)} refresh={refresh} notify={notify} />}
  </>;
}

function Payments({ version }) {
  const [status, setStatus] = useState('');
  const { data, loading } = useLoad(() => request(`/api/superadmin/payments${status ? `?status=${status}` : ''}`), [version, status]);
  return <>
    <div className="flex gap-3 mb-4"><select value={status} onChange={e => setStatus(e.target.value)}><option value="">Все статусы</option><option value="active">Оплаченные</option><option value="pending">Ожидают</option><option value="expired">Истёкшие</option><option value="frozen">Замороженные</option><option value="refunded">Возвращённые</option></select></div>
    <div className="grid gap-3 md:hidden">{loading ? <Loading /> : (data?.payments || []).length === 0 ? <div className="card rounded-xl p-8 text-center" style={{ color: 'var(--color-text-muted)' }}>История платежей пока пуста</div> : data.payments.map(row => <div key={row.id} className="card rounded-xl p-4 space-y-2 text-sm"><div className="flex justify-between gap-3"><b>{money(row.price)}</b><Badge value={row.status} /></div><p>Telegram ID: {row.master_telegram_id}</p><p>{row.lifetime ? 'Пожизненная подписка' : `${row.period_days} дней · до ${dateOnly(row.ends_at)}`}</p><small>{humanizePaymentProvider(row.payment_provider)} · {dateTime(row.created_at)}</small></div>)}</div>
    <div className="card rounded-xl overflow-auto max-md:hidden">{loading ? <Loading /> : (data?.payments || []).length === 0 ? <div className="p-10 text-center" style={{ color: 'var(--color-text-muted)' }}>История платежей пока пуста</div> : <table className="w-full text-sm"><thead><tr><th>Создан</th><th>Мастер TG</th><th>Провайдер</th><th>Сумма</th><th>Период</th><th>Статус</th></tr></thead><tbody>{data.payments.map(row => <tr key={row.id}><td>{dateTime(row.created_at)}<small>Оплата: {dateTime(row.paid_at)}</small></td><td>{row.master_telegram_id}</td><td>{humanizePaymentProvider(row.payment_provider)}<small>{row.provider_payment_charge_id || row.payment_id || '—'}</small></td><td>{money(row.price)}</td><td>{row.lifetime ? 'Пожизненная' : `${row.period_days} дней`}<small>{row.lifetime ? 'без ограничения срока' : `до ${dateOnly(row.ends_at)}`}</small></td><td><Badge value={row.status} /></td></tr>)}</tbody></table>}</div>
  </>;
}

function Events({ version }) {
  const [days, setDays] = useState('30');
  const [type, setType] = useState('');
  const { data, loading } = useLoad(() => request(`/api/superadmin/events?days=${days}${type ? `&event_type=${type}` : ''}`), [version, days, type]);
  const labels = { master_created: 'Новый мастер', payment: 'Оплата', bot_error: 'Ошибка бота' };
  return <>
    <div className="flex gap-3 mb-4"><select value={days} onChange={e => setDays(e.target.value)}><option value="7">7 дней</option><option value="30">30 дней</option><option value="90">90 дней</option></select><select value={type} onChange={e => setType(e.target.value)}><option value="">Все события</option><option value="master_created">Мастера</option><option value="payment">Платежи</option><option value="bot_error">Ошибки ботов</option></select></div>
    <div className="card rounded-xl divide-y">{loading ? <Loading /> : (data?.events || []).map((event, index) => <div key={`${event.type}-${index}`} className="p-4" style={{ borderColor: 'var(--color-border)' }}><div className="flex justify-between gap-3"><b>{labels[event.type] || event.type}</b><small>{dateTime(event.timestamp)}</small></div><p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>{event.master_name || event.bot_username || `Telegram ID: ${event.master_telegram_id || event.telegram_id || '—'}`}{event.amount != null ? ` · ${money(event.amount)}` : ''}</p></div>)}</div>
  </>;
}
