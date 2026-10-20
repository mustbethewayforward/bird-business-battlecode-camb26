# Experimental (not shipped): exp-demand (solo feasibility from own stats) + exp-assembly (squad election).
# Shared memory byte k = champion k's target group idx + 1 (0 = none).
# Bytes 6-7 = (group idx + 1, expiry round // 8) of the last failed squad assembly.
import cambc as bc
from cambc import game_map as gm

ALLY, ENEMY = bc.Team.ALLY, bc.Team.ENEMY

DEBUG = True
RETREAT_HP = 0.35
ENGAGE_HP = 0.6
BIG_BAG = 50
NEAR_ALTAR = 2
DETOUR_OK = 10
GOLD_WEIGHT = 0.05
SAFE_SHARE = 0.5
MULTI_CAMP_FACTOR = 0.65
SQUAD_WAIT = 20         # rounds with no new commitment or arrival before an assembly fails
WAIT_CAP = 60           # ...or total rounds waiting (a death's respawn time); never restarted
TEAM_COOLDOWN = 40      # rounds nobody newly picks a group whose assembly failed
BLACKLIST_ROUNDS = 60
CARRIER_GEMS = 15
CARRIER_HP = 0.5
MOVE_FUEL_RESERVE = 600_000  # BFS max ~0.5M (measured); 1.3M froze big maps
STUN_VALUE = 150        # a stun on an enemy champion is worth this much damage (untuned)

PICK_ORDER = [
    bc.ChampionDraft.RYTH, bc.ChampionDraft.VARG, bc.ChampionDraft.MARCELLA,
    bc.ChampionDraft.VENDETTA, bc.ChampionDraft.REN, bc.ChampionDraft.VESPER_VALE,
    bc.ChampionDraft.CASSI_AND_ISSAC, bc.ChampionDraft.TAVI, bc.ChampionDraft.STELLAR,
    bc.ChampionDraft.PRISM, bc.ChampionDraft.WILLOW,
]

