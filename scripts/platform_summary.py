# Summarise platform match JSONs (cambc matches summary <id> --json): result, gems, k/d, camp clears, idle champions, fuel exhaustion.
# usage: python scripts/platform_summary.py match-*.json
import json, sys, collections
OURS = ['Ryth', 'Varg', 'Marcella', 'Vendetta', 'Ren']  # our draft order: identifies our team
def our_team(d):
    seq = collections.defaultdict(list)
    for p in d['roster']['draft']:
        seq[p['team']].append(p['champion'])
    hits = [t for t, s in seq.items() if s == OURS[:len(s)]]
    return hits[0] if len(hits) == 1 else '?'
rows = []
for f in sys.argv[1:]:
    d = json.load(open(f)); m = d['match']
    us = our_team(d); them = 'teamB' if us == 'teamA' else 'teamA'
    gems = {t['team']: int(t['submittedGems']) for t in d['teams']}
    kd = collections.Counter()
    zero = 0
    for c in d['champions']:
        mt = c['metrics']
        kd[c['team'] + 'k'] += int(mt['kills']); kd[c['team'] + 'd'] += int(mt['deaths'])
        if c['team'] == us and int(mt['earnedGold']) == 0 and float(mt['monsterDamageDone']) == 0:
            zero += 1
    clears = collections.Counter()
    fuel = collections.Counter()
    for e in d['events']:
        if e['kind'] == 'campClear':
            for en in e['entries']: clears[e['owner'].get('team')] += 1
        if e['kind'] == 'fuelExhausted':
            fuel[e['owner'].get('team')] += len(e['entries'])
    n_ours = sum(1 for c in d['champions'] if c['team'] == us)
    print('%-8s %3dx%-3d r%-4d %-4s us=%4d them=%4d  k/d us %2d/%-3d them %2d/%-3d  clears %2d/%-2d  idle-champs %d/%d  fuelEx us %d' % (
        f.split('match-')[1][:8], m['width'], m['height'], m['roundsCompleted'],
        'WIN' if m['outcome'] == us else 'LOSS', gems.get(us, 0), gems.get(them, 0),
        kd[us + 'k'], kd[us + 'd'], kd[them + 'k'], kd[them + 'd'], clears[us], clears[them], zero, n_ours, fuel[us]))
