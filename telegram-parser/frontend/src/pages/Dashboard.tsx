import { useState, useEffect } from 'react'
import api from '../services/api'
import { motion } from 'framer-motion'
import { 
  AreaChart, 
  Area, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell
} from 'recharts'
import {
  Users,
  PaperPlaneTilt,
  Fire,
  CheckCircle,
  UsersThree,
  ArrowUpRight,
  DotsThreeVertical,
  TrendUp,
  Warning,
  Pulse
} from '@phosphor-icons/react'

interface Stats {
  summary: {
    total_accounts: number
    active_accounts: number
    total_messages: number
    success_rate: number
    total_reactions: number
    total_groups: number
  }
  activity_chart: Array<{name: string, messages: number}>
  recent_campaigns?: Array<any>
}

function StatCard({ title, value, subValue, icon: Icon, color }: any) {
  return (
    <motion.div 
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-card p-6 rounded-[32px] border border-border/50 shadow-sm relative overflow-hidden group hover:border-primary/50 transition-colors"
    >
      <div className="flex justify-between items-start mb-4">
        <div className={`p-3 rounded-2xl ${color} bg-opacity-10 text-opacity-100`}>
          <Icon size={24} weight="duotone" className={color.replace('bg-', 'text-')} />
        </div>
        <button className="text-muted-foreground hover:text-foreground p-1">
          <DotsThreeVertical size={20} />
        </button>
      </div>
      <div>
        <h3 className="text-muted-foreground text-sm font-medium mb-1">{title}</h3>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold tracking-tight">{value}</span>
          {subValue && (
            <span className="text-xs font-semibold text-emerald-500 flex items-center gap-0.5">
              <TrendUp size={14} />
              {subValue}
            </span>
          )}
        </div>
      </div>
      
      {/* Decorative background shape */}
      <div className={`absolute -right-4 -bottom-4 w-24 h-24 rounded-full opacity-5 group-hover:opacity-10 transition-opacity ${color}`} />
    </motion.div>
  )
}

