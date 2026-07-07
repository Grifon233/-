const express = require('express');
const dns = require('dns').promises;
const net = require('net');
const path = require('path');
const { domainToASCII } = require('url');
const http = require('http');
const https = require('https');
const crypto = require('crypto');
const cheerio = require('cheerio');
const ruCodes = require('ru-codes');
const { SocksClient } = require('socks');
const { SocksProxyAgent } = require('socks-proxy-agent');

const app = express();
const PORT = process.env.PORT || 3000;

app.set('trust proxy', true);
app.use(express.json());

app.use('/assets', express.static(path.join(__dirname, 'assets')));
app.use('/docs', express.static(path.join(__dirname, 'docs')));
app.get(['/', '/index.html'], (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});
app.get('/style.css', (req, res) => {
    res.sendFile(path.join(__dirname, 'style.css'));
});
app.get('/app.js', (req, res) => {
    res.sendFile(path.join(__dirname, 'app.js'));
});

function normalizeDomain(input) {
    let value = String(input || '').trim().toLowerCase();
    if (!value) return '';

    value = value.replace(/\\/g, '/');
    if (!/^https?:\/\//i.test(value)) {
        value = `https://${value}`;
    }

    try {
        const parsed = new URL(value);
        let hostname = parsed.hostname.replace(/^www\./, '');
        hostname = domainToASCII(hostname);

        if (hostname === 'localhost') return hostname;
        if (!/^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(hostname)) {
            return '';
        }

        return hostname;
    } catch (e) {
        return '';
    }
}

function isSameDomainOrSubdomain(hostname, rootDomain) {
    const normalizedHost = normalizeDomain(hostname);
    return normalizedHost === rootDomain || normalizedHost.endsWith(`.${rootDomain}`);
}

function normalizeClientIp(value) {
    const rawValue = Array.isArray(value) ? value[0] : value;
    const candidate = String(rawValue || '').split(',')[0].trim();
    if (!candidate) return '';

    const withoutMappedPrefix = candidate.replace(/^::ffff:/, '');
    if (net.isIP(withoutMappedPrefix)) return withoutMappedPrefix;
    if (net.isIP(candidate)) return candidate;
    return '';
}

function getClientIp(req) {
    return normalizeClientIp(req.headers['x-real-ip'])
        || normalizeClientIp(req.ip)
        || normalizeClientIp(req.socket.remoteAddress)
        || normalizeClientIp(req.headers['x-forwarded-for'])
        || 'unknown';
}

function normalizeProxyConfig(rawProxy, index = 0) {
    if (!rawProxy || rawProxy.enabled === false) {
        return { proxyConfig: null };
    }

    const type = String(rawProxy.type || 'socks5').trim().toLowerCase();
    if (type !== 'socks5') {
        return { error: 'Поддерживается только SOCKS5-прокси' };
    }

    let host = String(rawProxy.host || '').trim();
    let portValue = rawProxy.port;
    let usernameValue = rawProxy.username;
    let passwordValue = rawProxy.password;

    if (!host) {
        return { error: `Прокси #${index + 1}: укажите host SOCKS5-прокси` };
    }

    host = host.replace(/\\/g, '/');
    if (/^socks5:\/\//i.test(host) || /^https?:\/\//i.test(host)) {
        try {
            const parsed = new URL(host);
            if (!portValue && parsed.port) portValue = parsed.port;
            if (!usernameValue && parsed.username) usernameValue = decodeURIComponent(parsed.username);
            if (!passwordValue && parsed.password) passwordValue = decodeURIComponent(parsed.password);
            host = parsed.hostname;
        } catch (e) {
            return { error: `Прокси #${index + 1}: некорректный URL` };
        }
    }

    host = host.replace(/^\[|\]$/g, '').toLowerCase();
    if (host === 'localhost' || host === '127.0.0.1' || host === '::1') {
        return { error: `Прокси #${index + 1}: локальные адреса не разрешены` };
    }

    const port = Number.parseInt(portValue, 10);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
        return { error: `Прокси #${index + 1}: укажите корректный порт` };
    }

    const username = String(usernameValue || '').trim();
    const password = String(passwordValue || '');
    if (username.length > 128 || password.length > 256) {
        return { error: `Прокси #${index + 1}: логин или пароль слишком длинный` };
    }

    const limit = Number.parseInt(rawProxy.limit, 10);
    if (!Number.isInteger(limit) || limit < 1 || limit > 10000) {
        return { error: `Прокси #${index + 1}: лимит должен быть от 1 до 10000` };
    }

    return {
        proxyConfig: {
            id: rawProxy.id ? String(rawProxy.id).slice(0, 64) : `proxy-${index + 1}`,
            type,
            host,
            port,
            username,
            password,
            limit
        }
    };
}

function normalizeProxyPool(rawProxyPool) {
    const rawProxies = Array.isArray(rawProxyPool?.proxies)
        ? rawProxyPool.proxies
        : [];
    const enabled = rawProxyPool?.enabled === true;

    if (!enabled) {
        return { proxyPool: [] };
    }

    if (rawProxies.length === 0) {
        return { error: 'Добавьте хотя бы один SOCKS5-прокси или отключите режим прокси' };
    }

    if (rawProxies.length > 20) {
        return { error: 'За один запуск можно указать до 20 прокси' };
    }

    const proxyPool = [];
    const seen = new Set();

    for (let i = 0; i < rawProxies.length; i++) {
        const normalized = normalizeProxyConfig(rawProxies[i], i);
        if (normalized.error) return { error: normalized.error };
        if (!normalized.proxyConfig) continue;

        const dedupeKey = `${normalized.proxyConfig.host}:${normalized.proxyConfig.port}:${normalized.proxyConfig.username}`;
        if (seen.has(dedupeKey)) {
            return { error: `Прокси #${i + 1}: такая строка уже добавлена` };
        }
        seen.add(dedupeKey);
        proxyPool.push(normalized.proxyConfig);
    }

    if (proxyPool.length === 0) {
        return { error: 'Добавьте хотя бы один активный SOCKS5-прокси' };
    }

    return { proxyPool };
}

function getProxySummary(proxyConfig) {
    if (!proxyConfig) return null;
    return `${proxyConfig.type}://${proxyConfig.host}:${proxyConfig.port}`;
}

function getProxyFingerprint(proxyConfig) {
    return crypto
        .createHash('sha256')
        .update(`${proxyConfig.type}:${proxyConfig.host}:${proxyConfig.port}:${proxyConfig.username || ''}`)
        .digest('hex');
}

function buildSocksOptions(proxyConfig) {
    return {
        host: proxyConfig.host,
        port: proxyConfig.port,
        type: 5,
        userId: proxyConfig.username || undefined,
        password: proxyConfig.password || undefined
    };
}

function getSocksProxyUrl(proxyConfig) {
    const auth = proxyConfig.username
        ? `${encodeURIComponent(proxyConfig.username)}:${encodeURIComponent(proxyConfig.password || '')}@`
        : '';
    return `socks5://${auth}${proxyConfig.host}:${proxyConfig.port}`;
}

async function createTcpConnection(host, port, timeoutMs, proxyConfig = null) {
    if (proxyConfig) {
        const result = await SocksClient.createConnection({
            command: 'connect',
            proxy: buildSocksOptions(proxyConfig),
            destination: { host, port },
            timeout: timeoutMs
        });
        result.socket.setTimeout(timeoutMs);
        return result.socket;
    }

    return new Promise((resolve, reject) => {
        const socket = net.createConnection(port, host);
        const cleanup = () => {
            socket.removeListener('connect', onConnect);
            socket.removeListener('error', onError);
            socket.removeListener('timeout', onTimeout);
        };
        const onConnect = () => {
            cleanup();
            socket.setTimeout(timeoutMs);
            resolve(socket);
        };
        const onError = (error) => {
            cleanup();
            socket.destroy();
            reject(error);
        };
        const onTimeout = () => {
            cleanup();
            socket.destroy();
            reject(new Error('Таймаут подключения'));
        };

        socket.setTimeout(timeoutMs);
        socket.once('connect', onConnect);
        socket.once('error', onError);
        socket.once('timeout', onTimeout);
    });
}

