"""Solve a camera from a reference image: find the location, rotation and lens that put known 3D
points where they appear in the image.

Usage:
  python3 solve_camera.py points.json [--width 1920] [--lens 35] [--seed 1]

points.json:
  {
    "aspect": 2.39,                          # image width / height
    "points": [                              # at least 4; 6 or more is better
      {"name": "tower base corner", "world": [25, 0, 0], "image": [0.46, 0.97]},
      {"name": "car center", "world": [28, 17, 169], "image": [0.27, 0.37], "weight": 2}
    ],
    "lens": [18, 80],                        # optional: search range in mm, or a number to fix it
    "location_bounds": [[-100, -100, 0], [100, 100, 300]]   # optional search box
  }

"image" is a frame fraction: x from the left edge, y from the top edge. Measure it in the reference
frame (pixel / image width, pixel / image height). "weight" (default 1) makes a point count more.

Prints the camera as Blender values (location, rotation_euler in XYZ order, lens; 36 mm sensor
width) and the error for each point in pixels. Runs with any Python 3; no Blender needed.
A large error means the scene's assumptions are wrong, not just the camera: see SKILL.md.
"""

import argparse
import json
import math
import random
import sys

SENSOR_WIDTH = 36.0


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def normalize(a):
    length = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / length, a[1] / length, a[2] / length)


def basis(yaw, pitch, roll):
    """Camera axes from a heading (yaw, from +X toward +Y), pitch (up positive) and roll."""
    forward = (math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))
    right0 = normalize(cross(forward, (0.0, 0.0, 1.0)))
    up0 = cross(right0, forward)
    c, s = math.cos(roll), math.sin(roll)
    right = tuple(right0[i] * c + up0[i] * s for i in range(3))
    up = tuple(up0[i] * c - right0[i] * s for i in range(3))
    return forward, right, up


def project(point, cam, aspect):
    """Frame fraction (x from left, y from top) of a world point, or None if behind the camera."""
    forward, right, up = basis(cam["yaw"], cam["pitch"], cam["roll"])
    d = sub(point, cam["loc"])
    depth = dot(d, forward)
    if depth <= 1e-3:
        return None
    tan_h = SENSOR_WIDTH / 2 / cam["lens"]
    tan_v = tan_h / aspect
    return (0.5 + 0.5 * dot(d, right) / depth / tan_h, 0.5 - 0.5 * dot(d, up) / depth / tan_v)


def error(cam, points, aspect):
    total, weight_sum = 0.0, 0.0
    for p in points:
        q = project(p["world"], cam, aspect)
        w = p.get("weight", 1.0)
        weight_sum += w
        if q is None:
            total += w * 10.0                     # behind the camera: heavily penalized
            continue
        dx, dy = q[0] - p["image"][0], (q[1] - p["image"][1]) / aspect   # both in image-width units
        total += w * (dx * dx + dy * dy)
    return total / weight_sum


def look_at_angles(loc, target):
    d = sub(target, loc)
    return math.atan2(d[1], d[0]), math.atan2(d[2], math.hypot(d[0], d[1]))


def blender_euler(cam):
    """Blender rotation_euler (XYZ) for a camera with these axes (it looks down its local -Z)."""
    forward, right, up = basis(cam["yaw"], cam["pitch"], cam["roll"])
    back = (-forward[0], -forward[1], -forward[2])
    # Rotation matrix columns are the camera's local X (right), Y (up) and Z (back) axes.
    r00, r10, r20 = right
    r21, r22 = up[2], back[2]
    y = math.asin(max(-1.0, min(1.0, -r20)))
    x = math.atan2(r21, r22)
    z = math.atan2(r10, r00)
    return (x, y, z)


def solve(spec, fixed_lens=None, seed=1, samples=40000, refine=12):
    points = spec["points"]
    if len(points) < 4:
        sys.exit("need at least 4 points")
    aspect = float(spec.get("aspect", 16 / 9))
    lens_spec = fixed_lens if fixed_lens is not None else spec.get("lens", [16, 120])
    lens_range = (lens_spec, lens_spec) if isinstance(lens_spec, (int, float)) else tuple(lens_spec)
    worlds = [p["world"] for p in points]
    center = tuple(sum(w[i] for w in worlds) / len(worlds) for i in range(3))
    extent = max(max(w[i] for w in worlds) - min(w[i] for w in worlds) for i in range(3)) or 1.0
    lo, hi = spec.get("location_bounds", [[center[i] - 4 * extent for i in range(3)],
                                          [center[i] + 4 * extent for i in range(3)]])
    rng = random.Random(seed)

    def clamp_cam(cam):
        cam["loc"] = tuple(min(max(cam["loc"][i], lo[i]), hi[i]) for i in range(3))
        cam["lens"] = min(max(cam["lens"], lens_range[0]), lens_range[1])
        cam["pitch"] = min(max(cam["pitch"], -math.pi / 2 + 1e-3), math.pi / 2 - 1e-3)
        return cam

    # Random starts: sample a location and aim roughly at the points, with some slop
    starts = []
    for _ in range(samples):
        loc = tuple(rng.uniform(lo[i], hi[i]) for i in range(3))
        yaw, pitch = look_at_angles(loc, center)
        cam = clamp_cam({"loc": loc, "yaw": yaw + rng.gauss(0, 0.35), "pitch": pitch + rng.gauss(0, 0.35),
                         "roll": rng.gauss(0, 0.3), "lens": math.exp(rng.uniform(*map(math.log, lens_range)))})
        starts.append((error(cam, points, aspect), cam))
    starts.sort(key=lambda t: t[0])

    # Polish the best starts with Levenberg-Marquardt least squares and keep the best result
    solve_lens = lens_range[0] != lens_range[1]
    best = None
    for e, cam in starts[:refine]:
        cam = least_squares(cam, points, aspect, solve_lens, clamp_cam)
        e = error(cam, points, aspect)
        if best is None or e < best[0]:
            best = (e, cam)
    return best, aspect


