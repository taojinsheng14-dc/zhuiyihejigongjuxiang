"""Read-only map coverage planner; no game input."""
from collections import deque
import heapq


class CoverageRoute:
    def __init__(self,tilemap,start,spacing=8):
        self.tilemap=tilemap;self.goal=None;self.visited=set();self.deferred={};self.laps=0
        reachable=self.distances(tuple(start));bins={}
        self.clearance=wall_clearance(tilemap,set(reachable))
        for p in reachable:
            key=(p[0]//spacing,p[1]//spacing);center=((key[0]+.5)*spacing,(key[1]+.5)*spacing)
            score=(max(0,8-self.clearance[p]),sum((p[i]-center[i])**2 for i in (0,1)))
            if key not in bins or score<bins[key][0]:bins[key]=(score,p)
        self.points={row[1] for row in bins.values()}
        # Wide rooms need more lanes; narrow corridors keep sparse center points.
        room_bins={}
        for p in reachable:
            if self.clearance[p]<8:continue
            key=(p[0]//12,p[1]//12);center=((key[0]+.5)*12,(key[1]+.5)*12)
            score=sum((p[i]-center[i])**2 for i in (0,1))
            if key not in room_bins or score<room_bins[key][0]:room_bins[key]=(score,p)
        self.points.update(row[1] for row in room_bins.values())
        if not self.points:raise RuntimeError('地牢没有已确认可达路线')

    def navigation_map(self):
        return CenterPathMap(self.tilemap,self.clearance)

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
        return {'goal':self.goal,'visited':len(self.visited),'total':len(self.points),'laps':self.laps,'route_style':'corridor_center','min_waypoint_clearance':min(self.clearance[p] for p in self.points)}


def wall_clearance(tilemap,reachable):
    distance={};queue=deque()
    for x,y in reachable:
        if any(not tilemap.free((x+dx,y+dy)) for dx,dy in ((1,0),(-1,0),(0,1),(0,-1))):
            distance[(x,y)]=1;queue.append((x,y))
    while queue:
        x,y=queue.popleft()
        for p in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
            if p in reachable and p not in distance:distance[p]=distance[(x,y)]+1;queue.append(p)
    return distance


class CenterPathMap:
    """Same passability, with wall-distance and turn costs for actual movement."""
    def __init__(self,tilemap,clearance):self.base=tilemap;self.clearance=clearance
    def __getattr__(self,name):return getattr(self.base,name)
    def free(self,p):return self.base.free(p)
    def path(self,start,goal,blocked=()):
        start,goal=tuple(start),tuple(goal);blocked=set(map(tuple,blocked))-{start}
        if not self.free(start) or not self.free(goal) or goal in blocked:raise RuntimeError('巡逻目标当前没有可走路径')
        def heuristic(p):
            a,b=abs(p[0]-goal[0]),abs(p[1]-goal[1]);return 100*max(a,b)+41*min(a,b)
        first=(start,None);cost={first:0};parents={first:None};heap=[(heuristic(start),0,0,first)];sequence=0;found=None
        while heap:
            _,g,_,state=heapq.heappop(heap)
            if cost.get(state)!=g:continue
            point,direction=state
            if point==goal:found=state;break
            x,y=point
            for dx,dy in ((0,-1),(1,0),(0,1),(-1,0),(-1,-1),(1,-1),(1,1),(-1,1)):
                nxt=(x+dx,y+dy)
                if nxt in blocked or not self.free(nxt):continue
                if dx and dy and any(p in blocked or not self.free(p) for p in ((x+dx,y),(x,y+dy))):continue
                clearance=self.clearance.get(nxt,1)
                penalty=(220,100,45,15)[clearance-1] if clearance<=4 else 0
                ng=g+(141 if dx and dy else 100)+penalty+(12 if direction is not None and direction!=(dx,dy) else 0)
                new=(nxt,(dx,dy))
                if ng>=cost.get(new,float('inf')):continue
                cost[new]=ng;parents[new]=state;sequence+=1
                heapq.heappush(heap,(ng+heuristic(nxt),ng,sequence,new))
        if found is None:raise RuntimeError('巡逻目标当前没有可走路径')
        path=[]
        while found is not None:path.append(found[0]);found=parents[found]
        return path[::-1]


class PatrolStalled(RuntimeError):
    """A bounded movement budget was exhausted; callers decide its scope."""
    pass


class PatrolObstruction:
    """Remember failed first steps across goals; never infer the game's cause."""
    def __init__(self):self.until={};self.repeats={};self.failures=0
    def blocked(self,now):
        self.until={p:t for p,t in self.until.items() if t>now}
        return set(self.until)
    def observe(self,result,now):
        if tuple(result.get('from',()))!=tuple(result.get('to',())):
            self.failures=0;self.repeats.clear();return
        if result.get('arrived'):return
        step=result.get('planned_step')
        if step is None:return
        step=tuple(step);self.failures+=1;self.repeats[step]=self.repeats.get(step,0)+1
        if self.repeats[step]>=2:self.until[step]=now+20
        if self.failures>=12:raise PatrolStalled('巡逻多方向有限尝试仍无位移，保留现场停止；未自动重登')
