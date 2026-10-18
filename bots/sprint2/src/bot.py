"""CAMBC Sprint 1 bot: squad camp farmer.

Every champion runs this same file. Each turn, in priority order:
  1. Shop (on spawn, while dead, or anywhere for Tavi).
  2. Keep any channel (tribute, recall) running.
  3. Heal on spawn before leaving.
  4. Lock an altar an enemy is tributing at, if we carry a lock.
  5. Retreat when health is low: walk home while being hit (damage cancels recall),
     recall once nothing is hitting us.
  6. Hit back at an enemy champion hitting us, or attack a valuable enemy carrier,
     but only with even or better numbers nearby.
  7. Tribute when the bag is big, the altar is close or on the way, enemies are near,
     or we are hurt.
  8. Farm: pick a camp group, gather a squad if it needs one, kill it, capture it.

Coordination: champions are numbered 0..n-1 by sorted engine handle. Shared memory
byte k holds (group index + 1) for the group champion k is committed to, 0 for none.
Groups one champion can solo get one champion; harder groups wait for a squad.
Monolith groups are never targeted.

Safety valves (each found in local testing):
  - A target we stop getting closer to for 8 turns is dropped for 40 rounds
    (no path, camps behind holes, or camps hidden in bushes).
  - A capture still unclaimed after 8 rounds on the tile is contested: leave.
  - Pathfinding is skipped when the turn's fuel is low, so a turn never overruns.
  - The first turn only runs setup (the SDK charges ~20k fuel per call).
"""
import cambc as bc
from cambc import game_map as gm

ALLY, ENEMY = bc.Team.ALLY, bc.Team.ENEMY

# ---------------------------------------------------------------- tunables
DEBUG = True
RETREAT_HP = 0.35       # step away and recall below this share of max health
ENGAGE_HP = 0.6         # do not wake a new camp below this share of max health
BIG_BAG = 50            # always go tribute once carrying this many gems
NEAR_ALTAR = 2          # tribute any bag if an altar is this close
DETOUR_OK = 10          # tribute if the altar costs at most this many extra steps
GOLD_WEIGHT = 0.05      # a gold-only camp is worth this many gems per gold
SAFE_SHARE = 0.5        # a fight is OK if expected damage per champion < this share of health
MULTI_CAMP_FACTOR = 0.65  # camps in a group die one by one, so total damage is below full dps * time
SQUAD_WAIT = 80         # rounds to wait for squad mates before giving up on a group
BLACKLIST_ROUNDS = 60   # how long to ignore a group we gave up on
CARRIER_GEMS = 15       # an enemy carrying at least this many gems is worth attacking
CARRIER_HP = 0.5        # only chase carriers above this share of max health
MOVE_FUEL_RESERVE = 1_300_000  # skip pathfinding when less fuel than this is left this turn

PICK_ORDER = [
    bc.ChampionDraft.RYTH, bc.ChampionDraft.VARG, bc.ChampionDraft.MARCELLA,
    bc.ChampionDraft.VENDETTA, bc.ChampionDraft.REN, bc.ChampionDraft.VESPER_VALE,
    bc.ChampionDraft.CASSI_AND_ISSAC, bc.ChampionDraft.TAVI, bc.ChampionDraft.STELLAR,
    bc.ChampionDraft.PRISM, bc.ChampionDraft.WILLOW,
]

