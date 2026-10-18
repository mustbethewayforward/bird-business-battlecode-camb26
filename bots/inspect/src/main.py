"""Map inspector, not a competitive bot.

During the draft (which can see the whole map) it prints the map size, team size,
every camp group (gems, gold, camp kinds, strength) and the altars, then an ASCII
picture for maps up to 3000 tiles. Run it against itself for one round and read
team-a.stdout in the replay zip (scripts/logs.py does that):

    cambc run inspect inspect --map <map> --rounds 1
    python scripts/logs.py replays

Picture key: G gem cluster, D gold cluster, w wolf, E elk, M monolith, A altar,
# wall, o hole, " bush, 1 our spawn, 2 enemy spawn.
"""
import cambc as bc
from cambc import game_map as gm

KIND_CHAR = {0: "w", 1: "E", 2: "G", 3: "D", 4: "M"}  # CampType values


def dump():
    w, h = gm.width(), gm.height()
    print("SIZE", w, h, "team_size", bc.draft.team_size(), "symmetry", gm.symmetry())
    camp_at = {}
    for i, g in enumerate(gm.camp_groups()):
        kinds = []
        for c in g.camps():
            p = c.spawn_position()
            camp_at[(p.x, p.y)] = KIND_CHAR.get(int(c.kind()), "?")
            kinds.append(KIND_CHAR.get(int(c.kind()), "?"))
        print("GROUP", i, "gems", g.gem_value(), "gold", g.gold_value(),
              "respawn", g.max_respawn_timer(), "camps", "".join(kinds),
              "strength", [c.base_stats().base_strength for c in g.camps()],
              "tiles", [(p.x, p.y) for p in g.spawn_tiles().positions()])
    print("ALTARS", [(p.x, p.y) for p in gm.altars().positions()])
    if w * h > 3000:
        return  # drawing big maps tile by tile runs out of draft fuel
    walls, holes, altars, bushes = gm.walls(), gm.holes(), gm.altars(), gm.bushes()
    ours, theirs = gm.spawn_region(bc.Team.ALLY), gm.spawn_region(bc.Team.ENEMY)
    for y in range(h - 1, -1, -1):  # north (+y) at the top
        row = ""
        for x in range(w):
            v = bc.Vec2(x, y)
            if (x, y) in camp_at:
                row += camp_at[(x, y)]
            elif altars.is_set(v):
                row += "A"
            elif walls.is_set(v):
                row += "#"
            elif holes.is_set(v):
                row += "o"
            elif ours.is_set(v):
                row += "1"
            elif theirs.is_set(v):
                row += "2"
            elif bushes.is_set(v):
                row += '"'
            else:
                row += "."
        print(row)


def main():
    dumped = False
    while True:
        try:
            if bc.is_draft():
                if not dumped:
                    dumped = True
                    dump()
                picked = [int(c) for c in bc.draft.current_draft(bc.Team.ALLY)]
                for c in range(11):
                    if c not in picked:
                        bc.draft.pick(c)
                        break
        except Exception as e:
            print("ERR", repr(e))
        bc.end_turn()


main()
