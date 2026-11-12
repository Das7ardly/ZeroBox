"""Fold the die in 3D and project it with a perspective camera. Qt-free.

Each face is planar, so its projection to the screen is a homography of the flat die:
the renderer draws the flat artwork through that 3x3 matrix, no OpenGL needed."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

LIGHT = np.array([-0.25, 0.35, 0.9])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def _rot(axis, ang):
    x, y, z = axis
    c, s = math.cos(ang), math.sin(ang)
    C = 1 - c
    R = np.eye(4)
    R[:3, :3] = [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
                 [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
                 [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]
    return R


def _trans(v):
    T = np.eye(4)
    T[:3, 3] = v
    return T


def lens_fov(focal_mm: float) -> float:
    """Angle of view across the short side (24 mm) of a full-frame sensor."""
    return math.degrees(2 * math.atan(12.0 / focal_mm))


# (label, focal length mm)
LENSES = [
    ("35 mm (широк)", 35.0),
    ("50 mm (нормален)", 50.0),
    ("Nikon NIKKOR Z 85mm f/1.8 S", 85.0),
    ("Nikon NIKKOR Z MC 105mm f/2.8 VR S", 105.0),
    ("Nikon NIKKOR Z 135mm f/1.8 S Plena", 135.0),
]

# light presets: (x, y) on the light pad (front hemisphere, y up), shadow strength %, brightness %
LIGHTS = {
    "original": (-0.25, 0.35, 12, 100),
    "soft": (-0.45, 0.45, 30, 102),
    "contrast": (-0.65, 0.5, 60, 104),
}


def light_vector(x, y):
    """Light pad position (unit disk, y up) -> direction in camera space (light comes from there)."""
    r2 = x * x + y * y
    if r2 > 0.98:
        k = math.sqrt(0.98 / r2)
        x, y, r2 = x * k, y * k, 0.98
    return np.array([x, y, math.sqrt(1 - r2)])


def ease(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def fold_amount(fold, t):
    if fold.end <= fold.start:
        return 1.0 if t >= fold.end else 0.0
    return ease((t - fold.start) / (fold.end - fold.start))


# flat die (x right, y down) -> world plane z=0 (x right, y up); print faces +Z
FLAT = np.array([[1.0, 0, 0], [0, -1.0, 0], [0, 0, 0], [0, 0, 1.0]])


def face_transforms(model, t: float, extra_roll: float = 0.0):
    """World matrix (4x4) of every face for fold progress t in 0..1."""
    faces, folds = model.faces, model.folds
    base = _rot((0, 0, 1), math.radians(model.up_rotation + extra_roll))
    if getattr(model, "floor", False):
        # trays, pyramids, cubes: the main panel is the bottom, walls stand up from it
        base = _rot((1, 0, 0), math.radians(90)) @ base
    M = {model.root: base}
    order = [model.root]
    for f in order:
        for c in faces[f].children:
            fd = folds[faces[c].fold]
            axis = fd.__dict__.get("_axis")
            if axis is None:
                # the hinge line in world coordinates never changes: keep it on the fold
                P0 = np.array([fd.p0[0], -fd.p0[1], 0.0])
                u = np.array([fd.p1[0], -fd.p1[1], 0.0]) - P0
                n = float(np.linalg.norm(u))
                axis = fd.__dict__["_axis"] = (P0, u / n if n >= 1e-9 else None)
            P0, u = axis
            ang = math.radians(fd.angle) * fold_amount(fd, t) * fd.sign
            if u is None or not math.isfinite(ang):
                M[c] = M[f]
            else:
                # rotation about the line through P0 along u, written out (hot path)
                x, y, z = u
                cs, sn = math.cos(ang), math.sin(ang)
                C = 1 - cs
                R = np.array([[cs + x * x * C, x * y * C - z * sn, x * z * C + y * sn],
                              [y * x * C + z * sn, cs + y * y * C, y * z * C - x * sn],
                              [z * x * C - y * sn, z * y * C + x * sn, cs + z * z * C]])
                T = np.empty((4, 4))
                T[:3, :3] = R
                T[:3, 3] = P0 - R @ P0
                T[3] = (0.0, 0.0, 0.0, 1.0)
                M[c] = M[f] @ T
            order.append(c)
    return M


def face_points(face):
    return np.array(face.poly.exterior.coords[:-1])


def world_points(M, pts2d):
    h = np.c_[pts2d[:, 0], -pts2d[:, 1], np.zeros(len(pts2d)), np.ones(len(pts2d))]
    return (M @ h.T).T[:, :3]


def bounds3d(model, Ms):
    allp = np.vstack([world_points(Ms[f.id], face_points(f)) for f in model.faces])
    return allp.min(axis=0), allp.max(axis=0)


SHIFT_LIMIT = 30.0           # degrees of elevation a shift lens corrects


@dataclass
class Camera:
    yaw: float = -32.0          # degrees, around world Y
    pitch: float = 18.0         # degrees, positive looks from above
    zoom: float = 1.0
    pan_x: float = 0.0          # screen-space pan in pixels
    pan_y: float = 0.0
    fov: float = 16.07                # Nikon Z 85 mm on full frame
    shift: bool = True                # straight verticals (shift lens / two-point perspective)

    def view(self, center, radius):
        """(view matrix, distance, vertical lens shift as tan of the elevation)."""
        dist = radius / math.sin(math.radians(self.fov / 2)) * 1.15
        if self.shift:
            # the sensor stays vertical and the camera is raised instead of tilted, so
            # vertical edges stay parallel; the box is brought back to the centre by
            # shifting the lens (like a tilt-shift lens or "upright" correction).
            # A shift lens only goes so far: above 30 degrees the rest is a normal tilt,
            # otherwise a view from high above stretches the walls absurdly.
            ps = max(-SHIFT_LIMIT, min(SHIFT_LIMIT, self.pitch))
            el = math.tan(math.radians(ps))
            tilt = _rot((1, 0, 0), math.radians(self.pitch - ps))
            V = _trans((0, -dist * el, -dist)) @ tilt @ _rot((0, 1, 0), math.radians(-self.yaw))
            return V @ _trans(-np.asarray(center)), dist, el
        R = _rot((1, 0, 0), math.radians(self.pitch)) @ _rot((0, 1, 0), math.radians(-self.yaw))
        return _trans((0, 0, -dist)) @ R @ _trans(-np.asarray(center)), dist, 0.0


@dataclass
class DrawFace:
    id: int
    H: np.ndarray               # 3x3: die point (x, y, 1) -> screen (homogeneous)
    depth: float
    front: bool                 # printed side visible
    shade: float                # 0..1 light amount


def project(model, t, cam: Camera, width, height, extra_roll=0.0, light=None, strength=0.12, exposure=1.0):
    """Faces ready to draw back to front."""
    Ms = face_transforms(model, t, extra_roll)
    lo, hi = bounds3d(model, Ms)
    center = (lo + hi) / 2
    # radius from the folded box so the zoom does not jump while folding
    flo, fhi = bounds3d(model, face_transforms(model, 1.0, extra_roll))
    radius = max(1e-3, np.linalg.norm(fhi - flo) / 2, np.linalg.norm(hi - lo) / 2 * 0.8)
    V, dist, el = cam.view(center, radius)
    f = min(width, height) / 2 / math.tan(math.radians(cam.fov / 2)) * cam.zoom
    cx, cy = width / 2 + cam.pan_x, height / 2 + cam.pan_y - f * el
    K = np.array([[f, 0, -cx, 0], [0, -f, -cy, 0], [0, 0, -1, 0]])
    L = LIGHT if light is None else np.asarray(light, dtype=float) / np.linalg.norm(light)
    amax = max(fc.area for fc in model.faces)
    eps = radius * 0.004
    out = []
    for fc in model.faces:
        M = Ms[fc.id]
        # smaller flaps count as a hair inside bigger panels, so overlaps draw in the right
        # order; between equal flaps (a full-overlap lid) the one hanging on the front is
        # outside, the ones further round the box go under it. The inset only decides the
        # drawing order - the panel itself is drawn where it really is, otherwise thin
        # strips of the walls' inside would show along the edges.
        inset = eps * (1 - fc.area / amax) + eps * 0.05 * getattr(fc, "depth", 0)
        off = _trans((0, 0, -inset)) if inset > 0 else np.eye(4)
        VM = V @ M @ off
        H = K @ V @ M @ FLAT
        pts = face_points(fc)
        cam_pts = (VM @ np.c_[pts[:, 0], -pts[:, 1], np.zeros(len(pts)), np.ones(len(pts))].T).T[:, :3]
        if (cam_pts[:, 2] > -1e-3).any():
            continue                                    # behind the camera
        n = VM[:3, :3] @ np.array([0, 0, 1.0])
        n /= np.linalg.norm(n)
        front = float(n @ -cam_pts.mean(axis=0)) > 0
        nv = n if front else -n
        shade = exposure * (1.0 - strength * (1.0 - max(0.0, float(nv @ L))))
        d = DrawFace(fc.id, H, float(cam_pts[:, 2].mean()), front, shade)
        d.normal, d.point, d.zs = n, cam_pts.mean(axis=0), cam_pts[:, 2]
        out.append(d)
    if t >= 0.999:
        # a closed box: its inside can never be in front of its outside, so draw every
        # board-side (inside) face first; depth sorting alone fails for long panels
        out = _order([d for d in out if not d.front], eps * 4) + _order([d for d in out if d.front], eps * 4)
    else:
        out = _order(out, eps * 4)
    return Scene(out, _shadows(model, Ms, K @ V, lo[1]), f)


def _order(faces, tol):
    """Back to front. Faces lying in one plane (lid over flaps, glue flap under a wall)
    are drawn as a stack: the layer nearest the camera last."""
    clusters = []
    for d in faces:
        for cl in clusters:
            r = cl[0]
            if abs(float(r.normal @ d.normal)) > 0.995 and abs(float(r.normal @ (d.point - r.point))) < tol:
                cl.append(d)
                break
        else:
            clusters.append([d])
    out = []
    for cl in sorted(clusters, key=lambda c: float(np.mean(np.concatenate([d.zs for d in c])))):
        n = cl[0].normal
        if float(n @ -cl[0].point) < 0:
            n = -n                                   # normal towards the camera
        out.extend(sorted(cl, key=lambda d: float(n @ d.point)))
    return out


@dataclass
class Scene:
    faces: list
    shadows: list               # screen polygons of the box squashed onto the floor
    focal: float


def _shadows(model, Ms, KV, ground_y):
    out = []
    for fc in model.faces:
        w = world_points(Ms[fc.id], face_points(fc))
        w[:, 1] = ground_y
        h = (KV @ np.c_[w, np.ones(len(w))].T).T
        if (h[:, 2] <= 1e-6).any():
            continue
        out.append(h[:, :2] / h[:, 2:3])
    return out
