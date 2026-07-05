import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { toolDefinitions, runTool } from "./tools.js";

dotenv.config();

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

function readSecrets() {
  const secretsPath = path.join(rootDir, "secrets.json");
  if (!fs.existsSync(secretsPath)) {
    return {};
  }

  try {
    return JSON.parse(fs.readFileSync(secretsPath, "utf8"));
  } catch {
    return {};
  }
}

export function getDeepSeekConfig() {
  const secrets = readSecrets();
  const apiKey =
    process.env.DEEPSEEK_API_KEY ||
    secrets.deepseek_api_key ||
    secrets.DEEPSEEK_API_KEY ||
    "";

  return {
    apiKey,
    model:
      process.env.DEEPSEEK_MODEL ||
      secrets.deepseek_model ||
      secrets.DEEPSEEK_MODEL ||
      "deepseek-v4-flash",
    baseUrl:
      process.env.DEEPSEEK_BASE_URL ||
      secrets.deepseek_base_url ||
      "https://api.deepseek.com"
  };
}

function cleanAssistantText(text, options = {}) {
  let cleaned = String(text || "")
    .replaceAll("<END_OF_TURN>", "")
    .replaceAll("<END_OF_CALL>", "")
    .replace(/[\u{1f300}-\u{1faff}\u{2600}-\u{27bf}]/gu, "")
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/__(.*?)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .trim();

  cleaned = cleaned
    .replace(/\bОтправил\b/g, "Подготовил")
    .replace(/\bотправил\b/g, "подготовил")
    .replace(/\bОтправила\b/g, "Подготовила")
    .replace(/\bотправила\b/g, "подготовила")
    .replace(/\bОтправлю\b/g, "Подготовлю")
    .replace(/\bотправлю\b/g, "подготовлю")
    .replace(/\bОтправим\b/g, "Подготовим")
    .replace(/\bотправим\b/g, "подготовим");

  cleaned = normalizeEmailText(cleaned);
  cleaned = cleaned.replace(
    /\b(Подготовил|подготовил|Подготовила|подготовила|Подготовлю|подготовлю|Подготовим|подготовим)\s+на\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi,
    "$1 для $2"
  );
  cleaned = cleaned.replace(/\bна\s+почту\s+([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})/gi, "для $1");

  const internalPrefixes = [
    "Thought:",
    "Action:",
    "Action Input:",
    "Observation:",
    "Final Answer:"
  ];

  cleaned = cleaned
    .split("\n")
    .filter((line) => {
      const trimmed = line.trim();
      return !internalPrefixes.some((prefix) => trimmed.startsWith(prefix));
    })
    .join("\n")
    .trim();

  cleaned = cleaned.replace(/^(SalesGPT|SalesCopilot|Knotie-AI|AI-Sales-agent|Алексей|Марина|Илья|Эмилия|Emily)\s*:\s*/i, "");

  cleaned = enforceEarlyPriceGuard(cleaned, options.messages);
  cleaned = enforceDiscountGuard(cleaned, options);
  cleaned = compactLongResponse(cleaned);
  cleaned = normalizeEmailText(cleaned);

  if (!cleaned) {
    return "Давайте зафиксируем следующий шаг: сделаю расчет под вашу задачу?";
  }

  const last = cleaned.trim().slice(-1);
  if (!["?", "!", ":"].includes(last)) {
    const base = last === "." ? cleaned : `${cleaned}.`;
    cleaned = `${base} ${defaultClosingQuestion(options.salesCase)}`;
  }

  return cleaned;
}

function defaultClosingQuestion(salesCase) {
  if (salesCase?.id === "logistics") {
    return "Назовите город отправки, город назначения, вес и тип груза?";
  }

  if (salesCase?.id === "carpentry") {
    return "Что делаем и какие размеры берем в расчет?";
  }

  if (salesCase?.id === "household") {
    return "Какая площадь объекта и что закупаете чаще всего?";
  }

  return "Какие вводные берем для расчета?";
}

function normalizeEmailText(text) {
  return String(text).replace(
    /([A-Z0-9._%+-]+)@\s*([A-Z0-9.-]+)\.\s*([A-Z]{2,})/gi,
    "$1@$2.$3"
  );
}

function wordCount(text) {
  return (String(text).match(/\S+/g) || []).length;
}

function splitSentences(text) {
  const emailPlaceholder = "__EMAIL_DOT__";
  const normalized = String(text)
    .replace(/\s*\n+\s*/g, " ")
    .replace(/\s{2,}/g, " ")
    .trim()
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, (email) =>
      email.replace(/\./g, emailPlaceholder)
    );

  return (
    normalized
      .match(/[^.!?]+[.!?]+|[^.!?]+$/g)
      ?.map((sentence) => sentence.replaceAll(emailPlaceholder, ".").trim()) || []
  );
}

