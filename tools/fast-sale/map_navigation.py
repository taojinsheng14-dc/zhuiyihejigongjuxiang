"""Local classic 12-byte Mir map cells; no input or process writes."""
from pathlib import Path
import struct
from collections import deque
from toolbox_config import game_directory

MAP_DIRECTORY=game_directory()/'map'
_cache={}

class TileMap:
    def __init__(self,data,name=''):
        self.width,self.height=struct.unpack_from('<HH',data)
        if len(data)!=52+self.width*self.height*12:
            raise RuntimeError('地图不是已验证的12字节格子格式')
        self.data=data;self.name=name

    def free(self,xy):
        x,y=xy
        if not(0<=x<self.width and 0<=y<self.height):return False
        back,_,front=struct.unpack_from('<HHH',self.data,52+(x*self.height+y)*12)
        return not ((back|front)&0x8000)

    def path(self,start,goal,blocked=()):
        start,goal=tuple(start),tuple(goal);blocked=set(blocked)-{start}
        if not self.free(start) or not self.free(goal) or goal in blocked:
            raise RuntimeError('起点或目标不可用：起点%s（可走=%s），目标%s（可走=%s，占用=%s）' %
                               (start,self.free(start),goal,self.free(goal),goal in blocked))
        queue=deque([start]);parents={start:None}
        while queue:
            at=queue.popleft()
            if at==goal:break
            for dx,dy in ((0,1),(0,-1),(1,0),(-1,0),(-1,1),(1,1),(-1,-1),(1,-1)):
                nxt=(at[0]+dx,at[1]+dy)
                if nxt in parents or nxt in blocked or not self.free(nxt):continue
                parents[nxt]=at;queue.append(nxt)
        if goal not in parents:raise RuntimeError('地图上没有可走路径')
        result=[goal]
        while parents[result[-1]] is not None:result.append(parents[result[-1]])
        return result[::-1]

    def run_path(self,start,goals,blocked=()):
        start=tuple(start);goals=set(map(tuple,goals));blocked=set(blocked)-{start}
        queue=deque([start]);parents={start:None};found=None
        while queue:
            at=queue.popleft()
            if at in goals:found=at;break
            for dx,dy in ((0,-1),(-1,-1),(1,-1),(-1,0),(1,0),(0,1),(-1,1),(1,1)):
                middle=(at[0]+dx,at[1]+dy);nxt=(at[0]+2*dx,at[1]+2*dy)
                if nxt in parents or nxt in blocked or not self.free(middle) or not self.free(nxt):continue
                parents[nxt]=at;queue.append(nxt)
        if found is None:raise RuntimeError('附近没有仅用右键跑动的可用路线')
        result=[found]
        while parents[result[-1]] is not None:result.append(parents[result[-1]])
        return result[::-1]

def matching_map_file(header,directory=None):
    # Header identity is useful even when the map's tile encoding is unknown.
    # It never grants permission to pathfind through an unsupported map format.
    if len(header)!=52:raise RuntimeError('地图头长度不符')
    directory=Path(directory or MAP_DIRECTORY)
    matches=[]
    for path in directory.glob('*.map'):
        with path.open('rb') as stream:
            if stream.read(52)==header:matches.append(path)
    if len(matches)!=1:raise RuntimeError('无法唯一匹配当前地图文件，未执行移动')
    return matches[0]


def load_matching_map(header,directory=None):
    directory=Path(directory or MAP_DIRECTORY)
    key=(str(directory),header)
    if key in _cache:return _cache[key]
    path=matching_map_file(header,directory)
    result=TileMap(path.read_bytes(),path.name)
    _cache[key]=result
    return result


