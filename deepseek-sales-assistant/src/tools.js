export const toolDefinitions = [
  {
    type: "function",
    function: {
      name: "lookup_case_catalog",
      description:
        "Получить точные сведения о текущем тестовом кейсе: компания, предложения, цены, доставка, гарантия, документы и подсказки по возражениям.",
      parameters: {
        type: "object",
        properties: {
          query: {
            type: "string",
            description: "Что именно нужно узнать о предложениях, условиях, сроках или совместимости"
          }
        },
        required: ["query"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "recommend_product_bundle",
      description:
        "Подобрать товар, услугу или комплект из активного кейса по задаче клиента, бюджету, объему, срочности и ограничениям.",
      parameters: {
        type: "object",
        properties: {
          needs: {
            type: "string",
            description: "Что клиент хочет купить/заказать или какую проблему решить"
          },
          budget: {
            type: "string",
            description: "Бюджет или ограничение по цене, если клиент назвал"
          },
          volume: {
            type: "string",
            description: "Количество, площадь, объем закупки, маршрут, размеры, модель или другие параметры"
          },
          priority: {
            type: "string",
            description: "Главный критерий: цена, срок, надежность, совместимость, документы"
          }
        },
        required: ["needs"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "calculate_logistics_quote",
      description:
        "Рассчитать предварительную стоимость логистической перевозки по городам, весу груза и подходящей грузоподъемности. Использовать для кейса Логистика, когда клиент назвал маршрут или просит цену перевозки.",
      parameters: {
        type: "object",
        properties: {
          origin_city: {
            type: "string",
            description: "Город отправки"
          },
          destination_city: {
            type: "string",
            description: "Город назначения"
          },
          cargo_weight_tons: {
            type: "number",
            description: "Вес груза в тоннах"
          },
          vehicle_hint: {
            type: "string",
            description: "Какой транспорт просит клиент: фура, газель, 12-тонник, реф, тент и т.п."
          },
          distance_km: {
            type: "number",
            description: "Километраж маршрута, если клиент сам назвал точный километраж"
          }
        },
        required: ["cargo_weight_tons"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "create_quote",
      description:
        "Сымитировать подготовку счета, резерва, сметы или коммерческого предложения. Использовать после согласия клиента на следующий шаг.",
      parameters: {
        type: "object",
        properties: {
          items: {
            type: "string",
            description: "Какие товары, услуги или комплект включить"
          },
          customer_name: {
            type: "string",
            description: "Имя клиента или компании"
          },
          contact: {
            type: "string",
            description: "Контакт клиента: телефон, email или мессенджер"
          },
          delivery_city: {
            type: "string",
            description: "Город доставки или самовывоз"
          }
        },
        required: ["items"]
      }
    }
  },
  {
    type: "function",
    function: {
      name: "create_payment_link",
      description:
        "Сымитировать ссылку на оплату по выбранному предложению. Использовать только после подтверждения состава, цены и количества.",
      parameters: {
        type: "object",
        properties: {
          item_name: {
            type: "string",
            description: "Название товара, услуги или комплекта"
          },
          quantity: {
            type: "integer",
            description: "Количество"
          },
          customer_name: {
            type: "string",
            description: "Имя клиента или компании"
          }
        },
        required: ["item_name"]
      }
    }
  }
];

const logisticsVehicles = [
  {
    id: "gazelle_1_5",
    name: "Газель 1,5 т",
    capacityTons: 1.5,
    rateRubPerKm: 55,
    rule: "только грузы до 1,5 т"
  },
  {
    id: "truck_5",
    name: "Грузовик 5 т",
    capacityTons: 5,
    rateRubPerKm: 70,
    rule: "грузы от 1,6 до 5 т"
  },
  {
    id: "truck_12",
    name: "Грузовик 10-12 т",
    capacityTons: 12,
    rateRubPerKm: 82,
    rule: "грузы от 5,1 до 12 т"
  },
  {
    id: "fura_20",
    name: "Фура 20 т",
    capacityTons: 20,
    rateRubPerKm: 95,
    rule: "грузы от 12,1 до 20 т или объемные паллетные перевозки"
  }
];

const routeDistancesKm = new Map(
  [
    ["Москва", "Санкт-Петербург", 715],
    ["Москва", "Екатеринбург", 1784],
    ["Москва", "Казань", 815],
    ["Москва", "Нижний Новгород", 421],
    ["Москва", "Краснодар", 1347],
    ["Москва", "Ростов-на-Дону", 1075],
    ["Москва", "Новосибирск", 3370],
    ["Москва", "Псков", 731],
    ["Екатеринбург", "Санкт-Петербург", 2302],
    ["Екатеринбург", "Казань", 954],
    ["Екатеринбург", "Новосибирск", 1601],
    ["Екатеринбург", "Пермь", 361],
    ["Екатеринбург", "Челябинск", 205],
    ["Екатеринбург", "Тюмень", 329],
    ["Екатеринбург", "Уфа", 543],
    ["Екатеринбург", "Самара", 969],
    ["Екатеринбург", "Нижний Новгород", 1325],
    ["Екатеринбург", "Краснодар", 2251],
    ["Екатеринбург", "Ростов-на-Дону", 2088],
    ["Екатеринбург", "Псков", 2497],
    ["Казань", "Санкт-Петербург", 1507],
    ["Казань", "Новосибирск", 2403],
    ["Новосибирск", "Красноярск", 791],
    ["Новосибирск", "Омск", 646],
    ["Пермь", "Москва", 1442],
    ["Пермь", "Санкт-Петербург", 2078],
    ["Челябинск", "Москва", 1771],
    ["Уфа", "Москва", 1352],
    ["Самара", "Москва", 1062]
  ].flatMap(([from, to, distance]) => [
    [`${normalizeCityName(from)}|${normalizeCityName(to)}`, distance],
    [`${normalizeCityName(to)}|${normalizeCityName(from)}`, distance]
  ])
);

function normalizeCityName(city) {
  return String(city || "")
    .trim()
    .replace(/ё/g, "е")
    .replace(/Ё/g, "Е")
    .replace(/\s+/g, " ")
    .toLowerCase();
}

function titleCity(city) {
  const normalized = String(city || "").trim().replace(/\s+/g, " ");
  return normalized || "город не указан";
}

function selectLogisticsVehicle(weightTons, vehicleHint = "") {
  const weight = Number(weightTons || 0);
  const hint = String(vehicleHint || "").toLowerCase();

  if (weight > 20) {
    return {
      selected: logisticsVehicles.at(-1),
      overflow: true,
      note: "Груз тяжелее 20 т: нужен отдельный расчет на несколько машин или спецтранспорт."
    };
  }

  const selected =
    logisticsVehicles.find((vehicle) => weight > 0 && weight <= vehicle.capacityTons) ||
    logisticsVehicles[0];

  const wantsFura = /фур|20\s*т|двадцат/i.test(hint);
  const alternative =
    wantsFura && weight > 0 && weight <= 12
      ? logisticsVehicles.find((vehicle) => vehicle.id === "fura_20")
      : null;

  return {
    selected,
    alternative,
    overflow: false,
    note:
      alternative && selected.id !== alternative.id
        ? "По массе хватает 10-12 т. Фура 20 т нужна, если груз объемный или паллетность требует больший кузов."
        : selected.rule
  };
}

function getRouteDistanceKm(originCity, destinationCity, providedDistanceKm) {
  const provided = Number(providedDistanceKm || 0);
  if (provided > 0) {
    return {
      distanceKm: Math.round(provided),
      source: "километраж назвал клиент",
      exactEnoughForDemo: true
    };
  }

  const origin = normalizeCityName(originCity);
  const destination = normalizeCityName(destinationCity);

  if (!origin || !destination) {
    return {
      distanceKm: null,
      source: "не хватает города отправки или назначения",
      exactEnoughForDemo: false
    };
  }

  const distanceKm = routeDistancesKm.get(`${origin}|${destination}`) || null;
  return {
    distanceKm,
    source: distanceKm ? "демо-таблица междугородних маршрутов" : "маршрута нет в демо-таблице",
    exactEnoughForDemo: Boolean(distanceKm)
  };
}

function formatRubles(value) {
  return `${Math.round(value).toLocaleString("ru-RU")} ₽`;
}

function calculateLogisticsQuote(args = {}) {
  const weight = Number(args.cargo_weight_tons || 0);
  const vehicleChoice = selectLogisticsVehicle(weight, args.vehicle_hint);
  const route = getRouteDistanceKm(args.origin_city, args.destination_city, args.distance_km);

  if (!weight || weight <= 0) {
    return {
      status: "needs_weight",
      nextQuestion: "Назовите вес груза в тоннах."
    };
  }

  if (!route.distanceKm) {
    return {
      status: "needs_route",
      originCity: titleCity(args.origin_city),
      destinationCity: titleCity(args.destination_city),
      cargoWeightTons: weight,
      selectedVehicle: vehicleChoice.selected.name,
      vehicleCapacityTons: vehicleChoice.selected.capacityTons,
      vehicleRule: vehicleChoice.note,
      nextQuestion:
        "Назовите город отправки и город назначения или точный километраж маршрута."
    };
  }

  const basePrice = route.distanceKm * vehicleChoice.selected.rateRubPerKm;
  const alternativePrice = vehicleChoice.alternative
    ? route.distanceKm * vehicleChoice.alternative.rateRubPerKm
    : null;

  return {
    status: "preliminary_logistics_quote",
    originCity: titleCity(args.origin_city),
    destinationCity: titleCity(args.destination_city),
    distanceKm: route.distanceKm,
    distanceSource: route.source,
    cargoWeightTons: weight,
    selectedVehicle: vehicleChoice.selected.name,
    vehicleCapacityTons: vehicleChoice.selected.capacityTons,
    rateRubPerKm: vehicleChoice.selected.rateRubPerKm,
    basePriceRub: Math.round(basePrice),
    basePriceFormatted: formatRubles(basePrice),
    alternativeVehicle: vehicleChoice.alternative?.name || null,
    alternativePriceRub: alternativePrice ? Math.round(alternativePrice) : null,
    alternativePriceFormatted: alternativePrice ? formatRubles(alternativePrice) : null,
    vehicleNote: vehicleChoice.note,
    finalization:
      "Это предварительный расчет. Финальная цена фиксируется после точных адресов, даты, типа кузова, способа оплаты, погрузки/выгрузки и платных участков.",
    nextStep: "подтвердить города, вес, тип кузова и дату рейса"
  };
}

function scoreProduct(product, input) {
  const haystack = `${product.name} ${product.fit} ${product.details}`.toLowerCase();
  return input
    .split(/\s+/)
    .filter((word) => word.length > 3 && haystack.includes(word))
    .length;
}

function pickProducts(salesCase, args) {
  const input = `${args.needs ?? ""} ${args.budget ?? ""} ${args.volume ?? ""} ${
    args.priority ?? ""
  }`.toLowerCase();

  const scored = salesCase.products
    .map((product) => ({ product, score: scoreProduct(product, input) }))
    .sort((a, b) => b.score - a.score);

  const best = scored.filter((item) => item.score > 0).map((item) => item.product);
  return best.length ? best.slice(0, 2) : salesCase.products.slice(0, 2);
}

export function runTool(name, args = {}, salesCase) {
  if (name === "lookup_case_catalog") {
    return JSON.stringify(
      {
        company: salesCase.companyName,
        offer: salesCase.offerName,
        summary: salesCase.summary,
        buyerRole: salesCase.buyerRole,
        proof: salesCase.proof,
        delivery: salesCase.delivery,
        products: salesCase.products,
        objectionHints: salesCase.objectionHints,
        note: "Не называй это клиенту как работу инструмента. Используй как факты активного кейса."
      },
      null,
      2
    );
  }

  if (name === "recommend_product_bundle") {
    const selected = pickProducts(salesCase, args);

    return JSON.stringify(
      {
        recommendedProducts: selected,
        reason:
          "Подбор основан на задаче клиента, объеме, срочности и критериях цены/надежности/совместимости.",
        nextStep: `предложить ${salesCase.nextStepName}`
      },
      null,
      2
    );
  }

  if (name === "calculate_logistics_quote") {
    return JSON.stringify(calculateLogisticsQuote(args), null, 2);
  }

  if (name === "create_quote") {
    return JSON.stringify(
      {
        status: "mock_quote_created",
        company: salesCase.companyName,
        items: args.items,
        customer: args.customer_name || "клиент",
        contact: args.contact || "контакт не указан",
        deliveryCity: args.delivery_city || "город не указан",
        quoteNumber: `TEST-${salesCase.id.toUpperCase()}-${Date.now().toString().slice(-5)}`,
        nextStep: "подтвердить состав и запросить реквизиты",
        note:
          "Это демонстрационный счет/резерв для тестовой панели. Ничего не отправлено клиенту автоматически."
      },
      null,
      2
    );
  }

  if (name === "create_payment_link") {
    const selected =
      salesCase.products.find((product) =>
        product.name.toLowerCase().includes(String(args.item_name || "").toLowerCase())
      ) || salesCase.products[0];

    return JSON.stringify(
      {
        status: "mock_payment_link_created",
        company: salesCase.companyName,
        item: selected.name,
        price: selected.price,
        quantity: args.quantity || 1,
        customer: args.customer_name || "клиент",
        link: `https://pay.example.local/${salesCase.id}/${encodeURIComponent(selected.name)}?mock=1`,
        note: "Это демонстрационная ссылка, реальное списание не выполняется."
      },
      null,
      2
    );
  }

  return JSON.stringify({ error: `Unknown tool: ${name}` });
}
