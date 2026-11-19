import sys
from pathlib import Path


def balance(path):
    text = Path(path).read_text(encoding="utf-8")
    depth = 0
    in_str = False
    i = 0
    line = 1
    worst = []
    while i < len(text):
        c = text[i]
        if c == "\n":
            line += 1
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
        else:
            if c == ";":
                while i < len(text) and text[i] != "\n":
                    i += 1
                continue
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth < 0:
                    worst.append((line, depth))
                    depth = 0
        i += 1
    return depth, worst


for p in sys.argv[1:]:
    d, bad = balance(p)
    print(p, "final depth:", d, "negative at:", bad[:5])
