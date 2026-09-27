"""Optional geometric waypoint guidance, separate from safety certification.

This house experiment supports one rectangular forbidden region. Guidance uses
its configured geometry to supply navigation targets; it never approves a
velocity or replaces the runtime monitor, reachability, or LiDAR checks.
"""
import heapq
import math


class RectangleGuidance:
    def __init__(self,start,goal,region,footprint,sides=('top','bottom')):
        if region['kind']!='rectangle':
            raise ValueError('House waypoint guidance requires a rectangular region')
        if not all(math.isfinite(v) for v in [*start[:2],*goal,footprint]):
            raise ValueError('Nonfinite waypoint geometry')
        if footprint<0:
            raise ValueError('Negative footprint')
        self.goal=tuple(goal)
        # Keep routing margins explicit. The runtime filter independently checks
        # uncertainty, braking assumptions and sampled physical obstacles.
        clearance=footprint+.05
        corners=footprint+.20
        self.box=(region['xmin']-clearance,region['xmax']+clearance,
                  region['ymin']-clearance,region['ymax']+clearance)
        left,right=region['xmin']-corners,region['xmax']+corners
        bottom,top=region['ymin']-corners,region['ymax']+corners
        # Upper corners precede lower corners for a stable symmetric tie.
        if not set(sides)<={'top','bottom'} or not sides:
            raise ValueError('Guidance sides must be top and/or bottom')
        # Restricting the detour side is scenario configuration: RQ3 uses the
        # side already driven in development runs (free space verified there).
        vertices=[tuple(start[:2]),self.goal,
                  (left,top) if 'top' in sides else None,(right,top) if 'top' in sides else None,
                  (left,bottom) if 'bottom' in sides else None,(right,bottom) if 'bottom' in sides else None]
        costs={0:0.}; previous={}; pending=[(0.,0)]
        while pending:
            cost,index=heapq.heappop(pending)
            if cost>costs[index]+1e-9:
                continue
            if index==1:
                break
            for other,point in enumerate(vertices):
                if point is None or other==index or not self.clear(vertices[index],point):
                    continue
                candidate=cost+math.dist(vertices[index],point)
                if candidate<costs.get(other,math.inf)-1e-9:
                    costs[other]=candidate; previous[other]=index
                    heapq.heappush(pending,(candidate,other))
        if 1 not in costs:
            raise ValueError('No waypoint route with the configured clearance')
        indices=[1]
        while indices[-1]!=0:
            indices.append(previous[indices[-1]])
        self.targets=[vertices[i] for i in reversed(indices[:-1])]
        self.initial_targets=list(self.targets)

    def clear(self,a,b):
        """Separating-axis segment/box test; reference oracle uses other code."""
        left,right,bottom,top=self.box
        dx,dy=(b[0]-a[0])/2,(b[1]-a[1])/2
        cx,cy=(a[0]+b[0]-left-right)/2,(a[1]+b[1]-bottom-top)/2
        rx,ry=(right-left)/2,(top-bottom)/2
        return (abs(cx)>rx+abs(dx)+1e-9 or abs(cy)>ry+abs(dy)+1e-9 or
                abs(dx*cy-dy*cx)>rx*abs(dy)+ry*abs(dx)+1e-9)

    def target(self,pose):
        # Prune only when the next segment is clear. This avoids requiring an
        # exact stop at a corner while preventing a shortcut across the region.
        while len(self.targets)>1 and self.clear(pose[:2],self.targets[1]):
            self.targets.pop(0)
        return self.targets[0]