export default function Dashboard() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      const res = await api.get('/api/v1/analytics/dashboard')
      setStats(res.data)
      setError(null)
    } catch (err: any) {
      console.error('Error fetching dashboard stats:', err)
      setError(err.message || 'Failed to load dashboard')
      // Set empty stats to show UI
      setStats({
        summary: {
          total_accounts: 0,
          active_accounts: 0,
          total_messages: 0,
          success_rate: 0,
          total_reactions: 0,
          total_groups: 0,
        },
        activity_chart: [],
        recent_campaigns: []
      })
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Pulse size={48} className="animate-pulse text-primary/50" />
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <Warning size={48} className="mx-auto mb-4 text-destructive" />
          <p className="text-muted-foreground">{error || 'Failed to load dashboard'}</p>
          <button onClick={fetchStats} className="mt-4 px-4 py-2 bg-primary text-primary-foreground rounded-lg">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-8">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-4xl font-extrabold tracking-tight">Обзор системы</h1>
          <p className="text-muted-foreground mt-2 text-lg">Добро пожаловать в центр управления вашим комбайном.</p>
        </div>
        <div className="flex gap-3">
          <div className="px-4 py-2 rounded-xl bg-card border border-border flex items-center gap-2 text-sm font-medium">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            Все системы в норме
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard 
          title="Активные аккаунты" 
          value={`${stats.summary.active_accounts}/${stats.summary.total_accounts}`} 
          subValue="+2 за сегодня"
          icon={Users} 
          color="bg-blue-500" 
        />
        <StatCard 
          title="Всего сообщений" 
          value={stats.summary.total_messages.toLocaleString()} 
          subValue={`${stats.summary.success_rate}% успех`}
          icon={PaperPlaneTilt} 
          color="bg-purple-500" 
        />
        <StatCard 
          title="Масс-реакции" 
          value={stats.summary.total_reactions.toLocaleString()} 
          icon={Fire} 
          color="bg-orange-500" 
        />
        <StatCard 
          title="Группы" 
          value={stats.summary.total_groups.toLocaleString()} 
          icon={UsersThree} 
          color="bg-emerald-500" 
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Chart */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          className="lg:col-span-2 bg-card p-8 rounded-[32px] border border-border/50 shadow-sm"
        >
          <div className="flex justify-between items-center mb-8">
            <div>
              <h3 className="text-xl font-bold">Активность рассылок</h3>
              <p className="text-sm text-muted-foreground mt-1">Количество отправленных сообщений за 7 дней</p>
            </div>
            <select className="bg-muted px-4 py-2 rounded-xl text-sm border-none outline-none">
              <option>Последние 7 дней</option>
              <option>Месяц</option>
            </select>
          </div>
          <div className="h-[350px] w-full">
            <ResponsiveContainer width="100%" height={350} minHeight={300}>
              <AreaChart data={stats.activity_chart}>
                <defs>
                  <linearGradient id="colorMsg" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#E2E8F0" />
                <XAxis 
                  dataKey="name" 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#94A3B8', fontSize: 12}} 
                  dy={10}
                />
                <YAxis 
                  axisLine={false} 
                  tickLine={false} 
                  tick={{fill: '#94A3B8', fontSize: 12}}
                />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: '#1E293B', 
                    border: 'none', 
                    borderRadius: '16px', 
                    color: '#fff',
                    boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1)' 
                  }}
                  itemStyle={{ color: '#fff' }}
                />
                <Area 
                  type="monotone" 
                  dataKey="messages" 
                  stroke="#3b82f6" 
                  strokeWidth={4}
                  fillOpacity={1} 
                  fill="url(#colorMsg)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </motion.div>

        {/* Status Distribution */}
        <motion.div 
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          className="bg-card p-8 rounded-[32px] border border-border/50 shadow-sm"
        >
          <h3 className="text-xl font-bold mb-8">Эффективность</h3>
          <div className="space-y-6">
            <div className="relative pt-1">
              <div className="flex mb-2 items-center justify-between">
                <div>
                  <span className="text-xs font-semibold inline-block py-1 px-2 uppercase rounded-full text-emerald-600 bg-emerald-200">
                    Доставлено
                  </span>
                </div>
                <div className="text-right">
                  <span className="text-xs font-semibold inline-block text-emerald-600">
                    {stats.summary.success_rate}%
                  </span>
                </div>
              </div>
              <div className="overflow-hidden h-3 mb-4 text-xs flex rounded-full bg-emerald-100">
                <motion.div 
                  initial={{ width: 0 }}
                  animate={{ width: `${stats.summary.success_rate}%` }}
                  className="shadow-none flex flex-col text-center whitespace-nowrap text-white justify-center bg-emerald-500" 
                />
              </div>
            </div>

            <div className="p-6 rounded-3xl bg-muted/50 border border-border">
              <h4 className="text-sm font-bold flex items-center gap-2 mb-4">
                <Pulse size={18} className="text-primary" />
                Статистика работы
              </h4>
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 bg-card rounded-2xl border border-border/50">
                  <p className="text-xs text-muted-foreground uppercase mb-1">Реакций</p>
                  <p className="text-xl font-bold">{stats.summary.total_reactions}</p>
                </div>
                <div className="text-center p-3 bg-card rounded-2xl border border-border/50">
                  <p className="text-xs text-muted-foreground uppercase mb-1">Вступлений</p>
                  <p className="text-xl font-bold">{stats.summary.total_groups}</p>
                </div>
              </div>
            </div>

            <div className="pt-4">
              <button className="w-full py-4 rounded-2xl bg-primary text-primary-foreground font-bold hover:opacity-90 transition-all flex items-center justify-center gap-2 shadow-lg shadow-primary/20">
                Детальный отчет
                <ArrowUpRight size={18} weight="bold" />
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  )
}
