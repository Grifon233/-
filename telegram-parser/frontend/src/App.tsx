import { lazy, Suspense } from 'react'
import { Routes, Route, Link, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import ErrorBoundary from './ErrorBoundary'
import {
  GridFour,
  UserCircle,
  Globe,
  Users,
  PaperPlaneTilt,
  TextAa,
  MagnifyingGlass,
  BookOpen,
  Bell,
  SignOut,
  Fire,
  Brain,
  VideoCamera,
  ThermometerHot,
  FolderSimple,
  ChatCircle,
  ShieldCheck,
  SpinnerGap,
  Television,
  Broadcast,
  ClockCounterClockwise,
  BellRinging,
  LinkSimple,
} from '@phosphor-icons/react'
import ApiErrorBanner from './components/ApiErrorBanner'
import api from './services/api'
import { useEffect, useState } from 'react'

type LazyImport<T extends React.ComponentType<any>> = () => Promise<{ default: T }>

function lazyRoute<T extends React.ComponentType<any>>(
  routeName: string,
  importer: LazyImport<T>,
) {
  return lazy(async () => {
    const retryKey = `lazy-route-retry:${routeName}`
    try {
      const module = await importer()
      sessionStorage.removeItem(retryKey)
      return module
    } catch (error) {
      const alreadyRetried = sessionStorage.getItem(retryKey) === '1'
      if (!alreadyRetried) {
        sessionStorage.setItem(retryKey, '1')
        window.location.reload()
        return new Promise<never>(() => undefined)
      }
      sessionStorage.removeItem(retryKey)
      throw error
    }
  })
}

// Lazy-load every page so the initial bundle stays small. Each page
// becomes its own chunk; users only pay for the page they're on. The
// previous version pulled every page into a single 1.2 MB bundle
// (recharts + framer-motion + react-markdown + phosphor all in the
// main chunk). See MED-09 in the 2026-06-04 audit.
const Dashboard = lazyRoute('Dashboard', () => import('./pages/Dashboard'))
const Accounts = lazyRoute('Accounts', () => import('./pages/Accounts'))
const PersonalChannel = lazyRoute('PersonalChannel', () => import('./pages/PersonalChannel'))
const Proxies = lazyRoute('Proxies', () => import('./pages/Proxies'))
const Contacts = lazyRoute('Contacts', () => import('./pages/Contacts'))
const Templates = lazyRoute('Templates', () => import('./pages/Templates'))
const Campaigns = lazyRoute('Campaigns', () => import('./pages/Campaigns'))
const Parsing = lazyRoute('Parsing', () => import('./pages/Parsing'))
const ParserMonitor = lazyRoute('ParserMonitor', () => import('./pages/ParserMonitor'))
const ParserKeywords = lazyRoute('ParserKeywords', () => import('./pages/ParserKeywords'))
const ParserAlertBot = lazyRoute('ParserAlertBot', () => import('./pages/ParserAlertBot'))
const KnowledgeBase = lazyRoute('KnowledgeBase', () => import('./pages/KnowledgeBase'))
const Reactions = lazyRoute('Reactions', () => import('./pages/Reactions'))
const Groups = lazyRoute('Groups', () => import('./pages/Groups'))
const VideoNotes = lazyRoute('VideoNotes', () => import('./pages/VideoNotes'))
const AISettings = lazyRoute('AISettings', () => import('./pages/AISettings'))
const Warmup = lazyRoute('Warmup', () => import('./pages/Warmup'))
const TelegramSources = lazyRoute('TelegramSources', () => import('./pages/TelegramSources'))
const NeuroCommenting = lazyRoute('NeuroCommenting', () => import('./pages/NeuroCommenting'))
const SafetyPage = lazyRoute('Safety', () => import('./pages/Safety'))
const JoinPool = lazyRoute('JoinPool', () => import('./pages/JoinPool'))

function PageFallback() {
  return (
    <div className="h-full flex items-center justify-center py-20">
      <div className="text-center">
        <SpinnerGap size={40} className="animate-spin text-primary/50 mx-auto mb-3" />
        <p className="text-muted-foreground text-sm">Загрузка страницы…</p>
      </div>
    </div>
  )
}

const menuItems = [
  // Порядок по просьбе владельца: аккаунты → нейрокомментинг → прогрев →
  // прокси → парсинг → личные каналы → источники → панель, дальше остальное.
  { path: '/accounts', label: 'Аккаунты', icon: UserCircle },
  { path: '/neuro-commenting', label: 'Нейрокоммент', icon: ChatCircle },
  { path: '/warmup', label: 'Прогрев', icon: ThermometerHot },
  { path: '/join-pool', label: 'Вступление в чаты', icon: LinkSimple },
  { path: '/proxies', label: 'Прокси', icon: Globe },
  { path: '/parsing', label: 'Парсинг', icon: MagnifyingGlass },
  { path: '/parser-monitor', label: 'Монитор каналов', icon: Broadcast },
  { path: '/parser-keywords', label: 'Парсер истории', icon: ClockCounterClockwise },
  { path: '/parser-alert-bot', label: 'Алёрт-бот', icon: BellRinging },
  { path: '/personal-channel', label: 'Личные каналы', icon: Television },
  { path: '/sources', label: 'Источники', icon: FolderSimple },
  { path: '/', label: 'Панель', icon: GridFour },
  { path: '/contacts', label: 'Контакты', icon: Users },
  { path: '/groups', label: 'Группы', icon: Users },
  { path: '/video-notes', label: 'Кружки', icon: VideoCamera },
  { path: '/campaigns', label: 'Рассылки', icon: PaperPlaneTilt },
  { path: '/templates', label: 'Шаблоны', icon: TextAa },
  { path: '/reactions', label: 'Реакции', icon: Fire },
  { path: '/ai', label: 'AI Настройки', icon: Brain },
  { path: '/knowledge', label: 'База знаний', icon: BookOpen },
  { path: '/safety', label: 'Безопасность', icon: ShieldCheck },
]

interface Project {
  id: number
  name: string
  is_active?: boolean
}

function ProjectSwitcher() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProjectId, setActiveProjectId] = useState(localStorage.getItem('active_project_id') || '1')

  const fetchProjects = async () => {
    const response = await api.get('/api/v1/projects')
    const nextProjects = response.data as Project[]
    setProjects(nextProjects)

    if (nextProjects.length === 0) return

    const backendActive = nextProjects.find(project => project.is_active)
    const current =
      localStorage.getItem('active_project_id') ||
      String(backendActive?.id || '') ||
      activeProjectId
    const exists = nextProjects.some(project => String(project.id) === String(current))
    if (!exists) {
      const fallbackId = String(nextProjects[0].id)
      localStorage.setItem('active_project_id', fallbackId)
      setActiveProjectId(fallbackId)
    } else if (String(current) !== String(activeProjectId)) {
      localStorage.setItem('active_project_id', String(current))
      setActiveProjectId(String(current))
    }
  }

  useEffect(() => {
    fetchProjects().catch(error => console.error('Ошибка загрузки проектов:', error))
  }, [])

  const createProject = async () => {
    const name = window.prompt('Название нового проекта')
    if (!name?.trim()) return
    const response = await api.post('/api/v1/projects', { name: name.trim() })
    setProjects(prev => [...prev, response.data])
    changeProject(String(response.data.id))
  }

  const changeProject = (projectId: string) => {
    api.post(`/api/v1/projects/${projectId}/activate`)
      .catch(error => console.error('Ошибка активации проекта:', error))
      .finally(() => {
        localStorage.setItem('active_project_id', projectId)
        setActiveProjectId(projectId)
        window.location.reload()
      })
  }

  return (
    <div className="p-4 border-b border-border/50 space-y-2">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">Текущий проект</p>
      <select value={activeProjectId} onChange={event => changeProject(event.target.value)} className="w-full px-3 py-2 rounded-xl border border-border bg-background text-sm">
        {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
      </select>
      <button onClick={createProject} className="text-xs text-primary hover:underline">+ Новый проект</button>
    </div>
  )
}