def npc_approach_step(tilemap,current,npc_xy,blocked=()):
    """Choose at most two verified tiles toward a standing position near an NPC."""
    current=tuple(current);npc_xy=tuple(npc_xy);blocked=set(map(tuple,blocked));blocked.add(npc_xy)
    if max(abs(current[i]-npc_xy[i]) for i in (0,1))>30:
        raise RuntimeError('NPC距离超出已加载场景的短距靠近范围')
    goals=[]
    for x in range(npc_xy[0]-4,npc_xy[0]+5):
        for y in range(npc_xy[1]-4,npc_xy[1]+5):
            goal=(x,y);distance=max(abs(x-npc_xy[0]),abs(y-npc_xy[1]))
            if 2<=distance<=4 and goal!=current and goal not in blocked and tilemap.free(goal):goals.append(goal)
    if not goals:raise RuntimeError('NPC附近没有已核对的可走靠近路线')
    try:path=tilemap.run_path(current,goals,blocked)
    except RuntimeError:raise RuntimeError('NPC附近没有已核对的可走靠近路线')
    if len(path)<2:raise RuntimeError('NPC附近没有可用的右键靠近步点')
    return tuple(path[1])


def veteran_run_path(tilemap,start,goals,blocked=(),target=(320,320),passable_middle=()):
    """Run toward the NPC without crossing either axis or moving away on an axis."""
    start=tuple(start);target=tuple(target)
    class ApproachMap:
        def free(self,xy):
            return all(min(start[i],target[i])<=xy[i]<=max(start[i],target[i]) for i in (0,1)) and tilemap.free(xy)
    # BFS restricted to monotone progress, including both tiles of each run.
    allowed=ApproachMap();goals=set(map(tuple,goals));blocked=set(map(tuple,blocked))|{target}
    middle_blocked=blocked-set(map(tuple,passable_middle));middle_blocked.add(target)
    queue=deque([start]);parents={start:None};found=None
    while queue:
        at=queue.popleft()
        if at in goals:found=at;break
        for dx,dy in ((0,-1),(-1,-1),(1,-1),(-1,0),(1,0),(0,1),(-1,1),(1,1)):
            middle=(at[0]+dx,at[1]+dy);nxt=(at[0]+2*dx,at[1]+2*dy)
            if any(abs(nxt[i]-target[i])>abs(at[i]-target[i]) for i in (0,1)):continue
            if nxt in parents or nxt in blocked or middle in middle_blocked or not allowed.free(middle) or not allowed.free(nxt):continue
            parents[nxt]=at;queue.append(nxt)
    if found is None:raise RuntimeError('老兵同侧没有不越界的右键路线，停止移动')
    result=[found]
    while parents[result[-1]] is not None:result.append(parents[result[-1]])
    return result[::-1]


def veteran_run_batch(path,target=(320,320)):
    """At most two collinear runs when far away; replan near the NPC."""
    if len(path)<2:return []
    count=1
    if len(path)>2 and max(abs(path[0][i]-target[i]) for i in (0,1))>8:
        if tuple(path[1][i]-path[0][i] for i in (0,1))==tuple(path[2][i]-path[1][i] for i in (0,1)):count=2
    return path[1:count+1]


def validate_veteran_landing(tilemap,start,after,runs,origin=None,target=(320,320),tolerance=2):
    """Accept bounded observed drift; these NPC-axis checks are not a safe-zone map."""
    start=tuple(start);after=tuple(after);origin=tuple(origin or start);target=tuple(target)
    for i in (0,1):
        if ((origin[i]>=target[i] and after[i]<target[i]) or
                (origin[i]<=target[i] and after[i]>target[i])):
            raise RuntimeError('老兵跑动越过目标坐标轴，停止继续移动：起点%s，落点%s，目标%s' % (start,after,target))
    if not tilemap.free(after):raise RuntimeError('老兵跑动落点不是已核对可走格：'+str(after))
    if max(abs(after[i]-start[i]) for i in (0,1))>2*runs+tolerance:
        raise RuntimeError('老兵跑动位移异常：起点%s，落点%s，已发送%s次跑动' % (start,after,runs))
    if any(not min(origin[i],target[i])-tolerance<=after[i]<=max(origin[i],target[i])+tolerance for i in (0,1)):
        raise RuntimeError('老兵跑动偏移超过本次靠近容差：原点%s，落点%s' % (origin,after))
    if any(abs(after[i]-target[i])>abs(start[i]-target[i])+tolerance for i in (0,1)):
        raise RuntimeError('老兵跑动偏移超过单批容差：起点%s，落点%s' % (start,after))
    drift=any(not min(start[i],target[i])<=after[i]<=max(start[i],target[i]) for i in (0,1))
    return {'replan':drift,'origin':origin,'target':target,'tolerance':tolerance}