function isEarlyPriceRequest(messages = []) {
  const userMessages = messages.filter((message) => message.role === "user");
  const lastUserMessage = userMessages.at(-1)?.content || "";
  return (
    userMessages.length <= 1 &&
    /сколько|цена|стоимост|поч[её]м|прайс|сколько\s+стоит/i.test(lastUserMessage)
  );
}

function enforceEarlyPriceGuard(text, messages = []) {
  if (!isEarlyPriceRequest(messages)) {
    return text;
  }

  const filtered = splitSentences(text).filter(
    (sentence) => !/(₽|руб\.?|рублей|от\s+\d|стоимост[ьи]\s+\d|\d+\s*(тыс|k))/i.test(sentence)
  );

  if (filtered.length > 0) {
    return filtered.slice(0, 2).join(" ");
  }

  return "Сориентирую, но без задачи любая цена будет в воздух. Что нужно решить: объем, срок или качество?";
}

function isDiscountRequest(messages = []) {
  const lastUserMessage =
    messages
      .filter((message) => message.role === "user")
      .at(-1)?.content || "";

  return /скидк|скинь|скинуть|уступ|торг|подвин|дешевле\s+(сдела|будет|можно)|сделайте\s+дешевле/i.test(
    lastUserMessage
  );
}

function discountExchangeForCase(salesCase) {
  if (salesCase?.id === "logistics") {
    return "добавляете второй рейс, обратную загрузку или регулярное окно";
  }

  if (salesCase?.id === "carpentry") {
    return "добавляете полку, тумбу, панель, фурнитуру или фиксируете предоплату";
  }

  if (salesCase?.id === "household") {
    return "добавляете мешки, перчатки, мыло или расходники на месяц";
  }

  return "добавляете объем, предоплату или регулярность";
}

function hasStrongDiscountAlgorithm(text) {
  return (
    /максимальн.*скид|уже.*скид/i.test(text) &&
    /невыгодн/i.test(text) &&
    /добав|предоплат|регуляр|рейс|загруз|мешк|перчат|мыл|полк|тумб|фурнит/i.test(text)
  );
}

function enforceDiscountGuard(text, options = {}) {
  if (!isDiscountRequest(options.messages)) {
    return text;
  }

  if (hasStrongDiscountAlgorithm(text)) {
    return text;
  }

  const exchange = discountExchangeForCase(options.salesCase);
  return `Та цена, которую я назвал, уже с максимальной скидкой. Я бы не посмел предложить вам невыгодные условия. Просто резать цену — значит резать качество, срок или гарантию. Но если ${exchange}, я подвинусь. Фиксируем так?`;
}

function ensureToolConfirmations(content, toolLog = []) {
  const logisticsTool = [...toolLog]
    .reverse()
    .find((tool) => tool.name === "calculate_logistics_quote");
  const logisticsQuote = logisticsTool?.result;

  if (
    logisticsQuote?.status === "preliminary_logistics_quote" &&
    !content.includes(logisticsQuote.basePriceFormatted)
  ) {
    const alternative =
      logisticsQuote.alternativeVehicle && logisticsQuote.alternativePriceFormatted
        ? ` Если нужна именно ${logisticsQuote.alternativeVehicle}, будет ${logisticsQuote.alternativePriceFormatted}.`
        : "";

    return compactLongResponse(
      `По демо-калькулятору ${logisticsQuote.originCity} → ${logisticsQuote.destinationCity}: ${logisticsQuote.distanceKm} км. Для ${logisticsQuote.cargoWeightTons} т беру ${logisticsQuote.selectedVehicle}, не машину ниже тоннажа: ${logisticsQuote.rateRubPerKm} ₽/км, предварительно ${logisticsQuote.basePriceFormatted}.${alternative} Для фиксации нужны точные адреса, дата и кузов. Тент или реф?`
    );
  }

  if (logisticsQuote?.status === "needs_route") {
    return compactLongResponse(
      `По весу ${logisticsQuote.cargoWeightTons} т подходит ${logisticsQuote.selectedVehicle}, не машина ниже тоннажа. Для цены нужны город отправки и город назначения или точный километраж. Откуда и куда везем?`
    );
  }

  const quoteTool = [...toolLog].reverse().find((tool) => tool.name === "create_quote");
  const quoteNumber = quoteTool?.result?.quoteNumber;

  if (!quoteNumber || content.includes(quoteNumber)) {
    return content;
  }

  const lastQuestion = splitSentences(content)
    .reverse()
    .find((sentence) => sentence.endsWith("?"));

  if (lastQuestion) {
    return `Сформировал предварительный расчет №${quoteNumber}. ${lastQuestion}`;
  }

  return compactLongResponse(`Сформировал предварительный расчет №${quoteNumber}. ${content}`);
}

