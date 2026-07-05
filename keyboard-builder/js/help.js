window.BK = window.BK || {};
(function (BK) {

  // ── Type reference data ─────────────────────────────────────────────────
  const TYPE_REF = [
    {
      icon: "📨", name: "Сообщение", color: "var(--c-message)",
      desc: "Бот отправляет текст, картинку и кнопки пользователю.",
      example: "Пример: «Привет! Выберите раздел: [Услуги] [Контакты]»",
    },
    {
      icon: "⚡", name: "Команда", color: "var(--c-command)",
      desc: "Точка входа: бот реагирует на /start, /help и другие команды.",
      example: "Пример: Пользователь пишет /start → бот начинает диалог",
    },
    {
      icon: "🔀", name: "Условие", color: "var(--c-condition)",
      desc: "Развилка: два выхода (Да/Нет). Позволяет строить разные сценарии.",
      example: "Пример: «Подписан на канал?» → Да: доступ / Нет: подпишись",
    },
    {
      icon: "⌨️", name: "Ожидание ввода", color: "var(--c-input)",
      desc: "Бот ждёт ответа пользователя и сохраняет его в переменную.",
      example: "Пример: «Введите ваше имя:» → сохранить в user_name",
    },
    {
      icon: "⏳", name: "Задержка", color: "var(--c-delay)",
      desc: "Пауза N секунд перед следующим шагом. Создаёт эффект «печатает».",
      example: "Пример: После «Загружаю...» → ждём 2с → показываем меню",
    },
    {
      icon: "📦", name: "Переменная", color: "var(--c-variable)",
      desc: "Устанавливает значение переменной. Можно использовать {{другая}}.",
      example: "Пример: status = «подписан» / score = {{score}} + 1",
    },
    {
      icon: "🌐", name: "HTTP-запрос", color: "var(--c-api)",
      desc: "Запрос к внешнему API (GET/POST). Результат сохраняется в переменную.",
      example: "Пример: GET https://api.example.com/user/{{user_id}} → сохранить в response",
    },
  ];

  // ── Templates ────────────────────────────────────────────────────────────
  const TEMPLATES = [
    {
      id: "business-card",
      icon: "🏢",
      title: "Бот-визитка",
      desc: "Самый популярный тип бота. Пользователь нажимает /start и попадает в меню с разделами. Каждая кнопка ведёт на отдельную страницу с информацией.",
      flow:
"⚡ /start\n" +
"  └→ 📨 Привет! Выберите раздел:\n" +
"        ├─ [🏢 О нас]      → 📨 О компании + [← Назад]\n" +
"        ├─ [💼 Услуги]     → 📨 Список услуг + [← Назад]\n" +
"        └─ [📞 Контакты]   → 📨 Контактные данные + [← Назад]",
      steps: [
        ["Пользователь пишет <b>/start</b>", "Срабатывает блок «Команда» — точка входа в бота"],
        ["Бот отправляет <b>приветствие</b>", "Сообщение с тремя кнопками-разделами"],
        ["Нажатие на кнопку раздела", "Бот открывает соответствующую страницу с текстом"],
        ["Кнопка <b>← Назад</b>", "Возвращает пользователя в главное меню"],
      ],
      state: {
        version: 2,
        windows: [
          { id:"t1_cmd",  type:"command",  title:"Запуск",      x:50,  y:200, note:"Точка входа. Пользователь пишет /start", command:"/start", image:null, text:"", buttons:[{id:"t1_b1",label:"Перейти",action:"goto",target:"t1_hi",url:"",row:0}] },
          { id:"t1_hi",   type:"message",  title:"Приветствие", x:360, y:100, note:"Первый экран — приветствие и навигационные кнопки", image:null, text:"👋 Привет! Я бот нашей компании.\n\nВыберите, что вас интересует:", buttons:[{id:"t1_b2",label:"🏢 О нас",action:"goto",target:"t1_about",url:"",row:0},{id:"t1_b3",label:"💼 Услуги",action:"goto",target:"t1_svc",url:"",row:1},{id:"t1_b4",label:"📞 Контакты",action:"goto",target:"t1_cnt",url:"",row:2}] },
          { id:"t1_about",type:"message",  title:"О нас",       x:680, y:30,  note:"Раздел «О нас» — история и описание компании", image:null, text:"🏢 О нашей компании\n\nМы работаем с 2015 года. Наша команда — 50+ специалистов. Помогаем бизнесу автоматизировать продажи.\n\n🌐 Сайт: example.com", buttons:[] },
          { id:"t1_svc",  type:"message",  title:"Услуги",      x:680, y:210, note:"Раздел «Услуги» — что предлагает компания", image:null, text:"💼 Наши услуги:\n\n• Разработка Telegram-ботов\n• Настройка CRM-систем\n• SMM и маркетинг\n• Консалтинг\n\n📩 Напишите нам для расчёта стоимости.", buttons:[] },
          { id:"t1_cnt",  type:"message",  title:"Контакты",    x:680, y:390, note:"Раздел «Контакты» — как связаться", image:null, text:"📞 Контакты:\n\n📱 Телефон: +7 900 000-00-00\n✉️ Email: info@example.com\n🌐 Сайт: example.com\n\n⏰ Работаем Пн–Пт, 9:00–18:00", buttons:[] },
        ]
      },
    },

    {
      id: "data-collect",
      icon: "📋",
      title: "Сбор данных",
      desc: "Бот задаёт вопросы по очереди и сохраняет ответы в переменные. Используется для регистрации, заявок, анкет, записи на услуги.",
      flow:
"⚡ /start\n" +
"  └→ 📨 «Как вас зовут?»\n" +
"        └→ ⌨️ Ждём имя → сохр. user_name\n" +
"              └→ 📨 «Ваш телефон?»\n" +
"                    └→ ⌨️ Ждём телефон → сохр. user_phone\n" +
"                          └→ 📨 «Спасибо! Данные получены»",
      steps: [
        ["Блок <b>Команда</b>", "Запускает сценарий по /start"],
        ["Блок <b>Сообщение</b>", "Бот задаёт вопрос: «Как вас зовут?»"],
        ["Блок <b>Ожидание ввода</b>", "Бот ждёт ответ, сохраняет в переменную user_name"],
        ["Блок <b>Сообщение</b>", "Второй вопрос: «Ваш телефон?»"],
        ["Блок <b>Ожидание ввода</b>", "Ждёт телефон, сохраняет в user_phone"],
        ["Блок <b>Сообщение</b>", "Подтверждение — данные сохранены"],
      ],
      state: {
        version: 2,
        windows: [
          { id:"t2_cmd",  type:"command", title:"Запуск",      x:50,  y:230, note:"Точка входа", command:"/start", image:null, text:"", buttons:[{id:"t2_b1",label:"Начать",action:"goto",target:"t2_q1",url:"",row:0}] },
          { id:"t2_q1",   type:"message", title:"Вопрос: имя", x:330, y:130, note:"Просим пользователя ввести имя. После сообщения ставим блок ожидания", image:null, text:"✍️ Давайте познакомимся!\n\nКак вас зовут? Напишите ваше имя:", buttons:[{id:"t2_b2",label:"Далее →",action:"goto",target:"t2_in1",url:"",row:0}] },
          { id:"t2_in1",  type:"input",   title:"Ждём имя",    x:610, y:130, note:"Бот ждёт ответ пользователя. Ответ сохраняется в переменную user_name", variable_name:"user_name", text:"Введите ваше имя:", image:null, buttons:[{id:"t2_b3",label:"Далее →",action:"goto",target:"t2_q2",url:"",row:0}] },
          { id:"t2_q2",   type:"message", title:"Вопрос: тел", x:890, y:130, note:"Второй вопрос — запрашиваем телефон", image:null, text:"📱 Отлично!\n\nТеперь введите ваш номер телефона:", buttons:[{id:"t2_b4",label:"Далее →",action:"goto",target:"t2_in2",url:"",row:0}] },
          { id:"t2_in2",  type:"input",   title:"Ждём телефон",x:1170,y:130, note:"Сохраняем номер телефона в переменную user_phone", variable_name:"user_phone", text:"Введите ваш телефон:", image:null, buttons:[{id:"t2_b5",label:"Готово ✓",action:"goto",target:"t2_done",url:"",row:0}] },
          { id:"t2_done", type:"message", title:"Готово",      x:1170,y:310, note:"Финальное сообщение. Здесь можно добавить отправку данных в CRM через HTTP-запрос", image:null, text:"✅ Спасибо!\n\nМы получили ваши данные:\n• Имя: {{user_name}}\n• Телефон: {{user_phone}}\n\nМенеджер свяжется с вами в течение 15 минут.", buttons:[] },
        ]
      },
    },

    {
      id: "condition",
      icon: "🔀",
      title: "Развилка по условию",
      desc: "Бот проверяет условие (например, подписан ли пользователь) и ведёт по разным сценариям. Используется для проверки доступа, A/B тестов, квалификации лидов.",
      flow:
"⚡ /start\n" +
"  └→ 🔀 «Подписан на канал?»\n" +
"        ├─ [Да ✓] → 📨 Доступ открыт\n" +
"        │              └─ [📚 Материалы] → внешняя ссылка\n" +
"        └─ [Нет ✕] → 📨 Нужно подписаться\n" +
"                        ├─ [📢 Подписаться] → внешняя ссылка\n" +
"                        └─ [✅ Готово] → снова к условию",
      steps: [
        ["Блок <b>Условие</b>", "Описываете логику проверки: «Пользователь подписан?»"],
        ["Кнопка <b>Да ✓</b>", "Ведёт к позитивному сценарию — доступ, контент, скидка"],
        ["Кнопка <b>Нет ✕</b>", "Ведёт к блокирующему экрану с инструкцией"],
        ["Кнопка <b>✅ Готово</b>", "Возвращает обратно к условию — повторная проверка"],
      ],
      state: {
        version: 2,
        windows: [
          { id:"t3_cmd",  type:"command",   title:"Запуск",      x:50,  y:220, note:"Точка входа", command:"/start", image:null, text:"", buttons:[{id:"t3_b1",label:"Далее →",action:"goto",target:"t3_cond",url:"",row:0}] },
          { id:"t3_cond", type:"condition", title:"Проверка",    x:330, y:170, note:"Здесь описываете условие. Бот программно решает — куда направить пользователя", condition_text:"Пользователь подписан на @channel?", buttons:[{id:"t3_b2",label:"Да ✓",action:"goto",target:"t3_yes",url:"",row:0},{id:"t3_b3",label:"Нет ✕",action:"goto",target:"t3_no",url:"",row:1}] },
          { id:"t3_yes",  type:"message",   title:"Подписан",    x:620, y:60,  note:"Ветка ДА — пользователь выполнил условие. Открываем доступ", image:null, text:"🎉 Отлично! Вы подписаны на наш канал.\n\nВам открыт доступ к эксклюзивным материалам:", buttons:[{id:"t3_b4",label:"📚 Получить материалы",action:"url",target:null,url:"https://example.com",row:0}] },
          { id:"t3_no",   type:"message",   title:"Не подписан", x:620, y:280, note:"Ветка НЕТ — предлагаем выполнить условие, потом вернуться", image:null, text:"❌ Вы не подписаны на наш канал.\n\nПодпишитесь, чтобы получить доступ к материалам:", buttons:[{id:"t3_b5",label:"📢 Подписаться на канал",action:"url",target:null,url:"https://t.me/channel",row:0}] },
        ]
      },
    },

    {
      id: "delay-menu",
      icon: "⏳",
      title: "Меню с задержкой и API",
      desc: "Реалистичный бот: сначала «печатает», потом показывает меню. Один из пунктов загружает данные через HTTP-запрос. Показывает как связать задержку, меню и внешние данные.",
      flow:
"⚡ /start\n" +
"  └→ 📨 «Загружаю меню...»\n" +
"        └→ ⏳ Пауза 2 сек\n" +
"              └→ 📨 Главное меню [Каталог] [Поддержка]\n" +
"                    ├─ [🛒 Каталог] → 🌐 GET /products\n" +
"                    │                    ├─ [✓ Успешно] → 📨 Список товаров\n" +
"                    │                    └─ [✕ Ошибка]  → 📨 Ошибка загрузки\n" +
"                    └─ [💬 Поддержка] → 📨 Контакты менеджера",
      steps: [
        ["Блок <b>Задержка</b>", "Имитирует «бот печатает...» — делает диалог живым"],
        ["Блок <b>Сообщение</b> (меню)", "Главное меню с кнопками разделов"],
        ["Блок <b>HTTP-запрос</b>", "Загружает товары с сервера (GET-запрос)"],
        ["Кнопки <b>Успешно / Ошибка</b>", "Разные экраны в зависимости от ответа API"],
      ],
      state: {
        version: 2,
        windows: [
          { id:"t4_cmd",    type:"command",  title:"Запуск",          x:50,  y:250, note:"Точка входа", command:"/start", image:null, text:"", buttons:[{id:"t4_b1",label:"Начать",action:"goto",target:"t4_typing",url:"",row:0}] },
          { id:"t4_typing", type:"message",  title:"Эффект печати",   x:310, y:250, note:"Первое сообщение создаёт ощущение живого бота. После него — задержка", image:null, text:"⌨️ Загружаю меню, секунду...", buttons:[{id:"t4_b2",label:"Далее →",action:"goto",target:"t4_delay",url:"",row:0}] },
          { id:"t4_delay",  type:"delay",    title:"Пауза 2с",        x:570, y:250, note:"Ждём 2 секунды — имитация эффекта «печатает» в Telegram", delay_seconds:2, buttons:[{id:"t4_b3",label:"Далее →",action:"goto",target:"t4_menu",url:"",row:0}] },
          { id:"t4_menu",   type:"message",  title:"Главное меню",    x:830, y:150, note:"Главное меню. Задержка перед ним делает появление более естественным", image:null, text:"📋 Главное меню\n\nЧто вас интересует?", buttons:[{id:"t4_b4",label:"🛒 Каталог товаров",action:"goto",target:"t4_api",url:"",row:0},{id:"t4_b5",label:"💬 Поддержка",action:"goto",target:"t4_sup",url:"",row:1}] },
          { id:"t4_api",    type:"api",      title:"Загрузка товаров",x:1090,y:80,  note:"HTTP-запрос к серверу. Если ответ успешный — показываем товары. Если ошибка — сообщаем об этом", api_url:"https://api.example.com/products", api_method:"GET", api_save_to:"products_list", buttons:[{id:"t4_b6",label:"✓ Успешно",action:"goto",target:"t4_ok",url:"",row:0},{id:"t4_b7",label:"✕ Ошибка",action:"goto",target:"t4_err",url:"",row:1}] },
          { id:"t4_ok",     type:"message",  title:"Каталог",         x:1370,y:30,  note:"Показываем загруженные товары", image:null, text:"🛒 Наш каталог:\n\n• Товар 1 — 1 000 ₽\n• Товар 2 — 2 500 ₽\n• Товар 3 — 5 000 ₽\n\nДля заказа напишите менеджеру.", buttons:[{id:"t4_b8",label:"← Меню",action:"goto",target:"t4_menu",url:"",row:0}] },
          { id:"t4_err",    type:"message",  title:"Ошибка API",      x:1370,y:220, note:"Показываем ошибку если API не ответил", image:null, text:"⚠️ Не удалось загрузить каталог.\n\nПопробуйте позже или свяжитесь с нами.", buttons:[{id:"t4_b9",label:"← Меню",action:"goto",target:"t4_menu",url:"",row:0}] },
          { id:"t4_sup",    type:"message",  title:"Поддержка",       x:1090,y:330, note:"Контакты поддержки", image:null, text:"💬 Поддержка:\n\nМенеджер ответит в течение 15 минут.\n📱 @support_manager", buttons:[] },
        ]
      },
    },
  ];

  // ── Build type reference section ────────────────────────────────────────
  function buildTypeRef() {
    const section = document.createElement("div");
    const title = document.createElement("div");
    title.className = "help-section-title"; title.textContent = "Типы блоков — что каждый делает";
    const grid = document.createElement("div"); grid.className = "help-types-grid";
    TYPE_REF.forEach(t => {
      const card = document.createElement("div"); card.className = "help-type-card";
      card.style.borderLeft = "3px solid " + t.color;
      const head = document.createElement("div"); head.className = "help-type-head";
      head.innerHTML = `<span class="help-type-icon">${t.icon}</span>${t.name}`;
      const desc = document.createElement("div"); desc.className = "help-type-desc"; desc.textContent = t.desc;
      const ex = document.createElement("div"); ex.className = "help-type-example"; ex.textContent = t.example;
      card.append(head, desc, ex); grid.appendChild(card);
    });
    section.append(title, grid);
    return section;
  }

  // ── Build single template card ──────────────────────────────────────────
  function buildCard(tpl, onLoad) {
    const card = document.createElement("div"); card.className = "help-card";
    const hdr = document.createElement("div"); hdr.className = "help-card-hdr";
    hdr.innerHTML = `<span class="help-card-icon">${tpl.icon}</span><span class="help-card-title">${tpl.title}</span>`;
    const desc = document.createElement("p"); desc.className = "help-card-desc"; desc.textContent = tpl.desc;

    const flow = document.createElement("div"); flow.className = "help-flow"; flow.textContent = tpl.flow;

    const stepsWrap = document.createElement("div"); stepsWrap.className = "help-steps";
    tpl.steps.forEach((step, i) => {
      const row = document.createElement("div"); row.className = "help-step";
      const num = document.createElement("div"); num.className = "help-step-num"; num.textContent = i + 1;
      const txt = document.createElement("div"); txt.className = "help-step-text"; txt.innerHTML = step[0] + " — " + step[1];
      row.append(num, txt); stepsWrap.appendChild(row);
    });

    const loadBtn = document.createElement("button"); loadBtn.className = "help-load-btn";
    loadBtn.textContent = "Загрузить этот пример →";
    loadBtn.addEventListener("click", () => onLoad(tpl));

    card.append(hdr, desc, flow, stepsWrap, loadBtn);
    return card;
  }

  // ── Main open function ──────────────────────────────────────────────────
  function openHelp(renderAll) {
    const existing = document.getElementById("help-overlay");
    if (existing) { existing.remove(); return; }

    const overlay = document.createElement("div");
    overlay.id = "help-overlay"; overlay.className = "help-overlay";
    overlay.addEventListener("click", e => { if (e.target === overlay) overlay.remove(); });

    const modal = document.createElement("div"); modal.className = "help-modal";

    // Header
    const hdr = document.createElement("div"); hdr.className = "help-modal-hdr";
    const hdrLeft = document.createElement("div");
    hdrLeft.innerHTML = '<div class="help-modal-title">📖 Помощь и примеры</div>' +
      '<div class="help-modal-sub">Изучите типы блоков и загрузите готовый пример для старта</div>';
    const closeBtn = document.createElement("button"); closeBtn.className = "help-close"; closeBtn.textContent = "✕";
    closeBtn.addEventListener("click", () => overlay.remove());
    hdr.append(hdrLeft, closeBtn);

    // Callback for template load
    function onLoad(tpl) {
      const hasWork = BK.getState().windows.length > 0;
      if (hasWork && !confirm('Загрузить пример "' + tpl.title + '"?\nТекущий проект будет заменён.')) return;
      BK.replaceState(JSON.parse(JSON.stringify(tpl.state)));
      renderAll();
      overlay.remove();
    }

    // Templates grid
    const templatesTitle = document.createElement("div");
    templatesTitle.className = "help-section-title"; templatesTitle.textContent = "Готовые примеры — загрузите и посмотрите как устроен бот";
    const grid = document.createElement("div"); grid.className = "help-templates";
    TEMPLATES.forEach(tpl => grid.appendChild(buildCard(tpl, onLoad)));

    modal.append(hdr, buildTypeRef(), templatesTitle, grid);
    overlay.appendChild(modal);
    document.body.appendChild(overlay);
  }

  Object.assign(BK, { openHelp });
})(window.BK);