I = bc.ItemType
# Shop builds: (shard, emblem) stages bought in order, five shards each.
# Monster = +10% camp damage, Jungle = -30% camp damage, Treasure = +20% gold.
BUILD_DEFAULT = [(I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
                 (I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),
                 (I.POWER_SHARD_OF_STRENGTH, I.POWER_EMBLEM_OF_STRENGTH)]
BUILD_TANKY_FIRST = [(I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),
                     (I.MONSTER_SHARD_OF_STRENGTH, I.MONSTER_EMBLEM_OF_STRENGTH),
                     (I.POWER_SHARD_OF_STRENGTH, I.POWER_EMBLEM_OF_STRENGTH)]
BUILD_RYTH = [(I.JUNGLE_SHARD_OF_HEALTH, I.JUNGLE_EMBLEM_OF_HEALTH),   # health also adds strength
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


def log(msg):
    print(msg)


def dbg(msg):
    # debug_block costs no fuel locally and is skipped entirely on the platform
    if DEBUG:
        bc.debug_block(lambda: print(msg))


def dist(a, b):
    return a.chebyshev_distance(b)


# ---------------------------------------------------------------- per-champion state

class GroupInfo:
    """Static facts about one camp group plus what this champion has seen of it."""

    def __init__(self, idx, group, avg_str, avg_hp, n_allies):
        camps = group.camps()
        self.idx = idx
        self.group = group
        self.tiles = group.spawn_tiles()                 # Bitboard
        tile_list = self.tiles.positions()
        self.center = tile_list[len(tile_list) // 2]
        self.gems = group.gem_value()
        self.gold = group.gold_value()
        # Every SDK call costs fuel (~20k each), so read each camp's stats once.
        stats = [c.base_stats() for c in camps]
        self.hp = sum(s.base_health for s in stats)
        self.dps = sum(s.base_strength for s in stats)
        factor = 1.0 if len(camps) == 1 else MULTI_CAMP_FACTOR
        self.need = squad_size(self.hp, self.dps * factor, avg_str, avg_hp, n_allies)
        self.in_bush = not (self.tiles & st.bushes).is_empty()
        monolith = any(s.base_health >= 10000 for s in stats)  # monoliths have 20,000 HP
        self.skip = monolith or (self.gems == 0 and self.gold == 0)
        self.reach = None        # computed lazily by can_reach() to keep the first turn cheap
        self.respawn_at = 0      # round we expect it back (0 = alive or unknown)
        self.reward = False      # all camps dead, reward waiting to be captured
        self.wait_since = None   # round we started waiting here for squad mates
        self.capture_since = None  # round we stepped onto its spawn tile to capture


def squad_size(hp, dps, avg_str, avg_hp, n_allies):
    """Smallest squad whose estimated damage per member stays under SAFE_SHARE of health."""
    for n in range(1, n_allies + 1):
        rounds = hp / (n * avg_str)
        if dps * rounds / n < SAFE_SHARE * avg_hp:
            return n
    return 99  # too dangerous for the whole team


class State:
    ready = False
    walkable = None     # Bitboard: not wall, hole, altar or enemy spawn
    spawn = None        # Bitboard: our spawn region
    spawn_list = []
    altars = []
    bushes = None
    max_dist = 10000
    stuck = 0               # turns without getting closer to stuck_key's group
    stuck_key = None
    stuck_best = 0
    last_hp = 0.0           # our health at the start of last turn
    hurt = False            # took damage since last turn
    handles = []        # sorted ally handles; index = shared memory slot
    slot = 0
    groups = []
    by_handle = {}      # int(group) -> GroupInfo
    target = None       # GroupInfo we are committed to
    mem = bytearray(8)
    blacklist = {}      # group idx -> round until which we ignore it
    last_slot_value = -1
    alive_slots = []
    visible_allies = {}
    ally_pos = {}           # handle -> position, visible allies, this turn
    enemies = []            # (champion, position) for visible enemies, this turn
    static_blocked = None   # Bitboard: walls, holes, altars, enemy spawn
    was_alive = True


st = State()


def init():
    """One-off setup on the first gameplay turn (it gets double fuel)."""
    me = bc.me()
    st.static_blocked = gm.walls() | gm.holes() | gm.altars() | gm.spawn_region(ENEMY)
    st.walkable = ~st.static_blocked
    st.spawn = gm.spawn_region(ALLY)
    st.spawn_list = st.spawn.positions()
    st.altars = gm.altars().positions()
    st.bushes = gm.bushes()
    st.max_dist = gm.width() * gm.height()  # the search's default cap is too short on big maps
    allies = bc.champions(ALLY)
    st.handles = sorted(int(c) for c in allies)
    st.slot = st.handles.index(int(me))
    stats = [c.base_stats() for c in allies]
    avg_str = sum(s.base_strength for s in stats) / len(stats)
    avg_hp = sum(s.base_health for s in stats) / len(stats)
    st.groups = []
    for i, g in enumerate(gm.camp_groups()):
        info = GroupInfo(i, g, avg_str, avg_hp, len(allies))
        st.groups.append(info)
        st.by_handle[int(g)] = info
    st.ready = True
    dbg("init slot=%d %s groups=%s" % (st.slot, me.champion_name(),
        [(g.idx, g.gems, g.need) for g in st.groups if not g.skip]))


# ---------------------------------------------------------------- shared memory

def read_memory():
    buf = bytearray(8)
    bc.shared_memory.read(0, buf)
    st.mem = buf


def commit(info):
    """Publish which group we are working on (None = free)."""
    st.target = info
    value = 0 if info is None else info.idx + 1
    if value != st.last_slot_value:
        bc.shared_memory.write(st.slot, bytes([value]))
        st.last_slot_value = value


def refresh_allies():
    """Once per turn: which ally slots are alive, and the visible allies by handle."""
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
    """Slots of other living allies committed to this group."""
    want = info.idx + 1
    return [k for k in st.alive_slots if k != st.slot and k < 8 and st.mem[k] == want]


def alive_allies():
    return len(st.alive_slots)


# ---------------------------------------------------------------- observation

def observe(rnd):
    """Update respawn / reward knowledge for every group with a spawn tile in vision."""
    for g in bc.vision.camp_groups():
        info = st.by_handle.get(int(g))
        if info is None:
            continue
        try:
            s = g.state()
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
    """Visible living camps of a group."""
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


# ---------------------------------------------------------------- movement

def ring(center, rng, exclude=None):
    """Bitboard of free walkable tiles within Chebyshev rng of center."""
    bb = bc.Bitboard()
    bb.draw_chebyshev(center, rng)
    bb &= st.walkable
    bb &= ~(bc.vision.champion_tiles() | bc.vision.camp_tiles())
    if exclude is not None:
        bb &= ~exclude
    return bb


def walk_to(me, goals):
    """One step along a shortest path to the nearest tile of the goals Bitboard.

    One breadth-first search per call (DistanceField from all goals, stopping when it
    reaches us). A step can return False when a hidden enemy in a bush blocks it; that
    tile is then known, so we try the next best step. True if we moved."""
    if goals is None or not me.can_move():
        return False
    if bc.fuel_remaining() < MOVE_FUEL_RESERVE:
        return False  # a search with no path floods the whole map; never risk the turn
    origin = me.position()
    if goals.is_set(origin):
        return False  # already on a goal tile
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
            if me.move_absolute(p):
                return True
        except bc.Error as e:
            dbg("move error %r" % (e,))
    return False


def go_home(me):
    walk_to(me, st.spawn)


# ---------------------------------------------------------------- shopping

def shop(me):
    """Buy the champion's build on spawn, while dead, or anywhere for Tavi (shards only)."""
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
        break  # finish this stage before the next
    # One altar lock once the first emblem is done (only purchasable on spawn / dead).
    if on_spawn and first_emblem_done and gold >= LOCK.cost():
        if me.consumables()[int(LOCK)].count() == 0 and me.can_buy(LOCK):
            me.buy(LOCK)


# ---------------------------------------------------------------- safety

def threats_near(me, radius=4):
    """True if an awake camp or an enemy champion is within radius."""
    pos = me.position()
    for c in bc.vision.camps():
        try:
            if c.is_awake() and dist(pos, c.position()) <= radius:
                return True
        except bc.Error:
            pass
    return any(dist(pos, ep) <= radius for _, ep in st.enemies)


def retreat(me):
    """Low health: bank gems if an altar is adjacent, else get clear of threats and recall."""
    commit(None)
    pos = me.position()
    altar, d = nearest_altar(pos)
    if me.gem_count() > 0 and altar is not None and d <= 1:
        me.submit_gems(altar)
        dbg("retreat: tribute at altar")
        return
    if st.spawn.is_set(pos):
        return
    if st.hurt or threats_near(me):
        # Damage cancels a recall, so walk home and hit back at whatever is in range.
        go_home(me)
        hit_back(me)
        return
    me.recall()
    dbg("retreat: recall hp=%d" % me.health())


# ---------------------------------------------------------------- enemy interaction

def attack(me, target):
    """Basic-attack, then use an attack-reset ability if ready and attack again
    (Ryth, Varg, Vendetta, Marcella, Vesper, Tavi, Willow have one)."""
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


def hit_back(me):
    """Basic-attack an enemy champion in range, else an awake camp in range."""
    if not me.can_attack():
        return False
    targets = in_range_of(me, enemies_visible())
    if not targets:
        targets = [c for c in in_range_of(me, bc.vision.camps()) if c.is_awake()]
    if targets:
        attack(me, min(targets, key=lambda u: u.health()))
        return True
    return False


def defend(me):
    """Being hit with an enemy champion in range: always hit back. Platform games
    showed running on foot just means dying without dealing damage."""
    if not st.hurt or not in_range_of(me, enemies_visible()):
        return False
    return hit_back(me)


def interfere_altar(me):
    """Drop our altar lock on an altar an enemy is tributing at."""
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
    """Attack a visible enemy carrying many gems (or tributing), only with even or better numbers."""
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
        walk_to(me, ring(ep, rng))
    if me.can_attack() and in_range_of(me, [e]):
        attack(me, e)
        dbg("hit carrier")
    return True


# ---------------------------------------------------------------- tribute

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
        return True  # bank before someone takes it
    tgt = st.target if st.target is not None else pick_target(me, bc.round_number(), dry=True)
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
        me.submit_gems(altar)
        dbg("tribute %d gems" % me.gem_count())


# ---------------------------------------------------------------- farming

def can_reach(me, info):
    """Is there a walkable tile within our attack range of the group? (Camps ringed by
    holes can only be hit by ranged champions.) Cached after the first check."""
    if info.reach is None:
        if bc.fuel_remaining() < 1_500_000:
            return True  # not checked yet (checks are spread over turns); assume reachable
        spots = bc.Bitboard()
        for t in info.tiles.positions():
            spots.draw_chebyshev(t, me.attack_range())
        spots &= st.walkable
        spots &= ~info.tiles
        info.reach = not spots.is_empty()
    return info.reach


def target_ok(info, rnd, pos, alive):
    if info.skip or info.need > alive or st.blacklist.get(info.idx, 0) > rnd:
        return False
    if not can_reach(bc.me(), info):
        return False
    return info.respawn_at - rnd <= dist(pos, info.center)


def pick_target(me, rnd, dry=False):
    """Keep the current target while it is valid, else choose the best value per round."""
    pos = me.position()
    alive = alive_allies()
    cur = st.target
    if cur is not None and target_ok(cur, rnd, pos, alive):
        others = committed_others(cur)
        # A solo group belongs to the lowest slot committed to it.
        if cur.need > 1 or cur.reward or not any(k < st.slot for k in others):
            return cur
    best, best_score = None, 0.0
    for info in st.groups:
        if not target_ok(info, rnd, pos, alive):
            continue
        others = len(committed_others(info))
        if info.need == 1 and others >= 1 and not info.reward:
            continue  # separate camps: someone else has it
        if info.need > 1 and others >= info.need:
            continue  # squad already full
        d = dist(pos, info.center)
        value = info.gems + GOLD_WEIGHT * info.gold
        if info.reward:
            score = value / (d + 5 + 10)
        else:
            n = info.need
            value /= n
            if 0 < others < n:
                value *= 3.0  # fill squads that are already forming
            score = value / (d + info.hp / (n * max(1.0, me.strength())) + 5 + 10)
        if score > best_score:
            best, best_score = info, score
    if not dry:
        commit(best)
    return best


def note_stuck(me, info, rnd):
    """Called while approaching a target. If we have not got any closer for 8 turns
    (no path, or bouncing between two tiles), the target is unreachable for now."""
    d = dist(me.position(), info.center)
    if st.stuck_key != info.idx or d < st.stuck_best:
        st.stuck_key, st.stuck_best, st.stuck = info.idx, d, 0
        return
    st.stuck += 1
    if st.stuck > 8:
        st.stuck_key = None
        give_up(info, rnd, 40)


def give_up(info, rnd, rounds=BLACKLIST_ROUNDS):
    st.blacklist[info.idx] = rnd + rounds
    info.wait_since = None
    commit(None)
    dbg("give up on group %d" % info.idx)


def capture(me, info, rnd):
    """All camps dead: the lowest committed slot stands on a spawn tile for 5 rounds."""
    others = committed_others(info)
    if any(k < st.slot for k in others):
        # Someone else captures; leave and find more work.
        st.blacklist[info.idx] = rnd + 8
        commit(None)
        return
    if info.tiles.is_set(me.position()):
        # Standing on it: wait out the 5-round timer. Still unclaimed after 8 rounds
        # means an enemy is contesting the region, so go elsewhere for a while.
        if info.capture_since is None:
            info.capture_since = rnd
        elif rnd - info.capture_since > 8:
            info.capture_since = None
            give_up(info, rnd, 30)
        return
    info.capture_since = None
    walk_to(me, info.tiles)


def in_range_of(me, units):
    """Units still visible and within attack range (vision can change after a step)."""
    pos, rng, out = me.position(), me.attack_range(), []
    for u in units:
        try:
            if u.is_visible() and dist(pos, u.position()) <= rng:
                out.append(u)
        except bc.Error:
            pass
    return out


def fight(me, live, info, rnd):
    """Hit the weakest camp in range, moving into range first if needed."""
    in_range = in_range_of(me, live)
    if not in_range:
        pos = me.position()
        nearest = min(live, key=lambda c: dist(pos, c.position()))
        walk_to(me, ring(nearest.position(), me.attack_range()))
        note_stuck(me, info, rnd)
        in_range = in_range_of(me, live)
    if in_range and me.can_attack():
        attack(me, min(in_range, key=lambda c: c.health()))


def squad_here(info):
    """Allies (including me) committed to this group and within 5 tiles of it."""
    count = 1
    for k in committed_others(info):
        p = st.ally_pos.get(st.handles[k])
        if p is not None and dist(p, info.center) <= 5:
            count += 1
    return count


def farm(me, rnd, hp_frac):
    info = pick_target(me, rnd)
    if info is None:
        idle(me, rnd)
        return
    if info.reward:
        capture(me, info, rnd)
        return
    live = live_camps(info)
    if not live:
        # Not in vision yet. Camps inside bushes are only visible from next to them,
        # so walk right up (never onto its spawn tiles). Unseen when adjacent: skip a while.
        pos = me.position()
        goals = ring(info.center, 1, exclude=info.tiles)
        if info.in_bush and not (goals & st.bushes).is_empty():
            goals = goals & st.bushes
        if dist(pos, info.center) <= 1:
            give_up(info, rnd, 30)
        elif not walk_to(me, goals):
            walk_to(me, ring(info.center, 3, exclude=info.tiles))
        note_stuck(me, info, rnd)
        return
    awake = any(c.is_awake() for c in live)
    if not awake:
        if hp_frac < ENGAGE_HP:
            retreat(me)
            return
        if squad_here(info) < info.need:
            if info.wait_since is None:
                info.wait_since = rnd
            if rnd - info.wait_since > SQUAD_WAIT:
                give_up(info, rnd)
                return
            walk_to(me, ring(info.center, 3, exclude=info.tiles))
            return
    info.wait_since = None
    fight(me, live, info, rnd)


def idle(me, rnd):
    """Nothing worth doing: wait next to the group that comes back soonest."""
    pos = me.position()
    soon = [g for g in st.groups if not g.skip and g.need <= alive_allies()]
    if not soon:
        return
    g = min(soon, key=lambda g: (max(g.respawn_at - rnd, dist(pos, g.center)), g.idx))
    walk_to(me, ring(g.center, 3, exclude=g.tiles))


# ---------------------------------------------------------------- entry points

def draft_turn():
    picked = [int(c) for c in bc.draft.current_draft(ALLY)]
    for c in PICK_ORDER:
        if int(c) not in picked:
            bc.draft.pick(c)
            return


def play_turn():
    if not st.ready:
        init()
        return  # setup is expensive; acting on top of it can overrun the first-turn fuel
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
        return  # mid channel
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
    if st.spawn.is_set(me.position()) and hp_frac < 0.95:
        commit(None)
        return  # spawn heals us at turn end
    if interfere_altar(me):
        return
    if hp_frac < RETREAT_HP:
        retreat(me)
        return
    if defend(me) or hunt_carrier(me):
        return
    if want_tribute(me, hp_frac):
        tribute(me)
        return
    farm(me, rnd, hp_frac)
