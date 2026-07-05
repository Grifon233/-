import ExternalParserPanel, { ParserPanelConfig } from '../components/ExternalParserPanel'

const cfg: ParserPanelConfig = {
  parser: 'alert_bot',
  title: 'Алёрт-бот',
  subtitle: 'keyword_alert_bot (crazypeace) · реальное время, событийный, поддержка regex и дедупликации',
  realtime: true,
  channelLabel: 'Каналы (пусто = все, где состоит аккаунт)',
  channelPlaceholder: '@channel1\n@channel2  (или оставьте пустым)',
  channelsRequired: false,
  keywordLabel: 'Ключевые слова или /regex/',
  keywordPlaceholder: 'разработчик\n/ваканси[ия]/i\n/\\bpython\\b/i',
  numericFields: [
    { key: 'dedup_expire', label: 'Антидубль, сек', def: 5, min: 1, max: 86400, step: 1 },
  ],
  note: 'Ловит новые и отредактированные сообщения в реальном времени. Ключ в виде /шаблон/флаги воспринимается как регулярное выражение (флаги i, g). Дубликаты в окне антидубля не повторяются. Работает, пока не остановите.',
}

export default function ParserAlertBot() {
  return <ExternalParserPanel cfg={cfg} />
}