function compactLongResponse(text, maxWords = 55) {
  if (wordCount(text) <= maxWords) {
    return text;
  }

  const sentences = splitSentences(text);
  if (sentences.length === 0) {
    return text;
  }

  const lastQuestion = [...sentences].reverse().find((sentence) => sentence.endsWith("?"));
  const reserve = lastQuestion ? wordCount(lastQuestion) + 1 : 0;
  const budgetBeforeQuestion = Math.max(22, maxWords - reserve);
  const kept = [];

  for (const sentence of sentences) {
    if (lastQuestion && sentence === lastQuestion) {
      continue;
    }

    const next = [...kept, sentence].join(" ");
    if (wordCount(next) > budgetBeforeQuestion || kept.length >= 3) {
      break;
    }
    kept.push(sentence);
  }

  let compacted = kept.join(" ").trim();
  if (lastQuestion && !compacted.includes(lastQuestion)) {
    const withQuestion = `${compacted} ${lastQuestion}`.trim();
    if (wordCount(withQuestion) <= maxWords) {
      compacted = withQuestion;
    } else {
      compacted = `${sentences[0]} ${lastQuestion}`.trim();
    }
  }

  if (wordCount(compacted) > maxWords && lastQuestion) {
    compacted = lastQuestion;
  }

  return compacted || text;
}

function sanitizeMessages(messages) {
  if (!Array.isArray(messages)) {
    return [];
  }

  return messages
    .filter((message) => message && ["user", "assistant"].includes(message.role))
    .map((message) => ({
      role: message.role,
      content: String(message.content || "").slice(0, 8000)
    }))
    .slice(-24);
}

async function requestChatCompletion(body, config) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    const response = await fetch(`${config.baseUrl}/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${config.apiKey}`
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload?.error?.message || payload?.message || response.statusText;
      throw new Error(`DeepSeek API ${response.status}: ${message}`);
    }

    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

export async function createSalesReply({ systemPrompt, messages, salesCase }) {
  const config = getDeepSeekConfig();
  if (!config.apiKey) {
    throw new Error(
      "DEEPSEEK_API_KEY is not configured. Add it to .env, secrets.json, or the process environment."
    );
  }

  const sanitizedMessages = sanitizeMessages(messages);
  const apiMessages = [
    {
      role: "system",
      content: systemPrompt
    },
    ...sanitizedMessages
  ];

  const toolLog = [];

  for (let turn = 0; turn < 4; turn += 1) {
    const body = {
      model: config.model,
      messages: apiMessages,
      tools: toolDefinitions,
      tool_choice: "auto",
      thinking: { type: "disabled" },
      temperature: Number(process.env.DEEPSEEK_TEMPERATURE || 0.45),
      max_tokens: Number(process.env.DEEPSEEK_MAX_TOKENS || 520),
      stream: false
    };

    const completion = await requestChatCompletion(body, config);
    const assistantMessage = completion?.choices?.[0]?.message;

    if (!assistantMessage) {
      throw new Error("DeepSeek API returned an empty response.");
    }

    const toolCalls = assistantMessage.tool_calls || [];
    if (toolCalls.length === 0) {
      const content = cleanAssistantText(assistantMessage.content, {
        messages: sanitizedMessages,
        salesCase
      });
      return {
        content: ensureToolConfirmations(content, toolLog),
        usage: completion.usage || null,
        toolLog
      };
    }

    apiMessages.push({
      role: "assistant",
      content: assistantMessage.content || "",
      tool_calls: toolCalls
    });

    for (const toolCall of toolCalls) {
      const functionName = toolCall?.function?.name;
      const rawArguments = toolCall?.function?.arguments || "{}";
      let parsedArguments = {};

      try {
        parsedArguments = JSON.parse(rawArguments);
      } catch {
        parsedArguments = { query: rawArguments };
      }

      const result = runTool(functionName, parsedArguments, salesCase);
      toolLog.push({
        name: functionName,
        arguments: parsedArguments,
        result: JSON.parse(result)
      });

      apiMessages.push({
        role: "tool",
        tool_call_id: toolCall.id,
        content: result
      });
    }
  }

  return {
    content:
      "Я вижу следующий шаг: нужно зафиксировать расчет под вашу задачу. Какие вводные берем?",
    usage: null,
    toolLog
  };
}
