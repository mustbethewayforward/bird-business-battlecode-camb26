"""Run the real abandon_squad() and the broadcast write from a bot.py source:
    python3 scripts/test_abandon.py bots/exp-squad/src/bot.py
The broadcast bytes are produced by the source's own write expression (captured via a fake shared_memory)."""
import ast, sys, types

src = open(sys.argv[1]).read()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "abandon_squad")
consts = [n for n in tree.body if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "ABANDON_BYTE" for t in n.targets)]
# the leader's write call, taken verbatim from farm()
write_line = next(l.strip() for l in src.splitlines() if "shared_memory.write(ABANDON_BYTE" in l)

class St: pass
class Info:
    def __init__(self, idx): self.idx = idx

def run_case(announce_round, check_round, n_champs=5, target_idx=4, announced_idx=4):
    mem = bytearray(8)
    class SM:
        @staticmethod
        def write(off, data): mem[off:off + len(data)] = data
    bc = types.SimpleNamespace(shared_memory=SM)
    g = {"bc": bc}
    exec(compile(ast.Module(body=consts, type_ignores=[]), "c", "exec"), g)
    info, rnd = Info(announced_idx), announce_round
    exec(write_line, g, {"info": info, "rnd": rnd})          # leader broadcasts
    st = St(); st.handles = list(range(n_champs)); st.mem = bytes(mem); st.target = Info(target_idx)
    dropped = []
    g.update(st=st, give_up=lambda info, rnd: dropped.append(rnd))
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "f", "exec"), g)
    g["abandon_squad"](check_round)
    return bool(dropped)

cases = [  # (announce, check, expected, note)
    (100, 100, True,  "same round: follower drops"),
    (100, 101, True,  "next round: follower drops"),
    (100, 104, None,  "short window (informational)"),
    (100, 356, False, "+256: stays expired"),
    (100, 612, False, "+512: stays expired"),
    (100, 1124, False, "+1024: stays expired"),
    (7, 8, True,      "window crosses a block edge"),
    (1999, 1999, True, "last round"),
    (100, 140, False, "40 rounds later, leader dead/no rewrite: expired"),
]
fail = 0
for a, c, exp, note in cases:
    got = run_case(a, c)
    ok = exp is None or got == exp
    fail += not ok
    print("%-4s announce r%-4d check r%-4d drops=%-5s %s" % ("ok" if ok else "FAIL", a, c, got, note))
got = run_case(100, 100, target_idx=3)
print("%-4s other target ignored: drops=%s" % ("ok" if not got else "FAIL", got)); fail += got
got = run_case(100, 100, n_champs=7)
print("%-4s team of 7 (bytes 6-7 are slots): drops=%s" % ("ok" if not got else "FAIL", got)); fail += got
print("FAILURES", fail)
sys.exit(1 if fail else 0)
