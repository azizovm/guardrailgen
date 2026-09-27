"""Independent geometric reference: no compiler or generated monitor imports.

Actual trajectory checking uses straight segments between ground-truth samples.
This is an empirical sampled-trajectory oracle, not a continuous dynamics proof.
"""
import math


def _point_segment(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    norm = dx*dx + dy*dy
    t = 0.0 if norm == 0 else max(0.0, min(1.0, ((p[0]-a[0])*dx + (p[1]-a[1])*dy)/norm))
    return math.hypot(p[0]-a[0]-t*dx, p[1]-a[1]-t*dy)


def _intersects_rectangle(a, b, r):
    # Slab clipping, independently implemented from the interval monitor.
    enter, leave = 0.0, 1.0
    for dim, low, high in [(0, r['xmin'], r['xmax']), (1, r['ymin'], r['ymax'])]:
        delta = b[dim]-a[dim]
        if delta == 0:
            if not low <= a[dim] <= high:
                return False
        else:
            t1, t2 = (low-a[dim])/delta, (high-a[dim])/delta
            enter, leave = max(enter, min(t1, t2)), min(leave, max(t1, t2))
            if enter > leave:
                return False
    return True


def touches_region(a, b, region, footprint):
    if region['kind'] == 'circle':
        return _point_segment((region['cx'], region['cy']), a, b) <= footprint + region['radius']
    if _intersects_rectangle(a, b, region):
        return True
    corners = [(region['xmin'], region['ymin']), (region['xmin'], region['ymax']),
               (region['xmax'], region['ymax']), (region['xmax'], region['ymin'])]
    distances = [_point_segment(c, a, b) for c in corners]
    for p in (a, b):
        distances.append(math.hypot(max(region['xmin']-p[0], 0, p[0]-region['xmax']),
                                    max(region['ymin']-p[1], 0, p[1]-region['ymax'])))
    return min(distances) <= footprint


def nominal_rule_safe(pose, plan, region, footprint, dt=0.1):
    """Fine-step nominal replay only; does not test physical obstacles or backup."""
    x, y, yaw = pose
    if touches_region((x,y), (x,y), region, footprint):
        return False
    for speed, turn in plan:
        for _ in range(10):
            h = dt/10
            if abs(turn) < 1e-12:
                nx, ny = x + speed*h*math.cos(yaw), y + speed*h*math.sin(yaw)
            else:
                nx = x + speed/turn*(math.sin(yaw+turn*h)-math.sin(yaw))
                ny = y - speed/turn*(math.cos(yaw+turn*h)-math.cos(yaw))
            if touches_region((x,y), (nx,ny), region, footprint):
                return False
            x, y, yaw = nx, ny, yaw+turn*h
    return True


def nominal_speed_rule_safe(pose, plan, region, footprint, limit, dt=0.1):
    """Nominal replay for 'inside region, |commanded v| <= limit' (rule-only)."""
    x, y, yaw = pose
    for speed, turn in plan:
        for _ in range(10):
            h = dt/10
            if abs(turn) < 1e-12:
                nx, ny = x + speed*h*math.cos(yaw), y + speed*h*math.sin(yaw)
            else:
                nx = x + speed/turn*(math.sin(yaw+turn*h)-math.sin(yaw))
                ny = y - speed/turn*(math.cos(yaw+turn*h)-math.cos(yaw))
            if abs(speed) > limit and touches_region((x,y), (nx,ny), region, footprint):
                return False
            x, y, yaw = nx, ny, yaw+turn*h
    return True