def _pack(cam, solve_lens):
    x = list(cam["loc"]) + [cam["yaw"], cam["pitch"], cam["roll"]]
    return x + [cam["lens"]] if solve_lens else x


def _unpack(x, lens):
    return {"loc": tuple(x[:3]), "yaw": x[3], "pitch": x[4], "roll": x[5], "lens": x[6] if len(x) > 6 else lens}


def _residuals(cam, points, aspect):
    out = []
    for p in points:
        w = math.sqrt(p.get("weight", 1.0))
        q = project(p["world"], cam, aspect)
        if q is None:
            out += [w * 3.0, w * 3.0]
        else:
            out += [w * (q[0] - p["image"][0]), w * (q[1] - p["image"][1]) / aspect]
    return out


def _solve_linear(a, b):
    """Gaussian elimination with partial pivoting for a small dense system."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[piv][col]) < 1e-15:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def least_squares(cam, points, aspect, solve_lens, clamp_cam, iterations=60):
    x = _pack(cam, solve_lens)
    lens = cam["lens"]
    lam = 1e-3
    res = _residuals(cam, points, aspect)
    cost = sum(r * r for r in res)
    for _ in range(iterations):
        # numerical Jacobian
        jac = []
        for k in range(len(x)):
            h = 1e-6 * max(1.0, abs(x[k]))
            xk = x[:]
            xk[k] += h
            rk = _residuals(_unpack(xk, lens), points, aspect)
            jac.append([(rk[i] - res[i]) / h for i in range(len(res))])
        jtj = [[sum(jac[a][i] * jac[b][i] for i in range(len(res))) for b in range(len(x))] for a in range(len(x))]
        jtr = [sum(jac[a][i] * res[i] for i in range(len(res))) for a in range(len(x))]
        improved = False
        for _ in range(8):
            damped = [[jtj[a][b] + (lam * jtj[a][a] if a == b else 0.0) for b in range(len(x))] for a in range(len(x))]
            step = _solve_linear(damped, [-v for v in jtr])
            if step is None:
                lam *= 10
                continue
            trial = clamp_cam(_unpack([x[k] + step[k] for k in range(len(x))], lens))
            tres = _residuals(trial, points, aspect)
            tcost = sum(r * r for r in tres)
            if tcost < cost:
                x, res, cost, lam, improved = _pack(trial, solve_lens), tres, tcost, lam * 0.3, True
                break
            lam *= 10
        if not improved or cost < 1e-14:
            break
    return _unpack(x, lens)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("points")
    parser.add_argument("--width", type=int, default=1920, help="image width in pixels, for reporting errors")
    parser.add_argument("--lens", type=float, help="fix the focal length (mm) instead of solving for it")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    with open(args.points) as f:
        spec = json.load(f)
    (err, cam), aspect = solve(spec, args.lens, args.seed)

    rms_px = math.sqrt(err) * args.width
    print(f"RMS error: {rms_px:.1f} px at {args.width} px wide ({math.sqrt(err) * 100:.2f}% of the width)")
    print(f"{'point':28} {'measured':>14} {'solved':>14} {'error px':>9}")
    for p in spec["points"]:
        q = project(p["world"], cam, aspect)
        if q is None:
            print(f"{p.get('name', '?')[:28]:28} {'':>14} {'behind camera':>14}")
            continue
        d = math.hypot(q[0] - p["image"][0], (q[1] - p["image"][1]) / aspect) * args.width
        print(f"{p.get('name', '?')[:28]:28} ({p['image'][0]:.3f}, {p['image'][1]:.3f}) "
              f"({q[0]:.3f}, {q[1]:.3f}) {d:9.1f}")
    rx, ry, rz = blender_euler(cam)
    print("\nBlender camera:")
    print(f"cam.location = ({cam['loc'][0]:.3f}, {cam['loc'][1]:.3f}, {cam['loc'][2]:.3f})")
    print(f"cam.rotation_euler = ({rx:.4f}, {ry:.4f}, {rz:.4f})")
    print(f"cam.data.lens = {cam['lens']:.1f}")
    print(f"# render aspect {aspect:.3f}: e.g. resolution {args.width} x {round(args.width / aspect)}")
    if math.sqrt(err) > 0.02:
        print("\nError is over 2% of the frame width: check the measurements, then question the scene "
              "(scale, speed, where objects really are) before the camera. See SKILL.md.")


if __name__ == "__main__":
    main()
