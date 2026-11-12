from zerobox.dieline import Stroke


def grid2x2(s=100.0):
    out = []
    for i in range(2):
        for j in range(2):
            x, y = 50 + i * s, 50 + j * s
            out.append(Stroke([(x, y), (x + s, y), (x + s, y + s), (x, y + s)], True))
    return out
