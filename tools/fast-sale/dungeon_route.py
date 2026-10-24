"""Read-only map coverage planner; no game input."""
from collections import deque


class CoverageRoute:
    def __init__(self,tilemap,start,spacing=8):
        self.tilemap=tilemap;self.goal=None;self.visited=set();self.deferred={};self.laps=0
        reachable=self.distances(tuple(start));bins={}
        for p in reachable:
            key=(p[0]//spacing,p[1]//spacing);center=((key[0]+.5)*spacing,(key[1]+.5)*spacing)
            score=sum((p[i]-center[i])**2 for i in (0,1))
            if key not in bins or score<bins[key][0]:bins[key]=(score,p)
        self.points={row[1] for row in bins.values()}
        if not self.points:raise RuntimeError('地牢没有已确认可达路线')

    def distances(self,start):
        queue=deque([start]);dist={start:0}
        while queue:
            x,y=queue.popleft()
            for p in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                if p not in dist and self.tilemap.free(p):dist[p]=dist[(x,y)]+1;queue.append(p)
        return dist

    def next_goal(self,position,now):
        position=tuple(position)
        self.visited.update(p for p in self.points if max(abs(p[i]-position[i]) for i in (0,1))<=3)
        if self.goal in self.visited:self.goal=None
        if self.goal is not None:return self.goal
        if self.points<=self.visited:self.visited.clear();self.laps+=1
        choices=self.points-self.visited
        distances=self.distances(position)
        available=[p for p in choices if p in distances and self.deferred.get(p,0)<=now]
        if not available:return None
        self.goal=min(available,key=lambda p:(distances[p],p));return self.goal

    def defer_goal(self,now):
        if self.goal is not None:self.deferred[self.goal]=now+20
        self.goal=None

    def snapshot(self):
        return {'goal':self.goal,'visited':len(self.visited),'total':len(self.points),'laps':self.laps}