I = bc.ItemType
BUILD_DEFAULT = [(I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
                 (I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),
                 (I.POWER_SHARD_OF_STRENGTH, I.POWER_EMBLEM_OF_STRENGTH)]
BUILD_TANKY_FIRST = [(I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),
                     (I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
                     (I.POWER_SHARD_OF_STRENGTH, I.POWER_EMBLEM_OF_STRENGTH)]
BUILD_RYTH = [(I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),
              (I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
              (I.POWER_SHARD_OF_HEALTH, I.POWER_EMBLEM_OF_HEALTH)]
BUILD_VESPER = [(I.TREASURE_SHARD_OF_STRENGTH, I.TREASURE_EMBLEM_OF_STRENGTH),
                (I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
                (I.POWER_SHARD_OF_STRENGTH, I.POWER_EMBLEM_OF_STRENGTH)]
CT = bc.ChampionType
BUILDS = {CT.RYTH: BUILD_RYTH, CT.VESPER_VALE: BUILD_VESPER,
          CT.STELLAR: BUILD_TANKY_FIRST, CT.PRISM: BUILD_TANKY_FIRST, CT.WILLOW: BUILD_TANKY_FIRST,
          CT.CASSI: BUILD_TANKY_FIRST, CT.TAVI: BUILD_TANKY_FIRST}
LOCK = bc.ConsumableType.ALTAR_LOCK
COOLDOWN = 8             # ability cooldown in turn ends
# kit_of() for our usual picks, measured once (each SDK flag read costs ~20k of first-turn fuel)
KITS = {CT.RYTH: (0, 1), CT.VARG: (None, 0), CT.MARCELLA: (1, 0), CT.VENDETTA: (None, 0), CT.REN: (0, None)}
MONSTER_EMBLEMS = (I.MONSTER_EMBLEM_OF_STRENGTH, I.MONSTER_EMBLEM_OF_HEALTH, I.MONSTER_EMBLEM_OF_FOCUS)
JUNGLE_EMBLEMS = (I.JUNGLE_EMBLEM_OF_STRENGTH, I.JUNGLE_EMBLEM_OF_HEALTH, I.JUNGLE_EMBLEM_OF_FOCUS)


def log(msg):
    print(msg)


def dbg(msg):  # free locally, skipped on platform
    if DEBUG:
        bc.debug_block(lambda: print(msg))


def dist(a, b):
    return a.chebyshev_distance(b)


class GroupInfo:
    def __init__(self, idx, group, avg_str, avg_hp, n_allies, my, team):
        camps = group.camps()
        self.idx = idx
        self.group = group
        self.tiles = group.spawn_tiles()
        tile_list = self.tiles.positions()
        self.center = tile_list[len(tile_list) // 2]
        self.gems = group.gem_value()
        self.gold = group.gold_value()
        stats = [c.base_stats() for c in camps]  # each SDK call ~20k fuel
        for c, s in zip(camps, stats):
            st.camp_str[c.kind()] = s.base_strength
        self.hp = sum(s.base_health for s in stats)
        self.dps = sum(s.base_strength for s in stats)
        factor = 1.0 if len(camps) == 1 else MULTI_CAMP_FACTOR
        self.need0 = squad_size(self.hp, self.dps * factor, avg_str, avg_hp, n_allies)
        self.camps = sorted(((s.base_health, s.base_strength) for s in stats), key=lambda c: -c[1] / c[0])
        if solo_ok(self.camps, *my):
            self.need = 1
        elif any(solo_ok(self.camps, *a) for a in team):
            self.need = 99  # solo work for a teammate: no squad request for it
        else:
            self.need = max(2, self.need0)
        self.in_bush = not (self.tiles & st.bushes).is_empty()
        monolith = any(s.base_health >= 10000 for s in stats)  # 20k HP
        self.skip = monolith or (self.gems == 0 and self.gold == 0)
        self.reach = None
        self.respawn_at = 0
        self.reward = False
        self.capture_since = None


def kit_of(champ):
    """(slot of a SPELL attack() casts at camps, slot of an attack RESET), None if absent.
    A spell takes the turn's one cast (its damage is not credited); a reset gives a second attack."""
    spell = reset = None
    for ab in champ.abilities():
        if ab.is_attack_reset():
            reset = ab.slot()
        elif (ab.is_damage() or ab.is_aoe_damage() or ab.is_cc()) and (ab.can_target_camps() or ab.can_target_ground()):
            spell = ab.slot()
    return spell, reset


def solo_damage(camps, atk, kit, taken=1.0, cooldowns=(0, 0), limit=1e9):
    """Damage to a lone champion (camps hit the nearest champion: all of it lands on me), killing
    (health, strength) camps in order. Each turn: one attack of atk, then one cast: a ready spell
    first, else a ready reset, whose extra attack only hits a camp still alive; 8-turn cooldowns.
    Stops once past limit."""
    spell_cd = cooldowns[0] if kit[0] is not None else 99999
    reset_cd = cooldowns[1] if kit[1] is not None else 99999
    alive = sum(s for _, s in camps)
    dmg = 0.0
    for hp, strength in camps:
        while hp > 0:
            dmg += alive * taken  # every live camp hits me once a round
            if dmg > limit:
                return dmg
            hp -= atk
            if spell_cd == 0:
                spell_cd = COOLDOWN
            elif reset_cd == 0:
                reset_cd = COOLDOWN
                if hp > 0:
                    hp -= atk
            spell_cd, reset_cd = max(0, spell_cd - 1), max(0, reset_cd - 1)
        alive -= strength
    return dmg


def solo_ok(camps, atk, max_hp, kit, taken=1.0):
    return solo_damage(camps, atk, kit, taken, limit=SAFE_SHARE * max_hp) < SAFE_SHARE * max_hp


def refresh_solo(me):
    """Stats only change when we buy: groups I can now solo become solo work."""
    counts = me.item_count()
    bonus = 1.1 if any(counts[int(e)] for e in MONSTER_EMBLEMS) else 1.0
    st.taken = 0.7 if any(counts[int(e)] for e in JUNGLE_EMBLEMS) else 1.0
    st.atk = me.strength() * bonus
    max_hp = me.max_health()
    changed = []
    for info in st.groups:
        if info.need != 1 and solo_ok(info.camps, st.atk, max_hp, st.kit, st.taken):
            changed.append((info.idx, info.need))
            info.need = 1
    if changed:
        dbg("SOLO s%d atk=%.0f hp=%.0f taken=%.1f now solo (group, was): %s" % (st.slot, st.atk, max_hp, st.taken, changed))


def squad_size(hp, dps, avg_str, avg_hp, n_allies):
    for n in range(1, n_allies + 1):
        rounds = hp / (n * avg_str)
        if dps * rounds / n < SAFE_SHARE * avg_hp:
            return n
    return 99


class State:
    ready = False
    walkable = None
    spawn = None
    spawn_list = []
    altars = []
    bushes = None
    max_dist = 10000
    stuck = 0
    stuck_key = None
    stuck_best = 0
    last_hp = 0.0
    hurt = False
    handles = []
    slot = 0
    groups = []
    target = None
    mem = bytearray(8)
    blacklist = {}
    last_slot_value = -1
    wait = None             # [group idx, since, best (committed, here), round it last rose, last round waited]
    alive_slots = []
    visible_allies = {}
    ally_pos = {}
    enemies = []
    static_blocked = None
    was_alive = True
    rng = 1
    atk = 1.0
    taken = 1.0
    kit = (None, None)
    solo_fight = None       # debug: (group idx, round, hp, predicted) of my current solo engagement
    varg = False
    camp_str = {}
    branch = ""
    reach_budget = 0
    fuelskip = 0
    tel = None


st = State()


def init():
    me = bc.me()
    st.static_blocked = gm.walls() | gm.holes() | gm.altars() | gm.spawn_region(ENEMY)
    st.walkable = ~st.static_blocked
    st.spawn = gm.spawn_region(ALLY)
    st.spawn_list = st.spawn.positions()
    st.altars = gm.altars().positions()
    st.bushes = gm.bushes()
    st.max_dist = gm.width() * gm.height()  # default BFS cap too short on big maps
    allies = bc.champions(ALLY)
    st.handles = sorted(int(c) for c in allies)
    st.slot = st.handles.index(int(me))
    st.rng = me.attack_range()
    st.varg = me.champion_name() == CT.VARG
    stats = [c.base_stats() for c in allies]
    avg_str = sum(s.base_strength for s in stats) / len(stats)
    avg_hp = sum(s.base_health for s in stats) / len(stats)
    st.kit = kit_of(me)
    team = [(s.base_strength, s.base_health, KITS.get(c.champion_name()) or kit_of(c)) for c, s in zip(allies, stats)]
    mine = me.base_stats()
    mine = (mine.base_strength, mine.base_health, st.kit)
    st.groups = []
    for i, g in enumerate(gm.camp_groups()):
        info = GroupInfo(i, g, avg_str, avg_hp, len(allies), mine, team)
        st.groups.append(info)
    st.atk = mine[0]
    st.ready = True
    dbg("init slot=%d %s groups=%s" % (st.slot, me.champion_name(),
        [(g.idx, g.gems, g.need0, g.need) for g in st.groups if not g.skip]))


def read_memory():
    buf = bytearray(8)
    bc.shared_memory.read(0, buf)
    st.mem = buf


def commit(info):
    st.target = info
    value = 0 if info is None else info.idx + 1
    if value != st.last_slot_value:
        bc.shared_memory.write(st.slot, bytes([value]))
        st.last_slot_value = value


def refresh_allies():
    alive = {int(c) for c in bc.champions(ALLY) if c.is_alive()}
    st.alive_slots = [k for k, h in enumerate(st.handles) if h in alive]
    st.visible_allies = {int(c): c for c in bc.vision.champions(ALLY)}
    st.ally_pos = {h: c.position() for h, c in st.visible_allies.items()}
    st.enemies = []
    for e in bc.vision.champions(ENEMY):
        try:
            st.enemies.append((e, e.position()))
        except bc.Error:
            pass


def committed_others(info):
    want = info.idx + 1
    return [k for k in st.alive_slots if k != st.slot and k < 8 and st.mem[k] == want]


def alive_allies():
    return len(st.alive_slots)


def elect():
    """Squad requests compete for the same champions. Using shared memory only, so every
    champion agrees: most committed first, then lowest group idx, while champions remain.
    Returns ({viable group idx: committed}, champions left over)."""
    counts = {}
    for k in st.alive_slots:
        v = st.last_slot_value if k == st.slot else st.mem[k]
        if 0 < v <= len(st.groups) and st.groups[v - 1].need > 1:
            counts[v - 1] = counts.get(v - 1, 0) + 1
    viable, left = {}, alive_allies()
    for idx in sorted(counts, key=lambda i: (-counts[i], i)):
        if st.groups[idx].need <= left:
            viable[idx] = counts[idx]
            left -= st.groups[idx].need
    return viable, left


def reassign(info, rnd):
    """Keep my squad request only if elected; else join the top elected squad still short
    of champions, else go back to solo work. A reassignment is not a failed assembly."""
    viable, _ = elect()
    if info.idx in viable:
        return False
    short = [i for i in viable if viable[i] < st.groups[i].need]
    if short:
        dbg("ASM r%d s%d join g%d -> g%d" % (rnd, st.slot, info.idx, short[0]))
        commit(st.groups[short[0]])
    else:
        dbg("ASM r%d s%d solo g%d" % (rnd, st.slot, info.idx))
        st.blacklist[info.idx] = rnd + SQUAD_WAIT
        commit(None)
    return True


def assembly_failed(info, here, rnd):
    committed = 1 + len(committed_others(info))
    w = st.wait
    if w is None or w[0] != info.idx or w[4] < rnd - 1:  # any turn not waiting ends the wait
        w = st.wait = [info.idx, rnd, (committed, here), rnd, rnd]
        dbg("ASM r%d s%d wait g%d need=%d committed=%d here=%d" % (rnd, st.slot, info.idx, info.need, committed, here))
    w[4] = rnd
    if committed > w[2][0] or here > w[2][1]:  # support is getting closer
        w[2], w[3] = (max(committed, w[2][0]), max(here, w[2][1])), rnd
    if rnd - w[3] > SQUAD_WAIT:
        why = "no progress, committed %d here %d of %d" % (committed, here, info.need)
    elif rnd - w[1] > WAIT_CAP:
        why = "cap, committed %d here %d of %d" % (committed, here, info.need)
    else:
        return False
    dbg("ASM r%d s%d fail g%d after %d: %s" % (rnd, st.slot, info.idx, rnd - w[1], why))
    return True


def observe(rnd):
    vis = bc.vision.visible_tiles()  # vision.camp_groups() rebuilds every group: ~1.1M fuel
    for info in st.groups:
        if (info.tiles & vis).is_empty():
            continue
        try:
            s = info.group.state()
        except bc.Error:
            continue
        if isinstance(s, gm.CampGroupRespawning):
            info.respawn_at = rnd + max(1, s.timer)
            info.reward = False
        elif isinstance(s, gm.CampGroupRewardAvailable):
            info.respawn_at = 0
            info.reward = True
        else:
            info.respawn_at = 0
            info.reward = False


def live_camps(info):
    out = []
    for c in info.group.camps():
        try:
            if c.is_visible() and c.is_alive():
                out.append(c)
        except bc.Error:
            pass
    return out


def nearest_altar(pos):
    best, best_d = None, 10 ** 9
    for a in st.altars:
        d = dist(pos, a)
        if d < best_d:
            best, best_d = a, d
    return best, best_d


def enemies_visible():
    return [e for e, _ in st.enemies]


def count_near(points, center, radius):
    return sum(1 for p in points if dist(p, center) <= radius)


def ring(center, rng, exclude=None):
    bb = bc.Bitboard()
    bb.draw_chebyshev(center, rng)
    bb &= st.walkable
    bb &= ~(bc.vision.champion_tiles() | bc.vision.camp_tiles())
    if exclude is not None:
        bb &= ~exclude
    return bb


def walk_to(me, goals):
    if goals is None or not me.can_move():
        return False
    if bc.fuel_remaining() < MOVE_FUEL_RESERVE:  # no-path BFS floods the map
        st.fuelskip += 1
        return False
    origin = me.position()
    if goals.is_set(origin):
        return False
    blocked = st.static_blocked | bc.vision.champion_tiles() | bc.vision.camp_tiles()
    blocked.set(origin, False)
    roots = goals & ~blocked
    if roots.is_empty():
        return False
    dest = bc.Bitboard()
    dest.set(origin)
    field = bc.DistanceField()
    field.compute_to(blocked, roots, dest, bc.Bitboard(), st.max_dist)
    here = field.get(origin)
    steps = [p for p in blocked.reachable_tiles(origin, 1).positions() if p != origin]
    steps.sort(key=field.get)
    for p in steps[:3]:
        if field.get(p) >= here:
            break
        try:
            if me.move_absolute(p):  # False = hidden enemy, try next step
                return True
        except bc.Error as e:
            dbg("move error %r" % (e,))
    return False


def go_home(me):
    walk_to(me, st.spawn)


def shop(me):
    name = me.champion_name()
    on_spawn = (not me.is_alive()) or st.spawn.is_set(me.position())
    if not on_spawn and name != CT.TAVI:
        return
    gold = me.gold_count()
    counts = me.item_count()
    first_emblem_done = False
    for shard, emblem in BUILDS.get(name, BUILD_DEFAULT):
        if counts[int(emblem)] >= 1 and emblem != I.POWER_EMBLEM_OF_STRENGTH \
                and emblem != I.POWER_EMBLEM_OF_HEALTH:
            first_emblem_done = True
            continue
        n = min(gold // shard.cost(), 5 - counts[int(shard)])
        if n > 0 and me.can_buy(shard, n):
            me.buy(shard, n)
            gold -= n * shard.cost()
            dbg("bought %d x %s" % (n, shard.name))
            refresh_solo(me)
        break
    if on_spawn and first_emblem_done and gold >= LOCK.cost():
        if me.consumables()[int(LOCK)].count() == 0 and me.can_buy(LOCK):
            me.buy(LOCK)


def threats_near(me, radius=4):
    pos = me.position()
    for c in bc.vision.camps():
        try:
            if c.is_awake() and dist(pos, c.position()) <= radius:
                return True
        except bc.Error:
            pass
    return any(dist(pos, ep) <= radius for _, ep in st.enemies)


def retreat(me):
    commit(None)
    pos = me.position()
    altar, d = nearest_altar(pos)
    if me.gem_count() > 0 and altar is not None and d <= 1:
        me.submit_gems(altar)
        dbg("retreat: tribute at altar")
        return
    if st.spawn.is_set(pos):
        return
    if st.hurt or threats_near(me):  # damage cancels recall
        shield(me)
        go_home(me)
        hit_back(me)
        return
    me.recall()
    dbg("retreat: recall hp=%d" % me.health())


def stunned(u):
    try:
        return u.buffs().has_stun()
    except bc.Error:
        return False


def best_spell(me, target):
    """Ready damage/stun ability worth more than one basic attack on target, else None.
    One cast per turn is shared by both slots, so this is chosen before any reset."""
    if not me.can_cast():
        return None
    pos, tpos = me.position(), target.position()
    vs_champ = isinstance(target, bc.Champion)
    best, best_v, focus = None, me.strength(), None
    for ab in me.abilities():
        try:
            info = ab.info()
            if info is None or not ab.is_ready() or not (ab.is_damage() or ab.is_aoe_damage() or ab.is_cc()):
                continue
            ground = ab.can_target_ground() and not (ab.can_target_enemies() if vs_champ else ab.can_target_camps())
            if not ground and not (ab.can_target_enemies() if vs_champ else ab.can_target_camps()):
                continue
            if dist(pos, tpos) > info.range:
                continue
            focus = me.focus() if focus is None else focus
            hits = 1
            if ab.is_aoe_damage():
                pts = [ep for _, ep in st.enemies] if vs_champ else [c.position() for c in bc.vision.camps() if c.is_visible()]
                hits = max(1, count_near(pts, tpos, int(info.radius)))
            v = info.modifier * focus * hits
            if (ab.is_cc() or (ab.is_aoe_damage() and info.duration > 0)) and not stunned(target):
                v += STUN_VALUE if vs_champ else (target.strength() * hits if target.is_awake() else 0)
            if v > best_v:
                best, best_v = (ab, tpos if ground else target), v
        except bc.Error:
            continue
    return best


def cast(me, spell):
    try:
        if spell[0].use(spell[1]):
            dbg("CAST %s slot%d" % (me.champion_name(), spell[0].slot()))
            return True
    except bc.Error as e:
        dbg("cast error %r" % (e,))
    return False


def attack(me, target):
    """Best ability for this target, then basic attack; reset only if no spell was worth more
    (or the reset finishes the target)."""
    spell = best_spell(me, target)
    if spell is not None and not (target.health() <= 2 * me.strength() and reset_ready(me)):
        cast(me, spell)
    if me.can_attack() and in_range_of(me, [target]):
        me.attack(target)
    if not me.can_cast():
        return
    for ab in me.abilities():
        try:
            if ab.is_attack_reset() and ab.is_ready() and ab.use():
                if me.can_attack() and in_range_of(me, [target]):
                    me.attack(target)
                return
        except bc.Error as e:
            dbg("reset error %r" % (e,))
            return


def reset_ready(me):
    return any(ab.is_attack_reset() and ab.is_ready() for ab in me.abilities())


def precast(me, target):
    """Before walking: spells that forbid walking must be cast first, from spell range."""
    spell = best_spell(me, target)
    if spell is not None:
        cast(me, spell)


def shield(me):
    """Varg: shield when an enemy champion is hitting us (instead of a reset)."""
    if not me.can_cast() or not st.hurt or not st.enemies:
        return
    for ab in me.abilities():
        try:
            if ab.is_shield() and ab.is_ready() and ab.use():
                dbg("SHIELD")
                return
        except bc.Error:
            return


def hit_back(me):
    if not me.can_attack():
        return False
    targets = in_range_of(me, enemies_visible())
    if targets:
        attack(me, min(targets, key=lambda u: u.health()))
        return True
    camps = [c for c in in_range_of(me, bc.vision.camps()) if c.is_awake()]
    if camps:
        attack(me, best_camp(camps, camps))
        return True
    return False


def defend(me):  # fleeing on foot just dies (platform games)
    if not st.hurt or not in_range_of(me, enemies_visible()):
        return False
    shield(me)
    return hit_back(me)


def interfere_altar(me):
    lock = me.consumables()[int(LOCK)]
    if lock.count() == 0:
        return False
    pos = me.position()
    for e, ep in st.enemies:
        if not e.is_submitting_gems():
            continue
        altar, d = nearest_altar(ep)
        if altar is None or d > 1 or bc.vision.has_altar_lock(altar):
            continue
        if dist(pos, altar) <= 2:
            if lock.use(altar):
                dbg("locked altar under enemy tribute")
            return True
        if dist(pos, altar) <= 5 and me.health() > 0.5 * me.max_health():
            walk_to(me, ring(altar, 2))
            if dist(me.position(), altar) <= 2:
                lock.use(altar)
            return True
    return False


def hunt_carrier(me):
    if me.health() < CARRIER_HP * me.max_health() or not me.can_attack():
        return False
    pos = me.position()
    rng = me.attack_range()
    ally_points = list(st.ally_pos.values())
    enemy_points = [ep for _, ep in st.enemies]
    best = None
    for e, ep in st.enemies:
        try:
            if dist(pos, ep) > rng + 2:
                continue
            valuable = e.gem_count() >= CARRIER_GEMS or e.is_submitting_gems()
            if not valuable:
                continue
            ours = count_near(ally_points, ep, 4)
            theirs = count_near(enemy_points, ep, 4)
            if ours < theirs:
                continue
            if ours == 1 and e.health() > 1.5 * me.health():
                continue
            key = (-e.gem_count(), e.health())
            if best is None or key < best[0]:
                best = (key, e, ep)
        except bc.Error:
            continue
    if best is None:
        return False
    e, ep = best[1], best[2]
    if dist(pos, ep) > rng:
        precast(me, e)
        walk_to(me, ring(ep, rng))
    if me.can_attack() and in_range_of(me, [e]):
        attack(me, e)
        dbg("hit carrier")
    return True


def want_tribute(me, hp_frac):
    gems = me.gem_count()
    if gems == 0:
        return False
    pos = me.position()
    altar, d_alt = nearest_altar(pos)
    if altar is None:
        return False
    if gems >= BIG_BAG or d_alt <= NEAR_ALTAR or hp_frac < ENGAGE_HP:
        return True
    if any(dist(pos, ep) <= 6 for _, ep in st.enemies):
        return True
    tgt = st.target  # no dry pick_target scan: ~1.2M fuel on 42-group maps
    if tgt is None:
        return True
    detour = d_alt + dist(altar, tgt.center) - dist(pos, tgt.center)
    return detour <= DETOUR_OK


def tribute(me):
    commit(None)
    altar, d = nearest_altar(me.position())
    if d > 1:
        walk_to(me, ring(altar, 1))
        d = dist(me.position(), altar)
    if d <= 1:
        hit_back(me)  # free attacks before the channel starts
        me.submit_gems(altar)
        dbg("tribute %d gems" % me.gem_count())


def can_reach(me, info):
    if info.reach is None:
        if st.reach_budget <= 0:  # fixed 2/turn: a fuel gate never fired on big maps
            return True
        st.reach_budget -= 1
        spots = bc.Bitboard()  # camps ringed by holes need range
        for t in info.tiles.positions():
            spots.draw_chebyshev(t, st.rng)
        spots &= st.walkable
        spots &= ~info.tiles
        info.reach = not spots.is_empty()
    return info.reach


def target_ok(info, rnd, pos, alive):
    if info.skip or info.need > alive or st.blacklist.get(info.idx, 0) > rnd:
        return False
    if not can_reach(None, info):
        return False
    return info.respawn_at - rnd <= dist(pos, info.center)


def pick_target(me, rnd):
    pos = me.position()
    alive = alive_allies()
    cur = st.target
    if cur is not None and target_ok(cur, rnd, pos, alive):
        others = committed_others(cur)
        if cur.need > 1 or cur.reward or not any(k < st.slot for k in others):
            return cur
    best, best_score = None, 0.0
    my_str = max(1.0, me.strength())  # SDK calls ~20k each: once, not per group
    viable, left = elect()
    for info in st.groups:
        if bc.fuel_remaining() < 700_000:  # many-group maps overran fuel on platform
            break
        if not target_ok(info, rnd, pos, alive):
            continue
        if st.mem[6] == info.idx + 1 and rnd < 8 * st.mem[7]:  # its assembly just failed
            continue
        others = len(committed_others(info))
        if info.need == 1 and others >= 1 and not info.reward:
            continue
        if info.need > 1 and others >= info.need:
            continue
        if info.need > 1 and not info.reward and (info.idx not in viable if others else info.need > left):
            continue  # a squad the elected ones leave no champions for
        d = dist(pos, info.center)
        value = info.gems + GOLD_WEIGHT * info.gold
        if info.reward:
            score = value / (d + 5 + 10)
        else:
            n = info.need
            value /= n
            if 0 < others < n:
                value *= 3.0
            score = value / (d + info.hp / (n * my_str) + 5 + 10)
        if score > best_score:
            best, best_score = info, score
    commit(best)
    return best


def note_stuck(me, info, rnd):
    d = dist(me.position(), info.center)
    if st.stuck_key != info.idx or d < st.stuck_best:
        st.stuck_key, st.stuck_best, st.stuck = info.idx, d, 0
        return
    st.stuck += 1
    if st.stuck > 8:  # no progress in 8 turns: unreachable
        st.stuck_key = None
        give_up(info, rnd, 40)


def give_up(info, rnd, rounds=BLACKLIST_ROUNDS, team=False):
    st.branch += ":giveup%d" % info.idx
    st.blacklist[info.idx] = rnd + rounds
    if team:  # failed assembly: nobody newly picks it for a while
        bc.shared_memory.write(6, bytes([info.idx + 1, min(255, (rnd + TEAM_COOLDOWN) // 8)]))
    commit(None)
    dbg("give up on group %d" % info.idx)


def capture(me, info, rnd):
    others = committed_others(info)
    if any(k < st.slot for k in others):
        st.blacklist[info.idx] = rnd + 8
        commit(None)
        return
    if info.tiles.is_set(me.position()):
        if info.capture_since is None:
            info.capture_since = rnd
        elif rnd - info.capture_since > 8:  # contested
            info.capture_since = None
            give_up(info, rnd, 30)
        return
    info.capture_since = None
    walk_to(me, info.tiles)


def in_range_of(me, units):
    pos, rng, out = me.position(), me.attack_range(), []
    for u in units:
        try:
            if u.is_visible() and dist(pos, u.position()) <= rng:
                out.append(u)
        except bc.Error:
            pass
    return out


def best_camp(cands, live):
    """Kill order: most camp damage removed per turn of killing time (strength / health left).
    Varg first maximises splash: other live camps within 1 tile of the target."""
    def key(c):
        threat = st.camp_str[c.kind()] / max(1.0, c.health())
        if not st.varg:
            return threat
        p = c.spawn_position()  # camps never leave their tile
        return sum(1 for o in live if o != c and dist(o.spawn_position(), p) <= 1), threat
    return max(cands, key=key)


def fight(me, live, info, rnd):
    in_range = in_range_of(me, live)
    if not in_range:
        pos = me.position()
        goal = min(live, key=lambda c: dist(pos, c.position())) if st.enemies else best_camp(live, live)
        gpos = goal.position()  # read before precast: a spell can kill it
        precast(me, goal)
        walk_to(me, ring(gpos, me.attack_range()))
        note_stuck(me, info, rnd)
        in_range = in_range_of(me, live)
    elif st.rng == 1 and not st.enemies and not any(st.camp_str[c.kind()] for c in in_range):
        goal = best_camp(live, live)  # only harmless camps in reach: melee steps keep the attack
        if st.camp_str[goal.kind()] and goal not in in_range:
            walk_to(me, ring(goal.position(), 1))
            in_range = in_range_of(me, live)
    if in_range and me.can_attack():
        attack(me, best_camp(in_range, live))


def squad_here(info):
    count = 1
    for k in committed_others(info):
        p = st.ally_pos.get(st.handles[k])
        if p is not None and dist(p, info.center) <= 5:
            count += 1
    return count


def farm(me, rnd, hp_frac):
    info = pick_target(me, rnd)
    if info is None:
        st.branch = "farm:idle"
        idle(me, rnd)
        return
    st.branch = "farm:g%d" % info.idx
    if info.reward:
        st.branch += ":capture"
        if st.solo_fight is not None and st.solo_fight[0] == info.idx:
            g, r0, hp0, pred = st.solo_fight
            dbg("SOLO-DONE r%d s%d g%d rounds=%d took=%.0f predicted=%.0f" % (rnd, st.slot, g, rnd - r0, hp0 - me.health(), pred))
            st.solo_fight = None
        capture(me, info, rnd)
        return
    live = live_camps(info)
    awake = any(c.is_awake() for c in live)
    if not awake and info.need > 1 and reassign(info, rnd):  # not fighting yet: is my squad elected?
        st.branch += ":reassign"
        return
    if not live:
        st.branch += ":approach"
        pos = me.position()
        goals = ring(info.center, 1, exclude=info.tiles)
        if info.in_bush and not (goals & st.bushes).is_empty():  # bush camps only visible from inside
            goals = goals & st.bushes
        if dist(pos, info.center) <= 1:
            give_up(info, rnd, 30)
        elif not walk_to(me, goals):
            walk_to(me, ring(info.center, 3, exclude=info.tiles))
        note_stuck(me, info, rnd)
        return
    if not awake:
        if hp_frac < ENGAGE_HP:
            st.branch += ":lowhp"
            retreat(me)
            return
        if info.need == 1:  # solo: the predicted fight must end above the retreat line
            left = sorted(((c.health(), st.camp_str[c.kind()]) for c in live), key=lambda c: -c[1] / c[0])
            hp, spare = me.health(), me.health() - RETREAT_HP * me.max_health()
            abs_ = me.abilities()
            cds = tuple(0 if k is None else abs_[k].cooldown() for k in st.kit)
            pred = solo_damage(left, st.atk, st.kit, st.taken, cds)
            if pred > spare:
                if solo_damage(left, st.atk, st.kit, st.taken) <= spare:  # only a cooldown short
                    st.branch += ":cooldown"
                    walk_to(me, ring(info.center, 3, exclude=info.tiles))
                    return
                st.branch += ":unready"
                dbg("SOLO-UNREADY r%d s%d g%d predicted=%.0f hp=%.0f" % (rnd, st.slot, info.idx, pred, hp))
                retreat(me)
                return
            st.solo_fight = (info.idx, rnd, hp, pred)
        here = squad_here(info)
        if here < info.need:
            st.branch += ":wait%d/%d" % (here, info.need)
            if assembly_failed(info, here, rnd):
                give_up(info, rnd, team=True)
                return
            walk_to(me, ring(info.center, 3, exclude=info.tiles))
            return
    if st.wait is not None and st.wait[0] == info.idx and st.wait[4] == rnd - 1:
        dbg("ASM r%d s%d fight g%d after %d here=%d" % (rnd, st.slot, info.idx, rnd - st.wait[1], squad_here(info)))
    st.branch += ":fight"
    fight(me, live, info, rnd)


def idle(me, rnd):
    pos = me.position()
    soon = [g for g in st.groups if not g.skip and g.need <= alive_allies()]
    if not soon:
        return
    g = min(soon, key=lambda g: (max(g.respawn_at - rnd, dist(pos, g.center)), g.idx))
    walk_to(me, ring(g.center, 3, exclude=g.tiles))


def draft_turn():
    picked = [int(c) for c in bc.draft.current_draft(ALLY)]
    for c in PICK_ORDER:
        if int(c) not in picked:
            bc.draft.pick(c)
            return


def play_turn():
    if not st.ready:
        init()
        return  # turn 1 = setup only (fuel)
    me = bc.me()
    rnd = bc.round_number()
    shop(me)
    if not me.is_alive():
        if st.was_alive:
            dbg("DIED r%d s%d" % (rnd, st.slot))
        st.was_alive = False
        commit(None)
        return
    st.was_alive = True
    if me.is_submitting_gems() or me.is_recalling() or me.is_teleporting():
        return
    read_memory()
    refresh_allies()
    observe(rnd)
    hp_frac = me.health() / me.max_health()
    st.hurt = me.health() < st.last_hp
    st.last_hp = me.health()
    if rnd % 100 == 0 and st.slot == 0:
        dbg("SCORE r%d us=%d them=%d" % (rnd, bc.global_submitted_gems(ALLY),
                                         bc.global_submitted_gems(ENEMY)))
    if rnd % 25 == 0:
        dbg("r%d s%d %s pos=%s hp=%d/%d gems=%d gold=%d tgt=%s" % (
            rnd, st.slot, me.champion_name(), me.position(), me.health(), me.max_health(), me.gem_count(),
            me.gold_count(), None if st.target is None else st.target.idx))
    st.branch = ""
    st.reach_budget = 2
    bc.debug_block(lambda: tel_begin(me))
    act(me, rnd, hp_frac)
    bc.debug_block(lambda: tel_end(me, rnd))


def tel_begin(me):  # debug only: snapshot to detect turns with no useful action
    st.tel = st.tel or {"noop": {}, "turns": 0, "skip0": st.fuelskip}
    st.tel["pos"], st.tel["atk"] = me.position(), me.can_attack()


def tel_end(me, rnd):
    t = st.tel
    t["turns"] += 1
    acted = (me.position() != t["pos"] or (t["atk"] and not me.can_attack())
             or me.is_submitting_gems() or me.is_recalling())
    if not acted:
        key = st.branch.split(":giveup")[0] or "none"
        t["noop"][key] = t["noop"].get(key, 0) + 1
    if rnd % 100 == 0:
        top = sorted(t["noop"].items(), key=lambda kv: -kv[1])[:6]
        print("TEL r%d s%d turns=%d noop=%d fuelskip=%d top=%s" % (
            rnd, st.slot, t["turns"], sum(t["noop"].values()), st.fuelskip, top))


def act(me, rnd, hp_frac):
    if st.spawn.is_set(me.position()) and hp_frac < 0.95:
        st.branch = "heal"
        commit(None)
        hit_back(me)  # still use attacks/casts without leaving spawn
        return
    if interfere_altar(me):
        st.branch = "lock"
        hit_back(me)
        return
    if hp_frac < RETREAT_HP:
        st.branch = "retreat"
        retreat(me)
        return
    st.branch = "champfight"
    if defend(me) or hunt_carrier(me):
        return
    if want_tribute(me, hp_frac):
        st.branch = "tribute"
        tribute(me)
        return
    farm(me, rnd, hp_frac)
