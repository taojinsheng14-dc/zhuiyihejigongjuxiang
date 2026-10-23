"""Read saved samples only. Opening/closing this panel never controls a game."""
import json,time,sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
ROOT=Path(__file__).resolve().parents[2]


def render_combat(live,now=None):
    now=time.time() if now is None else now
    stats=live.get('combat') or {}
    if not live.get('ok') or not 0<=now-live.get('observed_epoch',0)<=3:
        return '等待有效游戏采样；不会回填未观测时段'
    if not stats:return '后台尚未接入经验统计'
    if not stats.get('available'):return '经验统计暂不可用：'+str(stats.get('error','等待字段核对'))
    main=stats.get('main') or {};hero=stats.get('hero') or {}
    rows=[stats.get('character','角色')+' · PID '+str(live.get('game_pid','—')),
          '人物等级 {}　英雄等级 {}'.format(main.get('level','—'),hero.get('level','未加载')),
          '人物当前经验 {:,}'.format(main.get('experience',0)),
          '累计经验净增 {:,}'.format(stats.get('main_exp_gain',0)),
          '每小时经验 {:,}'.format(stats.get('experience_per_hour',0)),
          '经验增长次数（击杀参考）：{}'.format(stats.get('growth_events',0)),
          '每小时增长次数：{}'.format(stats.get('growth_events_per_hour',0)),
          '英雄经验净增 {:,}（仅核对，不重复计数）'.format(stats.get('hero_exp_gain',0)),
          '有效观测 {:.1f} 分钟'.format(stats.get('observed_seconds',0)/60),
          '采样中附近有玩家占比 {}%'.format(stats.get('nearby_player_observation_percent',0)),
          '升级待核对段 {}　采样间断 {}'.format(stats.get('unknown_upgrade_transitions',0),stats.get('sampling_gaps',0))]
    if stats.get('last_growth_epoch'):rows.append('最近经验增长：'+time.strftime('%H:%M:%S',time.localtime(stats['last_growth_epoch'])))
    rows.append('从接入时开始统计；增长次数可能漏采，不是精确击杀数。')
    if stats.get('baseline_reason'):rows.append(stats['baseline_reason'])
    return '\n\n'.join(rows)


class CombatPanel(tk.Tk):
    def __init__(self):
        super().__init__();self.title('双号 · 经验与击杀参考统计');self.geometry('1000x650')
        ttk.Label(self,text='独立只读统计面板；关闭此窗口不停止任何挂机。',padding=12).pack(anchor='w')
        body=ttk.Frame(self);body.pack(fill='both',expand=True)
        self.values=[]
        for index in (1,2):
            panel=ttk.LabelFrame(body,text='账号'+str(index),padding=16);panel.pack(side='left',fill='both',expand=True,padx=10,pady=10)
            value=tk.StringVar(value='等待读取统计');self.values.append(value)
            ttk.Label(panel,textvariable=value,justify='left',wraplength=440,font=('Microsoft YaHei UI',11)).pack(anchor='nw')
        self.after(100,self.refresh)
    def refresh(self):
        for value,root in zip(self.values,[ROOT,ROOT/'instances'/'2']):
            try:
                live=json.loads((root/'outputs'/'实时监控.json').read_text(encoding='utf8'))
                value.set(render_combat(live))
            except (OSError,ValueError,TypeError):value.set('等待本号后台采样；不操作游戏')
        self.after(500,self.refresh)

if __name__=='__main__':CombatPanel().mainloop()