function normalizeCharset(charset) {
    const value = String(charset || '')
        .trim()
        .replace(/^["']|["']$/g, '')
        .toLowerCase();

    if (!value) return '';
    if (['cp1251', 'windows1251', 'win-1251', 'win1251'].includes(value)) return 'windows-1251';
    if (['utf8', 'utf-8'].includes(value)) return 'utf-8';
    return value;
}

function getCharsetFromContentType(contentType) {
    const match = String(contentType || '').match(/charset\s*=\s*["']?([^;"'\s]+)/i);
    return normalizeCharset(match ? match[1] : '');
}

function getCharsetFromHtml(htmlPreview) {
    const html = String(htmlPreview || '');
    const charsetMatch = html.match(/<meta[^>]+charset\s*=\s*["']?\s*([^"'\s/>;]+)/i);
    if (charsetMatch) return normalizeCharset(charsetMatch[1]);

    const contentTypeMatch = html.match(/<meta[^>]+http-equiv\s*=\s*["']?content-type["']?[^>]+content\s*=\s*["'][^"']*charset\s*=\s*([^"'\s;]+)/i);
    return normalizeCharset(contentTypeMatch ? contentTypeMatch[1] : '');
}

function decodeHtmlBuffer(buffer, contentType = '') {
    const bytes = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer || []);
    if (bytes.length === 0) return '';

    const utf8Decoder = new TextDecoder('utf-8');
    const utf8Preview = utf8Decoder.decode(bytes.subarray(0, Math.min(bytes.length, 8192)));
    const charset = getCharsetFromContentType(contentType) || getCharsetFromHtml(utf8Preview) || 'utf-8';

    try {
        return new TextDecoder(charset).decode(bytes);
    } catch (e) {
        return utf8Decoder.decode(bytes);
    }
}

async function fetchText(url, options = {}) {
    const {
        headers = {},
        timeoutMs = 4000,
        proxyConfig = null,
        redirectsLeft = 3
    } = options;

    if (!proxyConfig) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, { headers, signal: controller.signal });
            clearTimeout(timeoutId);
            if (!response.ok) return null;
            const buffer = Buffer.from(await response.arrayBuffer());
            return decodeHtmlBuffer(buffer, response.headers.get('content-type') || '');
        } catch (e) {
            clearTimeout(timeoutId);
            return null;
        }
    }

    return new Promise((resolve) => {
        let settled = false;
        const parsed = new URL(url);
        const transport = parsed.protocol === 'https:' ? https : http;
        const agent = new SocksProxyAgent(getSocksProxyUrl(proxyConfig));
        const req = transport.request(parsed, {
            method: 'GET',
            headers,
            agent,
            timeout: timeoutMs
        }, (res) => {
            const statusCode = res.statusCode || 0;

            if ([301, 302, 303, 307, 308].includes(statusCode) && res.headers.location && redirectsLeft > 0) {
                settled = true;
                res.resume();
                const redirectUrl = new URL(res.headers.location, parsed).toString();
                fetchText(redirectUrl, { headers, timeoutMs, proxyConfig, redirectsLeft: redirectsLeft - 1 })
                    .then(resolve);
                return;
            }

            if (statusCode < 200 || statusCode >= 300) {
                settled = true;
                res.resume();
                resolve(null);
                return;
            }

            const chunks = [];
            let totalBytes = 0;
            res.on('data', chunk => {
                const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
                chunks.push(buffer);
                totalBytes += buffer.length;
                if (totalBytes > 2_000_000) {
                    settled = true;
                    req.destroy();
                    resolve(decodeHtmlBuffer(Buffer.concat(chunks), res.headers['content-type'] || ''));
                }
            });
            res.on('end', () => {
                if (!settled) {
                    settled = true;
                    resolve(decodeHtmlBuffer(Buffer.concat(chunks), res.headers['content-type'] || ''));
                }
            });
        });

        req.on('timeout', () => {
            if (!settled) {
                settled = true;
                req.destroy();
                resolve(null);
            }
        });
        req.on('error', () => {
            if (!settled) {
                settled = true;
                resolve(null);
            }
        });
        req.end();
    });
}

async function fetchTextWithUrl(url, options = {}) {
    const {
        headers = {},
        timeoutMs = 4000,
        proxyConfig = null,
        redirectsLeft = 3
    } = options;

    if (!proxyConfig) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
        try {
            const response = await fetch(url, { headers, signal: controller.signal });
            clearTimeout(timeoutId);
            if (!response.ok) return null;
            const buffer = Buffer.from(await response.arrayBuffer());
            const text = decodeHtmlBuffer(buffer, response.headers.get('content-type') || '');
            return { text, finalUrl: response.url || url };
        } catch (e) {
            clearTimeout(timeoutId);
            return null;
        }
    }

    return new Promise((resolve) => {
        let settled = false;
        const parsed = new URL(url);
        const transport = parsed.protocol === 'https:' ? https : http;
        const agent = new SocksProxyAgent(getSocksProxyUrl(proxyConfig));
        const req = transport.request(parsed, {
            method: 'GET',
            headers,
            agent,
            timeout: timeoutMs
        }, (res) => {
            const statusCode = res.statusCode || 0;

            if ([301, 302, 303, 307, 308].includes(statusCode) && res.headers.location && redirectsLeft > 0) {
                settled = true;
                res.resume();
                const redirectUrl = new URL(res.headers.location, parsed).toString();
                fetchTextWithUrl(redirectUrl, { headers, timeoutMs, proxyConfig, redirectsLeft: redirectsLeft - 1 })
                    .then(resolve);
                return;
            }

            if (statusCode < 200 || statusCode >= 300) {
                settled = true;
                res.resume();
                resolve(null);
                return;
            }

            const chunks = [];
            let totalBytes = 0;
            res.on('data', chunk => {
                const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
                chunks.push(buffer);
                totalBytes += buffer.length;
                if (totalBytes > 2_000_000) {
                    settled = true;
                    req.destroy();
                    resolve({
                        text: decodeHtmlBuffer(Buffer.concat(chunks), res.headers['content-type'] || ''),
                        finalUrl: url
                    });
                }
            });
            res.on('end', () => {
                if (!settled) {
                    settled = true;
                    resolve({
                        text: decodeHtmlBuffer(Buffer.concat(chunks), res.headers['content-type'] || ''),
                        finalUrl: url
                    });
                }
            });
        });

        req.on('timeout', () => {
            if (!settled) {
                settled = true;
                req.destroy();
                resolve(null);
            }
        });
        req.on('error', () => {
            if (!settled) {
                settled = true;
                resolve(null);
            }
        });
        req.end();
    });
}

// Cache for port 25 status: null = untested, true = blocked, false = open
let isPort25Blocked = null;

// Test if outgoing port 25 is blocked.
async function testPort25(proxyConfig = null) {
    if (!proxyConfig && isPort25Blocked !== null) {
        return isPort25Blocked;
    }

    try {
        const socket = await createTcpConnection('aspmx.l.google.com', 25, 2500, proxyConfig);
        socket.destroy();
        if (!proxyConfig) isPort25Blocked = false;
        return false;
    } catch (e) {
        if (!proxyConfig) isPort25Blocked = true;
        return true;
    }
}

// Transliterate Cyrillic text
function transliterate(text) {
    if (!text) return "";
    const rus = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя";
    const eng = ["a","b","v","g","d","e","jo","zh","z","i","y","k","l","m","n","o","p","r","s","t","u","f","h","ts","ch","sh","shch","","y","","e","yu","ya"];
    return text.toLowerCase().split('').map(char => {
        const index = rus.indexOf(char);
        return index !== -1 ? eng[index] : char;
    }).join('');
}

// Guess mail provider based on MX records
function getMailProvider(mxRecords) {
    if (!mxRecords || mxRecords.length === 0) return "Нет почты";
    const recordStr = mxRecords.map(r => r.exchange).join(" ").toLowerCase();
    if (recordStr.includes("google") || recordStr.includes("aspmx")) {
        return "Google Workspace";
    } else if (recordStr.includes("outlook") || recordStr.includes("protection.outlook")) {
        return "Microsoft 365";
    } else if (recordStr.includes("yandex") || recordStr.includes("mx.yandex")) {
        return "Yandex 360";
    } else if (recordStr.includes("mail.ru")) {
        return "VK WorkSpace";
    }
    return "Собственный сервер";
}

function normalizeSocialLink(url) {
    try {
        const parsed = new URL(String(url || '').trim());
        parsed.hash = '';
        const host = parsed.hostname.replace(/^www\./i, '').toLowerCase();
        const removableParams = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'fbclid', 'yclid'];
        removableParams.forEach(param => parsed.searchParams.delete(param));
        let path = parsed.pathname.replace(/\/+$/, '').toLowerCase();
        if (host === 'youtu.be') {
            path = `/channel/${path.replace(/^\/+/, '')}`;
        }
        return `${host}${path}${parsed.searchParams.toString() ? `?${parsed.searchParams.toString()}` : ''}`;
    } catch (e) {
        return String(url || '').trim().replace(/\/+$/, '').toLowerCase();
    }
}

function isUsefulSocialLink(platformName, url) {
    if (platformName !== 'YouTube') return true;
    try {
        const parsed = new URL(url);
        const path = parsed.pathname.toLowerCase();
        return path.startsWith('/@') ||
            path.startsWith('/channel/') ||
            path.startsWith('/c/') ||
            path.startsWith('/user/') ||
            (path === '/subscription_center' && parsed.searchParams.has('add_user')) ||
            parsed.hostname.replace(/^www\./i, '').toLowerCase() === 'youtu.be';
    } catch (e) {
        return false;
    }
}

function buildCatchAllProbeEmail(domain) {
    const suffix = crypto.randomBytes(5).toString('hex');
    return `lo-check-${Date.now()}-${suffix}@${domain}`;
}

function getEmailDomain(email) {
    const match = String(email || '').trim().toLowerCase().match(/^[^@\s]+@([^@\s]+)$/);
    return match ? normalizeDomain(match[1]) : '';
}

function addEmailTemplate(templates, seenEmails, source, name, email) {
    const normalizedEmail = String(email || '').trim().toLowerCase();
    if (!normalizedEmail || !normalizedEmail.includes('@') || seenEmails.has(normalizedEmail)) return;
    seenEmails.add(normalizedEmail);
    templates.push({ source, name, email: normalizedEmail });
}

function addPersonEmailTemplates(templates, seenEmails, first, last, domain) {
    const f = String(first || '').trim();
    const l = String(last || '').trim();
    const fi = f.charAt(0);
    const li = l.charAt(0);

    if (f && l) {
        [
            ["{first}.{last}", `${f}.${l}@${domain}`],
            ["{last}.{first}", `${l}.${f}@${domain}`],
            ["{first}{last}", `${f}${l}@${domain}`],
            ["{last}{first}", `${l}${f}@${domain}`],
            ["{first}_{last}", `${f}_${l}@${domain}`],
            ["{last}_{first}", `${l}_${f}@${domain}`],
            ["{first}-{last}", `${f}-${l}@${domain}`],
            ["{last}-{first}", `${l}-${f}@${domain}`],
            ["{first}", `${f}@${domain}`],
            ["{last}", `${l}@${domain}`],
            ["{first_letter}{last}", `${fi}${l}@${domain}`],
            ["{first}{last_letter}", `${f}${li}@${domain}`],
            ["{last}{first_letter}", `${l}${fi}@${domain}`],
            ["{last_letter}{first}", `${li}${f}@${domain}`],
            ["{first_letter}.{last}", `${fi}.${l}@${domain}`],
            ["{first}.{last_letter}", `${f}.${li}@${domain}`],
            ["{last}.{first_letter}", `${l}.${fi}@${domain}`],
            ["{last_letter}.{first}", `${li}.${f}@${domain}`],
            ["{first_letter}_{last}", `${fi}_${l}@${domain}`],
            ["{first}_{last_letter}", `${f}_${li}@${domain}`],
            ["{last}_{first_letter}", `${l}_${fi}@${domain}`],
            ["{last_letter}_{first}", `${li}_${f}@${domain}`],
            ["{first_letter}-{last}", `${fi}-${l}@${domain}`],
            ["{first}-{last_letter}", `${f}-${li}@${domain}`],
            ["{last}-{first_letter}", `${l}-${fi}@${domain}`],
            ["{last_letter}-{first}", `${li}-${f}@${domain}`],
            ["{first_letter}{last_letter}", `${fi}${li}@${domain}`],
            ["{first_letter}.{last_letter}", `${fi}.${li}@${domain}`]
        ].forEach(([name, email]) => addEmailTemplate(templates, seenEmails, 'person', name, email));
    } else if (f) {
        addEmailTemplate(templates, seenEmails, 'person', "{first}", `${f}@${domain}`);
    } else if (l) {
        addEmailTemplate(templates, seenEmails, 'person', "{last}", `${l}@${domain}`);
    }
}

// Fallback DNS-over-HTTPS resolution using Cloudflare API
async function resolveMxFallback(domain) {
    try {
        const response = await fetch(`https://cloudflare-dns.com/dns-query?name=${encodeURIComponent(domain)}&type=MX`, {
            headers: {
                "Accept": "application/dns-json"
            }
        });
        if (!response.ok) return [];
        const data = await response.json();
        if (data.Answer && data.Answer.length > 0) {
            return data.Answer
                .filter(ans => ans.type === 15 || String(ans.type) === '15')
                .map(ans => {
                    const parts = ans.data.split(' ');
                    const priority = parseInt(parts[0], 10);
                    let exchange = parts[1] || '';
                    if (exchange.endsWith('.')) exchange = exchange.slice(0, -1);
                    return { priority, exchange };
                })
                .filter(rec => !isNaN(rec.priority) && rec.exchange);
        }
    } catch (e) {
        console.error('DoH resolveMx error:', e);
    }
    return [];
}

// Wrapper to try standard MX query first, and DoH on failure
async function getMxRecords(domain) {
    try {
        const mxRecords = await dns.resolveMx(domain);
        if (mxRecords && mxRecords.length > 0) {
            return mxRecords;
        }
    } catch (e) {
        // Fall back to DoH
    }
    return await resolveMxFallback(domain);
}

// Format phone helper
function formatPhone(phone) {
    if (phone.startsWith('+7') && phone.length === 12) {
        return `+7 (${phone.substring(2, 5)}) ${phone.substring(5, 8)}-${phone.substring(8, 10)}-${phone.substring(10, 12)}`;
    }
    if (phone.startsWith('8') && phone.length === 11) {
        return `+7 (${phone.substring(1, 4)}) ${phone.substring(4, 7)}-${phone.substring(7, 9)}-${phone.substring(9, 11)}`;
    }
    return phone;
}

// Classify department based on surrounding text context
function detectDepartment(text) {
    if (!text) return 'Общий контакт / Справочная';
    const textLower = text.toLowerCase();
    
    if (textLower.includes('продаж') || textLower.includes('sales') || textLower.includes('сдел') || textLower.includes('клиент')) {
        return 'Отдел продаж';
    }
    if (textLower.includes('поддерж') || textLower.includes('support') || textLower.includes('help') || textLower.includes('сервис') || textLower.includes('техническ')) {
        return 'Служба поддержки';
    }
    if (textLower.includes('бухгалтер') || textLower.includes('finance') || textLower.includes('accounting') || textLower.includes('счет') || textLower.includes('оплат')) {
        return 'Бухгалтерия / Финансы';
    }
    if (textLower.includes('директор') || textLower.includes('ceo') || textLower.includes('руковод') || textLower.includes('генеральн') || textLower.includes('шеф')) {
        return 'Руководство / Администрация';
    }
    if (textLower.includes('приемн') || textLower.includes('секретар') || textLower.includes('office') || textLower.includes('офис')) {
        return 'Приемная';
    }
    if (textLower.includes('кадр') || textLower.includes('hr') || textLower.includes('подбор') || textLower.includes('ваканс') || textLower.includes('personnel') || textLower.includes('работа')) {
        return 'Отдел кадров (HR)';
    }
    if (textLower.includes('склад') || textLower.includes('доставк') || textLower.includes('логист') || textLower.includes('warehouse') || textLower.includes('транспорт')) {
        return 'Логистика / Склад';
    }
    if (textLower.includes('закуп') || textLower.includes('снабжен') || textLower.includes('procurement') || textLower.includes('тендер')) {
        return 'Отдел закупок';
    }
    if (textLower.includes('маркетинг') || textLower.includes('reklama') || textLower.includes('реклам') || textLower.includes('pr') || textLower.includes('пиар')) {
        return 'Отдел маркетинга и PR';
    }
    if (textLower.includes('партнер') || textLower.includes('cooperation') || textLower.includes('сотруднич') || textLower.includes('франшиз')) {
        return 'Отдел партнерства';
    }
    return 'Общий контакт / Справочная';
}

// Find Russian requisites (INN/OGRN) with math validation (ru-codes)
function findRequisites(text) {
    const found = {
        inn: []
    };
    if (!text) return found;

    // Find potential 10 and 12 digit numbers
    const innMatches = text.match(/\b\d{10}\b/g) || [];
    const inn12Matches = text.match(/\b\d{12}\b/g) || [];
    
    for (const match of innMatches) {
        try {
            if (ruCodes.isINN10(match) && !found.inn.includes(match)) {
                found.inn.push(match);
            }
        } catch (e) {}
    }
    for (const match of inn12Matches) {
        try {
            if (ruCodes.isINN12(match) && !found.inn.includes(match)) {
                found.inn.push(match);
            }
        } catch (e) {}
    }
    
    return found;
}

// Detect tech stack based on common HTML/Script signatures
function detectTechnologies(html) {
    const tech = [];
    const htmlLower = html.toLowerCase();
    
    if (htmlLower.includes('tildacdn.com') || htmlLower.includes('id="allrecords"') || htmlLower.includes('tilda-')) {
        tech.push('Tilda (Конструктор сайтов)');
    }
    if (htmlLower.includes('/wp-content/') || htmlLower.includes('/wp-includes/')) {
        tech.push('WordPress (CMS)');
    }
    if (htmlLower.includes('/bitrix/') || htmlLower.includes('bitrix24')) {
        tech.push('1С-Битрикс (CMS)');
    }
    if (htmlLower.includes('cdn.shopify.com')) {
        tech.push('Shopify (E-commerce)');
    }
    if (htmlLower.includes('mc.yandex.ru/metrika')) {
        tech.push('Яндекс Метрика (Аналитика)');
    }
    if (htmlLower.includes('google-analytics.com') || htmlLower.includes('googletagmanager.com/gtag')) {
        tech.push('Google Analytics (Аналитика)');
    }
    if (htmlLower.includes('code.jivo.ru') || htmlLower.includes('jivosite')) {
        tech.push('JivoChat (Онлайн-консультант)');
    }
    if (htmlLower.includes('b24-loader') || htmlLower.includes('b24-form')) {
        tech.push('Битрикс24 (CRM-виджет)');
    }
    if (htmlLower.includes('cloud.roistat.com')) {
        tech.push('Roistat (Сквозная аналитика)');
    }
    
    return tech;
}

// Scrape company phones, extensions, socials, requisites, and tech stack intelligently
async function scrapeSiteData(domain, proxyConfig = null) {
    const foundPhones = [];
    const foundSocials = [];
    const foundEmails = [];
    const foundRequisites = { inn: [] };
    const detectedTechs = new Set();
    let foundTitle = '';
    
    const processedPhones = new Set();
    const processedSocials = new Set();
    const processedEmails = new Set();

    async function fetchHtml(url) {
        return fetchTextWithUrl(url, {
            proxyConfig,
            timeoutMs: 4000,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'ru,en-US;q=0.7,en;q=0.3'
            }
        });
    }

    // 1. Fetch homepage first
    let homepageResult = await fetchHtml(`https://${domain}`);
    let homepageHtml = homepageResult ? homepageResult.text : null;
    let homepageUrl = homepageResult ? homepageResult.finalUrl : `https://${domain}`;
    if (!homepageHtml) {
        homepageResult = await fetchHtml(`http://${domain}`);
        homepageHtml = homepageResult ? homepageResult.text : null;
        homepageUrl = homepageResult ? homepageResult.finalUrl : `http://${domain}`;
    }

    const crawlQueue = [];
    const crawledUrls = [];

    if (homepageHtml) {
        crawlQueue.push({ url: homepageUrl, html: homepageHtml });
        crawledUrls.push(homepageUrl);

        // 2. Extract title of page
        const $ = cheerio.load(homepageHtml);
        const titleText = $('title').text().trim();
        if (titleText) foundTitle = titleText;

        // 3. Find other promising contact/about links (ignoring catalogs, blogs, shop items)
        const keepKeywords = [
            'contact', 'kontak', 'about', 'o-nas', 'o-kompa', 'o-studii', 'company',
            'requisite', 'rekvizit', 'inn', 'kpp',
            'supplier', 'postav', 'purchase', 'zakup', 'snabjen', 'procurement',
            'partner', 'sotrud', 'coop',
            'vacancy', 'vakans', 'hr', 'career', 'rabot',
            'legal', 'oferta', 'feedback', 'document', 'dogovor', 'map', 'rules'
        ];
        const excludeKeywords = [
            'blog', 'news', 'novos', 'stat', 'article', 'post', 'publ',
            'catalog', 'product', 'tovar', 'shop', 'store', 'category', 'cart', 'basket', 'checkout',
            'tag', 'archive', 'gallery', 'photo', 'video', 'portfolio', 'work', 'project', 'client'
        ];

        const candidateLinks = new Set();
        
        $('a[href]').each((_, elem) => {
            let href = $(elem).attr('href');
            if (!href) return;
            href = href.trim();

            if (href.startsWith('//')) {
                href = 'https:' + href;
            } else if (href.startsWith('/')) {
                href = `${homepageUrl.replace(/\/+$/, "")}${href}`;
            } else if (!href.startsWith('http')) {
                href = `${homepageUrl.replace(/\/+$/, "")}/${href}`;
            }

            try {
                const parsedUrl = new URL(href);
                // Same domain only
                if (!isSameDomainOrSubdomain(parsedUrl.hostname, domain)) return;
                
                const path = parsedUrl.pathname.toLowerCase();

                // Exclude common binary files
                if (/\.(jpg|jpeg|png|gif|pdf|zip|rar|tar|gz|doc|docx|xls|xlsx|mp4|mov|avi)$/i.test(path)) return;

                // Check exclusions (catalogs, blogs)
                const shouldExclude = excludeKeywords.some(kw => path.includes(kw));
                if (shouldExclude) return;

                // Check keep keywords
                const shouldKeep = keepKeywords.some(kw => path.includes(kw));
                if (shouldKeep) {
                    const cleanHref = parsedUrl.origin + parsedUrl.pathname.replace(/\/+$/, "");
                    candidateLinks.add(cleanHref);
                }
            } catch (err) {}
        });

        // Score priorities (Contacts -> Procurement -> HR -> Legal)
        function getUrlPriorityScore(urlPath) {
            const path = urlPath.toLowerCase();
            
            // High Priority (Score 100): Contacts, Requisites, About company
            if (path.includes('contact') || path.includes('kontak') || path.includes('requisite') || path.includes('rekvizit') || path.includes('inn')) {
                return 100;
            }
            if (path.includes('about') || path.includes('o-kompa') || path.includes('o-nas') || path.includes('company')) {
                return 90;
            }
            
            // Medium-High Priority (Score 70): Suppliers, procurement, partners
            if (path.includes('supplier') || path.includes('postav') || path.includes('purchase') || path.includes('zakup') || path.includes('snabjen') || path.includes('procurement')) {
                return 70;
            }
            if (path.includes('partner') || path.includes('sotrud') || path.includes('coop')) {
                return 60;
            }
            
            // Medium-Low Priority (Score 40): Vacancies, HR, careers
            if (path.includes('vacancy') || path.includes('vakans') || path.includes('hr') || path.includes('career') || path.includes('rabot')) {
                return 40;
            }
            
            // Low Priority (Score 20): Legal docs, offer, feedback, documents
            if (path.includes('legal') || path.includes('oferta') || path.includes('feedback') || path.includes('document') || path.includes('dogovor') || path.includes('map')) {
                return 20;
            }
            
            return 10; // Default low score
        }

        // Limit to 14 additional links (total 15 pages max), sorted by priority score
        const selectedLinks = Array.from(candidateLinks)
            .map(link => ({ url: link, score: getUrlPriorityScore(link) }))
            .sort((a, b) => b.score - a.score)
            .map(item => item.url)
            .slice(0, 14);
        
        // Fetch them in parallel
        const linkPromises = selectedLinks.map(async (url) => {
            const result = await fetchHtml(url);
            return { url: result ? result.finalUrl : url, html: result ? result.text : null };
        });

        const fetchedLinks = await Promise.all(linkPromises);
        fetchedLinks.forEach(item => {
            if (item.html) {
                crawlQueue.push(item);
                crawledUrls.push(item.url);
            }
        });
    } else {
        // Fallback to hardcoded contacts pages if home fetch completely failed
        const fallbackUrls = [
            `https://${domain}/contacts`,
            `https://${domain}/contact`,
            `http://${domain}/contacts`
        ];
        const fallbackPromises = fallbackUrls.map(async (url) => {
            const result = await fetchHtml(url);
            return { url: result ? result.finalUrl : url, html: result ? result.text : null };
        });
        const fallbackResults = await Promise.all(fallbackPromises);
        fallbackResults.forEach(item => {
            if (item.html) {
                crawlQueue.push(item);
                crawledUrls.push(item.url);
            }
        });
    }

    const socialPlatforms = [
        { name: 'Telegram', patterns: [/t\.me\//, /telegram\.me\//] },
        { name: 'WhatsApp', patterns: [/wa\.me\//, /api\.whatsapp\.com\//, /chat\.whatsapp\.com\//] },
        { name: 'Viber', patterns: [/viber\.click\//, /chats\.viber\.com\//, /viber:\/\/chat/] },
        { name: 'VK', patterns: [/vk\.com\//, /vkontakte\.ru\//] },
        { name: 'LinkedIn', patterns: [/linkedin\.com\//, /lnkd\.in\//] },
        { name: 'Instagram', patterns: [/instagram\.com\//] },
        { name: 'YouTube', patterns: [/youtube\.com\//, /youtu\.be\//] },
        { name: 'Facebook', patterns: [/facebook\.com\//, /fb\.me\//] },
        { name: 'Twitter', patterns: [/twitter\.com\//, /x\.com\//] }
    ];

    function addSocialLink(rawHref) {
        const href = String(rawHref || '').trim();
        if (!href) return;

        for (const platform of socialPlatforms) {
            const matches = platform.patterns.some(pattern => pattern.test(href));
            if (!matches) continue;

            let socialUrl = href;
            if (socialUrl.startsWith('//')) socialUrl = 'https:' + socialUrl;
            if (!socialUrl.startsWith('http') && !socialUrl.startsWith('viber://')) return;
            if (!isUsefulSocialLink(platform.name, socialUrl)) return;

            const socialKey = `${platform.name}:${normalizeSocialLink(socialUrl)}`;
            if (processedSocials.has(socialKey)) return;
            processedSocials.add(socialKey);

            foundSocials.push({
                platform: platform.name,
                url: socialUrl
            });
        }
    }

    for (let i = 0; i < crawlQueue.length; i++) {
        const { url, html } = crawlQueue[i];
        if (!html) continue;

        try {
            // Detect technologies on homepage
            if (i === 0) {
                const techs = detectTechnologies(html);
                techs.forEach(t => detectedTechs.add(t));
            }

            const $ = cheerio.load(html);

            // Social links often live in header/footer, so collect them before trimming DOM.
            $('a[href]').each((_, elem) => {
                addSocialLink($(elem).attr('href'));
            });

            // Remove non-content tags before text extraction to avoid false positive emails/requisites in code/styles
            $('script, style, iframe, noscript, svg').remove();

            // Scrape clean text content
            const textContent = $('body').text();
            
            // Extract INN
            const reqs = findRequisites(textContent);
            reqs.inn.forEach(inn => {
                if (!foundRequisites.inn.includes(inn)) foundRequisites.inn.push(inn);
            });

            // Extract emails from text
            const emailMatches = textContent.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/g) || [];
            emailMatches.forEach(email => {
                const cleanEmail = email.trim().toLowerCase();
                if (cleanEmail.endsWith('.png') || cleanEmail.endsWith('.jpg') || cleanEmail.endsWith('.gif') || cleanEmail.endsWith('.svg')) return;
                if (processedEmails.has(cleanEmail)) return;
                processedEmails.add(cleanEmail);
                foundEmails.push(cleanEmail);
            });

            // Extract emails from mailto: links
            $('a[href^="mailto:"]').each((_, elem) => {
                const href = $(elem).attr('href') || '';
                const email = href.replace('mailto:', '').split('?')[0].trim().toLowerCase();
                if (email && !processedEmails.has(email)) {
                    processedEmails.add(email);
                    foundEmails.push(email);
                }
            });

            // Clean headers, footers for exact main content phone parsing
            $('header, footer').remove();

            // Extract phones from tel: links
            $('a[href^="tel:"]').each((_, elem) => {
                const href = $(elem).attr('href') || '';
                const rawPhone = href.replace('tel:', '').trim();
                const cleanPhone = rawPhone.replace(/[^\d+]/g, '');
                if (cleanPhone.length < 5) return;

                let standardizedPhone = cleanPhone;
                if (standardizedPhone.startsWith('8') && standardizedPhone.length === 11) {
                    standardizedPhone = '+7' + standardizedPhone.substring(1);
                } else if (!standardizedPhone.startsWith('+') && standardizedPhone.startsWith('7') && standardizedPhone.length === 11) {
                    standardizedPhone = '+' + standardizedPhone;
                } else if (!standardizedPhone.startsWith('+') && standardizedPhone.length === 10) {
                    standardizedPhone = '+7' + standardizedPhone;
                }

                if (processedPhones.has(standardizedPhone)) return;
                processedPhones.add(standardizedPhone);

                const linkText = $(elem).text().trim();
                const parentText = $(elem).parent().text().trim();
                
                const extMatch = parentText.match(/(?:доб\.?|добавочный|ext\.?|extension)\s*(\d{2,5})/i) ||
                                 linkText.match(/(?:доб\.?|добавочный|ext\.?|extension)\s*(\d{2,5})/i);
                const extension = extMatch ? extMatch[1] : '';

                let department = detectDepartment(linkText);
                if (department === 'Общий контакт / Справочная') {
                    department = detectDepartment(parentText);
                }

                foundPhones.push({
                    phone: formatPhone(standardizedPhone),
                    extension,
                    department,
                    sourceUrl: url
                });
            });

            // Extract phones from text (regex fallback)
            const bodyText = $('body').text();
            const phoneRegex = /(?<!\d)(?:\+7|8)[\s\-\(]*\d{3}[\s\-\)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}\b/g;
            let match;
            
            while ((match = phoneRegex.exec(bodyText)) !== null) {
                const matchedText = match[0];
                const cleanPhone = matchedText.replace(/[^\d+]/g, '');
                
                let standardizedPhone = cleanPhone;
                if (standardizedPhone.startsWith('8') && standardizedPhone.length === 11) {
                    standardizedPhone = '+7' + standardizedPhone.substring(1);
                } else if (!standardizedPhone.startsWith('+') && standardizedPhone.startsWith('7') && standardizedPhone.length === 11) {
                    standardizedPhone = '+' + standardizedPhone;
                } else if (!standardizedPhone.startsWith('+') && standardizedPhone.length === 10) {
                    standardizedPhone = '+7' + standardizedPhone;
                }

                if (processedPhones.has(standardizedPhone)) continue;
                processedPhones.add(standardizedPhone);

                const start = Math.max(0, match.index - 90);
                const end = Math.min(bodyText.length, match.index + matchedText.length + 90);
                const context = bodyText.substring(start, end).replace(/\s+/g, ' ').trim();

                const extMatch = context.match(/(?:доб\.?|добавочный|ext\.?|extension)\s*(\d{2,5})/i);
                const extension = extMatch ? extMatch[1] : '';

                const department = detectDepartment(context);

                foundPhones.push({
                    phone: formatPhone(standardizedPhone),
                    extension,
                    department,
                    sourceUrl: url
                });
            }

        } catch (e) {
            console.error('Scraping parse error:', e);
        }
    }

    return {
        phones: foundPhones,
        socials: foundSocials,
        emails: foundEmails,
        requisites: foundRequisites,
        technologies: Array.from(detectedTechs),
        pageTitle: foundTitle
    };
}

// Perform real SMTP handshake validation
async function verifySmtp(email, mxRecords, proxyConfig = null) {
    if (!mxRecords || mxRecords.length === 0) {
        return { smtpStatus: 'invalid', risk: 'Высокий', reason: 'У домена отсутствуют MX-записи почты', log: [] };
    }

    const mailServer = mxRecords[0].exchange;
    const log = [];
    log.push(`SMTP CONNECT -> ${mailServer}:25`);
    if (proxyConfig) {
        log.push(`[PROXY] ${getProxySummary(proxyConfig)}`);
    }

    return new Promise((resolve) => {
        let step = 0;
        let response = '';
        let completed = false;
        let socket = null;

        const finish = (smtpStatus, risk, reason) => {
            if (completed) return;
            completed = true;
            try {
                if (socket) socket.write('QUIT\r\n');
            } catch(e) {}
            if (socket) socket.destroy();
            resolve({ smtpStatus, risk, reason, log });
        };

        const attachSocketHandlers = () => {
            socket.on('data', (data) => {
            response += data.toString();
            const lines = response.split('\r\n');
            const lastLine = lines[lines.length - 2] || '';

            if (/^\d{3} /.test(lastLine)) {
                const code = parseInt(lastLine.substring(0, 3));
                log.push(`S: ${lastLine}`);

                if (step === 0) {
                    if (code >= 400) {
                        finish('risky', 'Средний', `Сервер отклонил соединение: ${lastLine}`);
                        return;
                    }
                    socket.write('EHLO leadorchestra.com\r\n');
                    log.push('C: EHLO leadorchestra.com');
                    step = 1;
                    response = '';
                } else if (step === 1) {
                    if (code >= 400) {
                        socket.write('HELO leadorchestra.com\r\n');
                        log.push('C: HELO leadorchestra.com');
                        step = 1.5;
                    } else {
                        socket.write('MAIL FROM:<verify@leadorchestra.com>\r\n');
                        log.push('C: MAIL FROM:<verify@leadorchestra.com>');
                        step = 2;
                    }
                    response = '';
                } else if (step === 1.5) {
                    if (code >= 400) {
                        finish('risky', 'Средний', `Сервер отклонил приветствие: ${lastLine}`);
                        return;
                    }
                    socket.write('MAIL FROM:<verify@leadorchestra.com>\r\n');
                    log.push('C: MAIL FROM:<verify@leadorchestra.com>');
                    step = 2;
                    response = '';
                } else if (step === 2) {
                    if (code >= 400) {
                        finish('risky', 'Средний', `Сервер отклонил отправителя (MAIL FROM): ${lastLine}`);
                        return;
                    }
                    socket.write(`RCPT TO:<${email}>\r\n`);
                    log.push(`C: RCPT TO:<${email}>`);
                    step = 3;
                    response = '';
                } else if (step === 3) {
                    if (code === 250 || code === 251) {
                        finish('verified', 'Низкий', 'Адрес существует (Получен ответ 250 OK)');
                    } else if (code === 550 || code === 551 || code === 553 || code === 554) {
                        finish('invalid', 'Высокий', `Адрес не существует (Ответ сервера: ${code})`);
                    } else {
                        finish('risky', 'Средний', `Неопределенный ответ сервера: ${lastLine}`);
                    }
                    response = '';
                }
            }
            });

            socket.on('error', (err) => {
                log.push(`Ошибка сокета: ${err.message}`);
                let reason = `Ошибка соединения SMTP: ${err.message}`;
                let status = 'risky';
                
                if (err.code === 'ETIMEDOUT') {
                    reason = 'Таймаут подключения (порт 25 заблокирован)';
                } else if (err.code === 'ECONNREFUSED') {
                    reason = 'Соединение отклонено сервером';
                } else if (err.code === 'EACCES' || err.code === 'EPERM') {
                    reason = 'Блокировка доступа (порт 25 закрыт)';
                }
                finish(status, 'Средний', reason);
            });

            socket.on('timeout', () => {
                log.push('Превышено время ожидания ответа сокета');
                finish('risky', 'Средний', 'Таймаут сокета SMTP (порт 25 заблокирован)');
            });
        };

        createTcpConnection(mailServer, 25, 4000, proxyConfig)
            .then((connectedSocket) => {
                socket = connectedSocket;
                log.push(`[SMTP] Подключение установлено`);
                attachSocketHandlers();
            })
            .catch((err) => {
                log.push(`Ошибка подключения: ${err.message}`);
                finish('risky', 'Средний', proxyConfig
                    ? 'Не удалось подключиться к SMTP через указанный SOCKS5-прокси'
                    : 'Не удалось подключиться к SMTP');
            });
    });
}

// IP Daily Limit Tracking System (anti-abuse, anti-block)
const ipLimits = {};
const proxyLimits = {};

function getLimitData(ip) {
    const now = Date.now();
    
    // Clean up old entries from ipLimits to prevent memory leak
    for (const key in ipLimits) {
        if (now - ipLimits[key].dayStartedAt > 24 * 60 * 60 * 1000) {
            delete ipLimits[key];
        }
    }

    if (!ipLimits[ip]) {
        ipLimits[ip] = {
            firstHalfUsed: 0,
            secondHalfUsed: 0,
            firstHalfBlockedUntil: null,
            dayStartedAt: now
        };
    }
    
    const data = ipLimits[ip];
    
    // Reset limits if 24 hours have passed
    if (now - data.dayStartedAt > 24 * 60 * 60 * 1000) {
        data.firstHalfUsed = 0;
        data.secondHalfUsed = 0;
        data.firstHalfBlockedUntil = null;
        data.dayStartedAt = now;
    }
    
    // Clear cooldown if it expired
    if (data.firstHalfBlockedUntil && now >= data.firstHalfBlockedUntil) {
        data.firstHalfBlockedUntil = null;
    }
    
    return data;
}

function getPublicLimitStatus(limitData) {
    return {
        firstHalfUsed: limitData.firstHalfUsed,
        secondHalfUsed: limitData.secondHalfUsed,
        total: 20,
        blockedUntil: limitData.firstHalfBlockedUntil,
        dayStartedAt: limitData.dayStartedAt
    };
}

function getProxyUsageData(ip, proxyConfig) {
    const now = Date.now();
    const fingerprint = getProxyFingerprint(proxyConfig);
    const key = `${ip}:${fingerprint}`;

    // Clean up old entries from proxyLimits to prevent memory leak
    for (const k in proxyLimits) {
        if (now - proxyLimits[k].dayStartedAt > 24 * 60 * 60 * 1000) {
            delete proxyLimits[k];
        }
    }

    if (!proxyLimits[key]) {
        proxyLimits[key] = {
            used: 0,
            dayStartedAt: now
        };
    }

    const data = proxyLimits[key];
    if (now - data.dayStartedAt > 24 * 60 * 60 * 1000) {
        data.used = 0;
        data.dayStartedAt = now;
    }

    return data;
}

function getProxyPoolStatus(ip, proxyPool) {
    const proxies = proxyPool.map((proxyConfig, index) => {
        const usage = getProxyUsageData(ip, proxyConfig);
        return {
            id: proxyConfig.id,
            index,
            summary: getProxySummary(proxyConfig),
            limit: proxyConfig.limit,
            used: usage.used,
            remaining: Math.max(0, proxyConfig.limit - usage.used)
        };
    });

    return {
        enabled: proxyPool.length > 0,
        totalLimit: proxies.reduce((sum, item) => sum + item.limit, 0),
        totalUsed: proxies.reduce((sum, item) => sum + item.used, 0),
        totalRemaining: proxies.reduce((sum, item) => sum + item.remaining, 0),
        proxies
    };
}

function selectProxyForRequest(ip, proxyPool) {
    if (!proxyPool.length) return { proxyConfig: null, proxyStatus: null };

    for (const proxyConfig of proxyPool) {
        const usage = getProxyUsageData(ip, proxyConfig);
        if (usage.used < proxyConfig.limit) {
            usage.used++;
            return {
                proxyConfig,
                proxyStatus: getProxyPoolStatus(ip, proxyPool)
            };
        }
    }

    return {
        error: 'Лимит всех прокси в пуле исчерпан',
        proxyStatus: getProxyPoolStatus(ip, proxyPool)
    };
}

// Endpoint 0: Get Limit Status
app.get('/api/limit-status', (req, res) => {
    const ip = getClientIp(req);
    const limitData = getLimitData(ip);
    res.json({
        firstHalfUsed: limitData.firstHalfUsed,
        secondHalfUsed: limitData.secondHalfUsed,
        total: 20,
        blockedUntil: limitData.firstHalfBlockedUntil,
        dayStartedAt: limitData.dayStartedAt
    });
});

// Endpoint 1: Get Port 25 Status
app.get('/api/port-status', async (req, res) => {
    if (isPort25Blocked === null) {
        await testPort25();
    }
    res.json({ blocked: isPort25Blocked });
});

// Endpoint 1.5: Validate user SOCKS5 proxy pool without consuming proxy limits.
app.post('/api/proxy-test', async (req, res) => {
    const ip = getClientIp(req);
    const normalizedProxyPool = normalizeProxyPool(req.body.proxyPool || req.body.proxy);
    if (normalizedProxyPool.error) {
        return res.status(400).json({ error: normalizedProxyPool.error });
    }

    const proxyPool = normalizedProxyPool.proxyPool || [];
    if (!proxyPool.length) {
        return res.status(400).json({ error: 'Включите режим прокси и добавьте хотя бы один SOCKS5-прокси' });
    }

    const results = await Promise.all(proxyPool.map(async (proxyConfig) => {
        const [smtpBlocked, webHtml] = await Promise.all([
            testPort25(proxyConfig),
            fetchText('https://example.com', {
                proxyConfig,
                timeoutMs: 5000,
                headers: {
                    'User-Agent': 'LeadOrchestra Proxy Check',
                    'Accept': 'text/html,*/*;q=0.8'
                }
            })
        ]);

        return {
            id: proxyConfig.id,
            summary: getProxySummary(proxyConfig),
            limit: proxyConfig.limit,
            webFetchOk: Boolean(webHtml),
            smtpPort25Open: !smtpBlocked,
            ok: Boolean(webHtml) && !smtpBlocked
        };
    }));

    res.json({
        success: true,
        proxyStatus: getProxyPoolStatus(ip, proxyPool),
        results
    });
});

// Endpoint 2: Single Lead Enrichment & SMTP validation & Phone Scraping
app.post('/api/enrich', async (req, res) => {
    const { domain, firstName, lastName } = req.body;
    
    if (!domain) {
        return res.status(400).json({ error: 'Параметр domain является обязательным' });
    }

    const cleanDomain = normalizeDomain(domain);
    if (!cleanDomain) {
        return res.status(400).json({ error: 'Введите корректный домен или ссылку на страницу, например example.com или https://example.com/contacts' });
    }

    const ip = getClientIp(req);
    const normalizedProxyPool = normalizeProxyPool(req.body.proxyPool || req.body.proxy);
    if (normalizedProxyPool.error) {
        return res.status(400).json({ error: normalizedProxyPool.error });
    }

    const proxyPool = normalizedProxyPool.proxyPool || [];
    const proxySelection = selectProxyForRequest(ip, proxyPool);
    if (proxySelection.error) {
        return res.status(429).json({
            error: proxySelection.error,
            proxyStatus: proxySelection.proxyStatus,
            limitStatus: {
                ...getPublicLimitStatus(getLimitData(ip)),
                proxyMode: true
            }
        });
    }

    const selectedProxy = proxySelection.proxyConfig;
    const limitData = getLimitData(ip);
    const now = Date.now();

    // Check if in 1.5h cooldown
    if (!selectedProxy && limitData.firstHalfBlockedUntil && now < limitData.firstHalfBlockedUntil) {
        const timeLeftMs = limitData.firstHalfBlockedUntil - now;
        const timeLeftMin = Math.ceil(timeLeftMs / (60 * 1000));
        return res.status(429).json({
            error: `Достигнут лимит первой половины дня. В целях защиты от блокировок следующая проверка будет доступна через ${timeLeftMin} мин.`,
            limitStatus: {
                firstHalfUsed: limitData.firstHalfUsed,
                secondHalfUsed: limitData.secondHalfUsed,
                total: 20,
                blockedUntil: limitData.firstHalfBlockedUntil,
                isCooldown: true
            }
        });
    }

    // Check if daily limit fully exhausted
    if (!selectedProxy && limitData.firstHalfUsed + limitData.secondHalfUsed >= 20) {
        return res.status(429).json({
            error: 'Ваш суточный лимит (20 доменов) полностью исчерпан. Пожалуйста, возвращайтесь завтра.',
            limitStatus: {
                firstHalfUsed: limitData.firstHalfUsed,
                secondHalfUsed: limitData.secondHalfUsed,
                total: 20,
                blockedUntil: null,
                isExhausted: true
            }
        });
    }

    // Increment counters
    if (!selectedProxy && limitData.firstHalfUsed < 10) {
        limitData.firstHalfUsed++;
        if (limitData.firstHalfUsed === 10) {
            limitData.firstHalfBlockedUntil = now + 1.5 * 60 * 60 * 1000; // 1.5h cooldown
        }
    } else if (!selectedProxy) {
        limitData.secondHalfUsed++;
    }

    try {
        // Run website data scraping and MX records lookup in parallel
        const [mxResult, siteData] = await Promise.all([
            (async () => {
                let mxRecords = [];
                let mxStatus = 'Неактивен';
                let provider = 'Нет почтовых серверов';
                try {
                    mxRecords = await getMxRecords(cleanDomain);
                    if (mxRecords && mxRecords.length > 0) {
                        mxRecords.sort((a, b) => a.priority - b.priority);
                        mxStatus = 'Активен';
                        provider = getMailProvider(mxRecords);
                    }
                } catch (e) {}
                return { mxRecords, mxStatus, provider };
            })(),
            scrapeSiteData(cleanDomain, selectedProxy)
        ]);

        const { mxRecords, mxStatus, provider } = mxResult;

        // Check if port 25 is blocked
        const smtpPortBlocked = await testPort25(selectedProxy);
        const validationContextCache = new Map();
        validationContextCache.set(cleanDomain, {
            domain: cleanDomain,
            mxRecords,
            mxStatus,
            provider,
            catchAllProbe: null,
            catchAllDetected: false,
            catchAllProbeEmail: null
        });

        const getValidationContext = async (emailDomain) => {
            const domainForEmail = normalizeDomain(emailDomain || cleanDomain);
            if (!domainForEmail) return validationContextCache.get(cleanDomain);
            if (validationContextCache.has(domainForEmail)) {
                return validationContextCache.get(domainForEmail);
            }

            let domainMxRecords = [];
            let domainMxStatus = 'Неактивен';
            let domainProvider = 'Нет почтовых серверов';
            try {
                domainMxRecords = await getMxRecords(domainForEmail);
                if (domainMxRecords && domainMxRecords.length > 0) {
                    domainMxRecords.sort((a, b) => a.priority - b.priority);
                    domainMxStatus = 'Активен';
                    domainProvider = getMailProvider(domainMxRecords);
                }
            } catch (e) {}

            const context = {
                domain: domainForEmail,
                mxRecords: domainMxRecords,
                mxStatus: domainMxStatus,
                provider: domainProvider,
                catchAllProbe: null,
                catchAllDetected: false,
                catchAllProbeEmail: null
            };
            validationContextCache.set(domainForEmail, context);
            return context;
        };

        const runCatchAllProbe = async (context) => {
            if (!context || context.catchAllProbeEmail || context.mxRecords.length === 0 || smtpPortBlocked) {
                return context;
            }

            context.catchAllProbeEmail = buildCatchAllProbeEmail(context.domain);
            context.catchAllProbe = await verifySmtp(context.catchAllProbeEmail, context.mxRecords, selectedProxy);
            context.catchAllDetected = context.catchAllProbe.smtpStatus === 'verified';
            return context;
        };

        const primaryValidationContext = await runCatchAllProbe(validationContextCache.get(cleanDomain));
        const catchAllDetected = primaryValidationContext.catchAllDetected;
        const catchAllProbeEmail = primaryValidationContext.catchAllProbeEmail;

        // Generate Patterns
        const cleanFirst = transliterate(firstName).trim();
        const cleanLast = transliterate(lastName).trim();
        
        const emailTemplates = [];
        const seenTemplateEmails = new Set();
        addPersonEmailTemplates(emailTemplates, seenTemplateEmails, cleanFirst, cleanLast, cleanDomain);
        
        // Add generic corporate emails
        addEmailTemplate(emailTemplates, seenTemplateEmails, 'generic', "info@{domain}", `info@${cleanDomain}`);
        addEmailTemplate(emailTemplates, seenTemplateEmails, 'generic', "sales@{domain}", `sales@${cleanDomain}`);
        addEmailTemplate(emailTemplates, seenTemplateEmails, 'generic', "admin@{domain}", `admin@${cleanDomain}`);

        const sameDomainSiteEmails = (siteData.emails || []).filter(email => {
            const emailDomain = getEmailDomain(email);
            return emailDomain && isSameDomainOrSubdomain(emailDomain, cleanDomain);
        });
        const externalSiteEmails = (siteData.emails || []).filter(email => {
            const emailDomain = getEmailDomain(email);
            return emailDomain && !isSameDomainOrSubdomain(emailDomain, cleanDomain);
        });

        // Add actual scraped emails from the checked domain to validation templates.
        // External emails can appear in widgets, partners, old links, or shared footers;
        // validating them inside this company's report makes the result look duplicated.
        if (sameDomainSiteEmails.length > 0) {
            sameDomainSiteEmails.forEach(email => {
                addEmailTemplate(emailTemplates, seenTemplateEmails, 'site', "Найдено на сайте", email);
            });
        }

        const leads = [];
        const checkedVariants = [];
        const hiddenLeads = [];
        
        // Validate each template
        for (const template of emailTemplates) {
            const emailDomain = getEmailDomain(template.email) || cleanDomain;
            const validation = await runCatchAllProbe(await getValidationContext(emailDomain));
            let smtpStatus = 'risky';
            let risk = 'Средний';
            let reason = selectedProxy
                ? 'Пропущено: SMTP порт 25 недоступен через выбранный SOCKS5-прокси'
                : 'Пропущено: SMTP порт 25 заблокирован на этом сервере';
            let log = [
                `[СИСТЕМА] Проверка ${template.email}`,
                selectedProxy
                    ? `SOCKS5-прокси: ${getProxySummary(selectedProxy)}`
                    : 'Проверка идет через IP сервера',
                `Порт 25 недоступен. Точная проверка не выполнена.`
            ];
            
            if (validation.mxRecords.length === 0) {
                smtpStatus = 'invalid';
                risk = 'Высокий';
                reason = 'Нет почтовых серверов (MX-записи не найдены)';
                log = [`[СИСТЕМА] Домен ${validation.domain} не принимает почту`];
            } else if (validation.catchAllDetected) {
                smtpStatus = 'risky';
                risk = 'Недостоверно (Catch-All)';
                reason = 'Домен принимает случайные адреса, поэтому конкретные ящики на этом домене невозможно проверить точно.';
                log = [
                    `[СИСТЕМА] Проверка ${template.email}`,
                    `[CATCH-ALL] Контрольный случайный адрес: ${validation.catchAllProbeEmail}`,
                    `[CATCH-ALL] Сервер принял случайный адрес. Конкретные ящики этого домена не считаем достоверно подтвержденными.`,
                    ...(validation.catchAllProbe?.log || [])
                ];
            } else if (!smtpPortBlocked) {
                const check = await verifySmtp(template.email, validation.mxRecords, selectedProxy);
                smtpStatus = check.smtpStatus;
                risk = check.risk;
                reason = check.reason;
                log = check.log;
            } else {
                if (template.name === 'info@{domain}' || template.name === 'sales@{domain}') {
                    smtpStatus = 'risky';
                    risk = 'Средний (Catch-All)';
                    reason = selectedProxy
                        ? 'Домен активен, но порт 25 недоступен через выбранный SOCKS5-прокси. Ящик info/sales обычно существует.'
                        : 'Домен активен, но порт 25 заблокирован. Ящик info/sales обычно существует.';
                } else {
                    smtpStatus = 'risky';
                    risk = 'Средний';
                    reason = selectedProxy
                        ? 'Домен активен. SMTP проверка пропущена: порт 25 недоступен через выбранный SOCKS5-прокси'
                        : 'Домен активен. SMTP проверка пропущена: порт 25 заблокирован';
                }
            }

            const lead = {
                source: template.source,
                pattern: template.name,
                email: template.email,
                validationDomain: validation.domain,
                provider: validation.provider,
                mxStatus: validation.mxStatus,
                smtpStatus,
                risk,
                reason,
                log: log.join('\n')
            };

            if (template.source === 'person') {
                checkedVariants.push(lead);
            }

            const shouldDisplay = validation.mxStatus === 'Активен'
                && smtpStatus !== 'invalid'
                && (template.source !== 'person' || smtpStatus === 'verified');

            if (shouldDisplay) {
                leads.push(lead);
            } else {
                hiddenLeads.push(lead);
            }
        }

        res.json({
            success: true,
            domain: cleanDomain,
            pageTitle: siteData.pageTitle,
            provider,
            mxStatus,
            port25Blocked: smtpPortBlocked,
            proxyUsed: selectedProxy ? getProxySummary(selectedProxy) : null,
            proxyStatus: proxyPool.length ? getProxyPoolStatus(ip, proxyPool) : null,
            catchAllDetected,
            catchAllProbeEmail,
            leads,
            checkedVariants,
            hiddenEmailCount: hiddenLeads.length,
            hiddenInactiveEmailCount: hiddenLeads.filter(lead => lead.mxStatus !== 'Активен').length,
            hiddenInvalidEmailCount: hiddenLeads.filter(lead => lead.mxStatus === 'Активен' && lead.smtpStatus === 'invalid').length,
            phones: siteData.phones,
            socials: siteData.socials,
            scrapedEmails: sameDomainSiteEmails,
            externalEmails: externalSiteEmails,
            requisites: siteData.requisites,
            technologies: siteData.technologies,
            limitStatus: {
                firstHalfUsed: limitData.firstHalfUsed,
                secondHalfUsed: limitData.secondHalfUsed,
                total: 20,
                blockedUntil: limitData.firstHalfBlockedUntil,
                proxyMode: Boolean(selectedProxy)
            }
        });

    } catch (error) {
        console.error(error);
        res.status(500).json({ error: 'Внутренняя ошибка сервера: ' + error.message });
    }
});

// Endpoint 3: Bulk MX Check
app.post('/api/check-mx-bulk', async (req, res) => {
    const { domains } = req.body;
    if (!domains || !Array.isArray(domains)) {
        return res.status(400).json({ error: 'Параметр domains должен быть массивом строк' });
    }

    const results = [];

    for (let rawDomain of domains) {
        const domain = normalizeDomain(rawDomain);
        if (!domain) {
            results.push({
                domain: String(rawDomain || '').trim(),
                success: false,
                provider: 'Некорректный домен',
                records: []
            });
            continue;
        }

        try {
            const mxRecords = await getMxRecords(domain);
            if (mxRecords && mxRecords.length > 0) {
                mxRecords.sort((a, b) => a.priority - b.priority);
                results.push({
                    domain,
                    success: true,
                    provider: getMailProvider(mxRecords),
                    records: mxRecords.map(r => `${r.exchange} (${r.priority})`)
                });
            } else {
                results.push({
                    domain,
                    success: false,
                    provider: 'Нет почты',
                    records: []
                });
            }
        } catch (e) {
            results.push({
                domain,
                success: false,
                provider: 'Домен не найден / Нет MX',
                records: []
            });
        }
    }

    res.json({ success: true, results });
});

if (require.main === module) {
    const HOST = process.env.HOST || '127.0.0.1';
    app.listen(PORT, HOST, () => {
        console.log(`Сервер запущен на http://${HOST}:${PORT}`);
    });
}

module.exports = {
    app,
    normalizeDomain,
    isSameDomainOrSubdomain,
    normalizeProxyPool,
    getProxyPoolStatus,
    scrapeSiteData
};
