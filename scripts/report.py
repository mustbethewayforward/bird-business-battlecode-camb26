# Detailed per-champion report for match JSONs (platform summaries or suite stats files: replays/suite/*.json).
# usage: python scripts/report.py *-match-*.json   (file names must contain 'match-')
import json, sys, collections

def at(runs, r):
    """Value of a run-length timeline at round index r."""
    t = 0
    for run in runs:
        t += run['duration']
        if r < t:
            return run['value']
    return runs[-1]['value'] if runs else None

for f in sys.argv[1:]:
    d = json.load(open(f))
    m = d['match']
    ours = 'teamA' if d['roster']['champions'][0]['name'] == 'Ryth' and d['roster']['draft'][0]['team'] == 'teamA' else None
    names = {c['id']: '%s(%s)' % (c['name'], c['team'][-1]) for c in d['roster']['champions']}
    print('=' * 70)
    print('%s  map %dx%d  rounds %d  winner %s  gems %s' % (f.split('-match-')[1][:8], m['width'], m['height'],
          m['roundsCompleted'], m['outcome'], {t['team']: t['submittedGems'] for t in d['teams']}))
    for t in d['teamTimelines']:
        print('  %s submitted @100/200/300/400/500/600: %s' % (t['owner'], [at(t['runs'], r) for r in (100, 200, 300, 400, 500, 600)]))
    print('  %-12s %6s %6s %6s %5s %5s %7s %7s %7s %7s %6s' % ('champ', 'colGem', 'subGem', 'gold', 'kill', 'death', 'monDmg', 'monTkn', 'chmDmg', 'chmTkn', 'items'))
    for c in d['champions']:
        mt = c['metrics']
        g = lambda k: mt.get(k, '')
        print('  %-12s %6s %6s %6s %5s %5s %7s %7s %7s %7s %6d' % (names[c['id']], g('collectedGems'), g('submittedGems'), g('earnedGold'),
              g('kills'), g('deaths'), str(g('monsterDamageDone')).split('.')[0], str(g('monsterDamageTaken')).split('.')[0],
              str(g('championDamageDone')).split('.')[0], str(g('championDamageTaken')).split('.')[0], len(c['itemsBought'])))
    by = collections.defaultdict(list)
    for e in d['events']:
        for en in e['entries']:
            by[e['kind']].append((en['timestamp']['round'], names.get(e['owner'].get('id'), e['owner']), en))
    for r, who, en in sorted(by['death'], key=lambda x: x[0]):
        tgt = en.get('target', {})
        print('  DEATH r%-4d %-12s by %-14s ctx=%s amount=%s at (%s,%s)' % (r, who, tgt.get('name', '?') + '(' + str(tgt.get('team', ''))[-1:] + ')', en.get('context'), en.get('amount'), en.get('x'), en.get('y')))
    for r, who, en in sorted(by['gemLoss'], key=lambda x: x[0])[:12]:
        print('  GEMLOSS r%-4d %-12s amount=%s ctx=%s' % (r, who, en.get('amount'), en.get('context')))
    clears = collections.Counter()
    for r, who, en in by['campClear']:
        clears[(who[-2], en.get('context'), en.get('target', {}).get('name'))] += 1
    print('  camp clears (team, ctx, target):', dict(clears))
    first_sub = {}
    for r, who, en in sorted(by['gemSubmission'], key=lambda x: x[0]):
        first_sub.setdefault(who[-2], r)
    print('  first tribute round by team:', first_sub)
    print('  fuelExhausted:', len(by['fuelExhausted']), ' botFault:', len(by['botFault']))
