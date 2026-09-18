import json, glob, os, sys
out = sys.argv[1]
rows = []
for f in sorted(glob.glob(os.path.join(out, '*-*.json')), key=lambda p: (os.path.basename(p).split('-')[0], int(os.path.basename(p).split('-')[1].split('.')[0]))):
    kind, vus = os.path.basename(f).split('.')[0].split('-')
    d = json.load(open(f))['metrics']
    dur = d['http_req_duration']; reqs = d['http_reqs']; fail = d['http_req_failed']
    rows.append((kind, int(vus), reqs['count'], round(reqs['rate'], 1), round(dur['med']), round(dur['p(95)']), round(dur['p(99)']), round(dur['max']), round(100 * fail['value'], 2)))
print('| path | VUs | requests | req/s | p50 ms | p95 ms | p99 ms | max ms | errors % |')
print('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
for r in rows: print('| ' + ' | '.join(str(x) for x in r) + ' |')
