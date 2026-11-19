from pathlib import Path
import sys

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
depth = 0
in_str = False
line = 1
starts = []
i = 0
lines_at_depth0_end = []
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
            if depth == 0:
                starts.append(line)
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                lines_at_depth0_end.append(line)
    i += 1
print("final depth", depth)
print("forms opened at:", starts)
print("forms closed at:", lines_at_depth0_end)
print("in_string_at_eof:", in_str)
