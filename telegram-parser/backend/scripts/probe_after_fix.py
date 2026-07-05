import urllib.request, urllib.error, json
TOKEN = 'YOUR_BEARER_TOKEN'
def hit(method, ep, body=None):
    req = urllib.request.Request('http://127.0.0.1:8000' + ep, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={'Content-Type': 'application/json','Authorization': f'Bearer {TOKEN}'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode('utf-8','replace')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8','replace')

# 1) Gender filter
for ep in ['/api/v1/accounts?gender=male', '/api/v1/accounts?gender=unknown', '/api/v1/accounts?gender=']:
    s, b = hit('GET', ep)
    j = json.loads(b) if s == 200 else b
    if s == 200:
        print(f'{s}  GET  {ep}  count={len(j)}  genders={[a.get("gender") for a in j]}')
    else:
        print(f'{s}  GET  {ep}  {b[:200]}')

# 2) profile/refresh on real account
s, b = hit('POST', '/api/v1/accounts/4/profile/refresh', {})
print(f'{s}  POST /api/v1/accounts/4/profile/refresh  {b[:300]}')