function NavItem({ path, label, icon: Icon, isActive, onClick }: {
  path: string
  label: string
  icon: React.ElementType
  isActive: boolean
  onClick: () => void
}) {
  return (
    <Link
      to={path}
      onClick={onClick}
      className={`
        relative flex items-center gap-3 px-4 py-3 rounded-2xl
        transition-all duration-300 group
        ${isActive
          ? 'bg-primary/10 text-primary'
          : 'text-muted-foreground hover:text-foreground hover:bg-muted'
        }
      `}
    >
      {isActive && (
        <motion.div
          layoutId="activeNav"
          className="absolute inset-0 bg-primary/10 rounded-2xl -z-10"
          initial={false}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
        />
      )}
      <Icon
        size={20}
        weight={isActive ? 'fill' : 'regular'}
        className="transition-transform duration-300 group-hover:scale-110"
      />
      <span className="font-medium text-sm">{label}</span>
    </Link>
  )
}

function App() {
  const location = useLocation()
  const [isMenuOpen, setIsMenuOpen] = useState(false)

  return (
    <div className="h-screen bg-background flex overflow-hidden">
        {/* Sidebar - Bento Grid Style */}
        <aside className="w-64 shrink-0 border-r bg-card/50 backdrop-blur-sm h-full flex flex-col">
          {/* Logo */}
          <div className="p-6 border-b border-border/50">
            <Link to="/" className="flex items-center gap-3 group">
              <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-primary-foreground font-bold text-lg shadow-lg shadow-primary/20">
                TG
              </div>
              <div>
                <h1 className="font-semibold text-lg tracking-tight">Комбайн</h1>
                <p className="text-xs text-muted-foreground">Telegram Management</p>
              </div>
            </Link>
          </div>
          <ProjectSwitcher />

          {/* Navigation - Bento Grid */}
          <nav className="flex-1 p-4 space-y-2 overflow-y-auto">
            {menuItems.map((item) => (
              <NavItem
                key={item.path}
                {...item}
                isActive={location.pathname === item.path}
                onClick={() => setIsMenuOpen(false)}
              />
            ))}
          </nav>

          {/* Footer - User Profile */}
          <div className="p-4 border-t border-border/50">
            <div className="flex items-center gap-3 p-3 rounded-2xl bg-muted/50 hover:bg-muted transition-colors cursor-pointer group">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-primary/80 to-primary flex items-center justify-center text-primary-foreground font-semibold text-sm shadow-md">
                Ю
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm truncate">Юрий Козлов</p>
                <p className="text-xs text-muted-foreground">Администратор</p>
              </div>
              <button className="p-2 rounded-lg hover:bg-background transition-colors text-muted-foreground hover:text-foreground">
                <SignOut size={18} />
              </button>
            </div>
          </div>
        </aside>

        {/* Main Content */}
        <main className="flex-1 min-w-0 h-screen overflow-y-auto">
          {/* Top Bar */}
          <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md border-b">
            <div className="flex items-center justify-between px-8 py-4">
              <div className="flex items-center gap-4">
                <h2 className="text-2xl font-semibold tracking-tight">
                  {menuItems.find(item => item.path === location.pathname)?.label || 'Панель'}
                </h2>
              </div>
              <div className="flex items-center gap-4">
                <button className="relative p-3 rounded-xl hover:bg-muted transition-colors text-muted-foreground hover:text-foreground">
                  <Bell size={20} />
                  <span className="absolute top-2 right-2 w-2 h-2 bg-primary rounded-full" />
                </button>
              </div>
            </div>
          </header>

          {/* Page Content with AnimatePresence */}
          <div className="p-8 pb-16">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                transition={{ duration: 0.2 }}
              >
                <ErrorBoundary>
                  <Suspense fallback={<PageFallback />}>
                    <Routes>
                      <Route path="/" element={<Dashboard />} />
                      <Route path="/accounts" element={<Accounts />} />
                      <Route path="/personal-channel" element={<PersonalChannel />} />
                      <Route path="/proxies" element={<Proxies />} />
                      <Route path="/contacts" element={<Contacts />} />
                      <Route path="/groups" element={<Groups />} />
                      <Route path="/sources" element={<TelegramSources />} />
                      <Route path="/video-notes" element={<VideoNotes />} />
                      <Route path="/campaigns" element={<Campaigns />} />
                      <Route path="/templates" element={<Templates />} />
                      <Route path="/parsing" element={<Parsing />} />
                      <Route path="/parser-monitor" element={<ParserMonitor />} />
                      <Route path="/parser-keywords" element={<ParserKeywords />} />
                      <Route path="/parser-alert-bot" element={<ParserAlertBot />} />
                      <Route path="/reactions" element={<Reactions />} />
                      <Route path="/ai" element={<AISettings />} />
                      <Route path="/neuro-commenting" element={<NeuroCommenting />} />
                      <Route path="/warmup" element={<Warmup />} />
                      <Route path="/join-pool" element={<JoinPool />} />
                      <Route path="/knowledge" element={<KnowledgeBase />} />
                      <Route path="/safety" element={<SafetyPage />} />
                    </Routes>
                  </Suspense>
                </ErrorBoundary>
              </motion.div>
            </AnimatePresence>
          </div>
        </main>
        {/* Grain Overlay */}
        <div className="grain-overlay" />

        {/* Global API error banner — surfaces network/401/5xx errors
            from the axios interceptor so the operator can see real
            backend problems instead of mock data fallback. */}
        <ApiErrorBanner />
      </div>
  )
}

export default App
