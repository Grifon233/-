import ExternalParserPanel, { ParserPanelConfig } from '../components/ExternalParserPanel'

const cfg: ParserPanelConfig = {
  parser: 'keywords',
  title: 'Парсер истории',
  subtitle: 'telegram-keywords-parser (minaton) · разовый обход истории чатов по ключевым словам',
  realtime: false,
  channelLabel: 'Чаты / каналы',
  channelPlaceholder: '@chat1\n@chat2\nhttps://t.me/chat3',
  channelsRequired: true,
  keywordLabel: 'Ключевые слова',
  keywordPlaceholder: 'python\nдизайнер\nвакансия',
  numericFields: [
    { key: 'days', label: 'За сколько дней', def: 2, min: 1, max: 90, step: 1 },
    { key: 'limit', label: 'Сообщений на чат', def: 100, min: 10, max: 5000, step: 10 },
  ],
  note: 'Поиск по словам целиком (токен должен совпасть с ключевым словом). Разовый прогон: обходит историю и завершается.',
}

export default function ParserKeywords() {
  return <ExternalParserPanel cfg={cfg} />
}
