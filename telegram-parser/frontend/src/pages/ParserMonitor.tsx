import ExternalParserPanel, { ParserPanelConfig } from '../components/ExternalParserPanel'

const cfg: ParserPanelConfig = {
  parser: 'monitor',
  title: 'Монитор каналов',
  subtitle: 'telegram-channels-monitor (volom) · реальное время, опрос каналов по ключевым словам',
  realtime: true,
  channelLabel: 'Каналы для мониторинга',
  channelPlaceholder: '@channel1\n@channel2\nhttps://t.me/channel3',
  channelsRequired: true,
  keywordLabel: 'Ключевые слова',
  keywordPlaceholder: 'ищу разработчика\nнужен дизайн\nвакансия',
  numericFields: [
    { key: 'time_pause', label: 'Пауза опроса, сек', def: 60, min: 10, max: 3600, step: 10 },
    { key: 'limit', label: 'Сообщений за проверку', def: 3, min: 1, max: 50, step: 1 },
  ],
  note: 'Подстрочный поиск (без учёта регистра). Каждые N секунд берёт последние сообщения каналов и ловит совпадения. Работает, пока не остановите.',
}

export default function ParserMonitor() {
  return <ExternalParserPanel cfg={cfg} />
}
