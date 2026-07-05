import urllib.request, json
TOKEN = 'YOUR_BEARER_TOKEN'
def hit(method, ep, body=None):
    req = urllib.request.Request('http://127.0.0.1:8000' + ep, method=method,
        data=json.dumps(body).encode() if body else None,
        headers={'Content-Type': 'application/json','Authorization': f'Bearer {TOKEN}'})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode('utf-8','replace')

for ep in ['/api/v1/accounts?gender=male', '/api/v1/accounts?gender=unknown', '/api/v1/accounts?gender=']:
    s, b = hit('GET', ep)
    j = json.loads(b)
    g_list = [a.get('gender') for a in j]
    print(f'{s}  GET {ep}  count={len(j)}  genders={g_list}')
