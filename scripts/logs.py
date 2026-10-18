"""Print one team's stdout from a replay bundle.

    python scripts/logs.py <file.repl26a | directory> [team-a|team-b]

Given a directory, uses the newest .repl26a in it. Bot prints (including
debug_block output in debug builds) land in team-a.stdout / team-b.stdout.
"""
import glob
import os
import sys
import zipfile


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "replays"
    team = sys.argv[2] if len(sys.argv) > 2 else "team-a"
    if os.path.isdir(path):
        bundles = sorted(glob.glob(os.path.join(path, "*.repl26a")), key=os.path.getmtime)
        if not bundles:
            sys.exit("no .repl26a in %s" % path)
        path = bundles[-1]
    with zipfile.ZipFile(path) as z:
        sys.stdout.write(z.read(team + ".stdout").decode("utf8", "replace"))


if __name__ == "__main__":
    main()
