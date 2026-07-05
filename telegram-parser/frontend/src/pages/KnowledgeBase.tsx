import { useState, useEffect } from 'react'
import api from '../services/api'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import {
  BookOpen,
  CaretRight,
  Lightbulb,
  ShieldCheck,
  Robot,
  RocketLaunch,
  MagnifyingGlass
} from '@phosphor-icons/react'

interface ArticleSummary {
  id: string
  title: string
  category: string
}

interface Article {
  id: string
  title: string
  category: string
  content: string
}

const categoryIcons: Record<string, any> = {
  'Обучение': RocketLaunch,
  'AI': Robot,
  'Безопасность': ShieldCheck,
  'Стратегии': Lightbulb
}

export default function KnowledgeBase() {
  const [summaries, setSummaries] = useState<ArticleSummary[]>([])
  const [selectedArticle, setSelectedArticle] = useState<Article | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    fetchSummaries()
  }, [])

  const fetchSummaries = async () => {
    try {
      const res = await api.get('/api/v1/kb/articles')
      setSummaries(res.data)
      if (res.data.length > 0 && !selectedArticle) {
        fetchArticle(res.data[0].id)
      }
    } catch (error) {
      console.error('Error fetching articles:', error)
    } finally {
      setLoading(false)
    }
  }

  const fetchArticle = async (id: string) => {
    try {
      const res = await api.get(`/api/v1/kb/articles/${id}`)
      setSelectedArticle(res.data)
    } catch (error) {
      console.error('Error fetching article content:', error)
    }
  }

  const filteredSummaries = summaries.filter(s => 
    s.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
    s.category.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="flex h-[calc(100vh-120px)] gap-8">
      {/* Sidebar List */}
      <div className="w-80 flex flex-col gap-6">
        <div className="relative">
          <MagnifyingGlass className="absolute left-4 top-1/2 -translate-y-1/2 text-muted-foreground" size={18} />
          <input
            type="text"
            placeholder="Поиск статей..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full pl-11 pr-4 py-3 rounded-2xl border border-border bg-card focus:border-primary outline-none transition-colors"
          />
        </div>

        <div className="flex-1 overflow-y-auto space-y-2 pr-2 custom-scrollbar">
          {filteredSummaries.map((article) => {
            const Icon = categoryIcons[article.category] || BookOpen
            const isActive = selectedArticle?.id === article.id

            return (
              <button
                key={article.id}
                onClick={() => fetchArticle(article.id)}
                className={`
                  w-full text-left p-4 rounded-2xl transition-all duration-200 flex items-center gap-4 group
                  ${isActive 
                    ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/20' 
                    : 'hover:bg-muted bg-card border border-border/50'
                  }
                `}
              >
                <div className={`
                  w-10 h-10 rounded-xl flex items-center justify-center
                  ${isActive ? 'bg-white/20' : 'bg-primary/10 text-primary'}
                `}>
                  <Icon size={20} weight={isActive ? 'fill' : 'duotone'} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs opacity-70 font-medium uppercase tracking-wider">{article.category}</p>
                  <p className="font-semibold truncate leading-tight mt-0.5">{article.title}</p>
                </div>
                <CaretRight size={16} className={isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100 transition-opacity'} />
              </button>
            )
          })}
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 bg-card rounded-[32px] border border-border overflow-hidden flex flex-col shadow-sm">
        <AnimatePresence mode="wait">
          {selectedArticle ? (
            <motion.div
              key={selectedArticle.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="h-full overflow-y-auto p-12 custom-scrollbar"
            >
              <div className="max-w-3xl mx-auto">
                <div className="flex items-center gap-3 text-primary mb-6">
                  <span className="px-3 py-1 rounded-full bg-primary/10 text-xs font-bold uppercase tracking-widest">
                    {selectedArticle.category}
                  </span>
                </div>
                <h1 className="text-4xl font-extrabold tracking-tight mb-10 leading-tight">
                  {selectedArticle.title}
                </h1>
                <div className="prose prose-slate prose-invert max-w-none 
                  prose-headings:font-bold prose-headings:tracking-tight
                  prose-h1:text-3xl prose-h2:text-2xl prose-h2:mt-12 prose-h2:mb-6
                  prose-p:text-muted-foreground prose-p:leading-relaxed prose-p:text-lg
                  prose-li:text-muted-foreground prose-li:text-lg
                  prose-strong:text-foreground prose-strong:font-bold
                  prose-blockquote:border-l-primary prose-blockquote:bg-muted/50 prose-blockquote:p-6 prose-blockquote:rounded-r-2xl prose-blockquote:not-italic
                  prose-code:text-primary prose-code:bg-primary/5 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:before:content-none prose-code:after:content-none
                ">
                  <ReactMarkdown>{selectedArticle.content}</ReactMarkdown>
                </div>
              </div>
            </motion.div>
          ) : (
            <div className="h-full flex flex-col items-center justify-center text-center p-12">
              <div className="w-20 h-20 rounded-full bg-muted flex items-center justify-center mb-6">
                <BookOpen size={40} className="text-muted-foreground" />
              </div>
              <h3 className="text-xl font-semibold">Выберите статью</h3>
              <p className="text-muted-foreground mt-2 max-w-xs">
                Выберите статью из списка слева, чтобы прочитать инструкцию или стратегию.
              </p>
            </div>
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}
