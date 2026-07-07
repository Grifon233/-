const assert = require('assert');
const http = require('http');
const {
    app,
    normalizeDomain,
    isSameDomainOrSubdomain,
    normalizeProxyPool,
    getProxyPoolStatus
} = require('../server');

function request(port, path, options = {}) {
    return new Promise((resolve, reject) => {
        const req = http.request({
            hostname: options.hostname || '127.0.0.1',
            port,
            path,
            method: options.method || 'GET',
            headers: {
                ...(options.headers || {})
            }
        }, (res) => {
            let body = '';
            res.setEncoding('utf8');
            res.on('data', chunk => {
                body += chunk;
            });
            res.on('end', () => {
                resolve({ status: res.statusCode, headers: res.headers, body });
            });
        });

        req.on('error', reject);

        if (options.body) {
            req.write(options.body);
        }

        req.end();
    });
}

async function main() {
    assert.strictEqual(normalizeDomain('https://www.Example.com/some/page?utm=1'), 'example.com');
    assert.strictEqual(normalizeDomain('https://id.freelance.ru/login'), 'id.freelance.ru');
    assert.strictEqual(normalizeDomain('id.freelance.ru/login'), 'id.freelance.ru');
    assert.strictEqual(normalizeDomain('apple.com/contacts'), 'apple.com');
    assert.strictEqual(normalizeDomain('bad host name'), '');
    assert.strictEqual(isSameDomainOrSubdomain('sales.example.com', 'example.com'), true);
    assert.strictEqual(isSameDomainOrSubdomain('fakeexample.com', 'example.com'), false);
    const normalizedProxyPool = normalizeProxyPool({
        enabled: true,
        proxies: [
            { host: 'socks5://user:secret@proxy-one.example:1080', limit: 100 },
            { host: 'proxy-two.example', port: 1080, limit: 100 },
            { host: 'proxy-three.example', port: 1080, limit: 100 }
        ]
    });
    assert.ifError(normalizedProxyPool.error);
    const proxyStatus = getProxyPoolStatus('203.0.113.15', normalizedProxyPool.proxyPool);
    assert.strictEqual(proxyStatus.totalLimit, 300);
    assert.strictEqual(proxyStatus.totalRemaining, 300);
    assert.match(proxyStatus.proxies[0].summary, /^socks5:\/\/proxy-one\.example:1080$/);

    const server = app.listen(0, '127.0.0.1');
    await new Promise(resolve => server.once('listening', resolve));
    const { port } = server.address();

    try {
        const home = await request(port, '/', {
            headers: { Host: 'tunnel-one.example' }
        });
        assert.strictEqual(home.status, 200);
        assert.match(home.body, /<script src="app\.js"><\/script>/);
        assert.match(home.body, /<link rel="stylesheet" href="style\.css">/);

        const appJs = await request(port, '/app.js', {
            headers: { Host: 'tunnel-two.example' }
        });
        assert.strictEqual(appJs.status, 200);
        assert.match(appJs.body, /normalizeDomainInput/);
        assert.match(appJs.body, /scrollToReportStartOnMobile/);

        const sourceLeak = await request(port, '/server.js', {
            headers: { Host: 'tunnel-one.example' }
        });
        assert.strictEqual(sourceLeak.status, 404);

        const limitStatus = await request(port, '/api/limit-status', {
            headers: {
                Host: 'tunnel-two.example',
                'X-Forwarded-For': '203.0.113.10, 10.0.0.2',
                'X-Forwarded-Proto': 'https'
            }
        });
        assert.strictEqual(limitStatus.status, 200);
        const limitJson = JSON.parse(limitStatus.body);
        assert.strictEqual(limitJson.total, 20);
        assert.strictEqual(limitJson.firstHalfUsed, 0);

        const invalidEnrich = await request(port, '/api/enrich', {
            method: 'POST',
            headers: {
                Host: 'tunnel-one.example',
                'Content-Type': 'application/json',
                'X-Forwarded-For': '203.0.113.10'
            },
            body: JSON.stringify({ domain: 'https://bad host/name' })
        });
        assert.strictEqual(invalidEnrich.status, 400);

        const bulkInvalid = await request(port, '/api/check-mx-bulk', {
            method: 'POST',
            headers: {
                Host: 'tunnel-two.example',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ domains: ['https://bad host/name'] })
        });
        assert.strictEqual(bulkInvalid.status, 200);
        const bulkJson = JSON.parse(bulkInvalid.body);
        assert.strictEqual(bulkJson.results[0].success, false);
        assert.strictEqual(bulkJson.results[0].provider, 'Некорректный домен');

        const invalidProxyPool = await request(port, '/api/proxy-test', {
            method: 'POST',
            headers: {
                Host: 'tunnel-two.example',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                proxyPool: {
                    enabled: true,
                    proxies: [
                        { host: '127.0.0.1', port: 1080, username: 'user', password: 'secret', limit: 100 }
                    ]
                }
            })
        });
        assert.strictEqual(invalidProxyPool.status, 400);
        assert.doesNotMatch(invalidProxyPool.body, /secret/);
    } finally {
        await new Promise(resolve => server.close(resolve));
    }
}

main()
    .then(() => {
        console.log('Smoke tests passed');
    })
    .catch((error) => {
        console.error(error);
        process.exitCode = 1;
    });
