import unittest
from analyze_route import summarize

class RouteReferenceTests(unittest.TestCase):
    def test_selling_and_closing_are_distinct_steps(self):
        def position(seconds,merchant,sell,bag,map_id='town',xy=(320,320)):
            return dict(kind='position',seconds=seconds,merchant=merchant,sell=sell,bag=bag,map_id=map_id,xy=xy)
        events=[position(0,False,False,False),
                dict(kind='mouse_down',seconds=.2,button='left',client=[100,100]),
                position(.4,True,False,False),position(.7,True,True,True),
                position(1,True,False,True),position(1.2,False,False,False),
                position(2,False,False,False,'island',(140,330))]
        result=summarize(events)
        changes=result['changes']
        self.assertEqual([x['open'] for x in changes if x.get('window')=='sell'],[True,False])
        self.assertEqual([x['open'] for x in changes if x.get('window')=='merchant'],[True,False])
        self.assertEqual(changes[-1]['type'],'map_change')
        self.assertTrue(result['reference_only'])

    def test_no_click_is_invented_when_closed_by_keyboard(self):
        events=[dict(kind='position',seconds=0,map_id='shop',xy=[5,15],merchant=True,sell=True,bag=True),
                dict(kind='position',seconds=5,map_id='shop',xy=[5,15],merchant=False,sell=False,bag=False)]
        changes=summarize(events)['changes']
        self.assertEqual(len(changes),3)
        self.assertTrue(all(x['preceding_click'] is None for x in changes))

    def test_map_transition_waits_for_actual_landing_coordinates(self):
        events=[dict(kind='position',seconds=t,map_id=m,xy=xy) for t,m,xy in
                [(0,'shop',[5,16]),(.1,'town',[4,16]),(.2,'town',[327,315]),
                 (.3,'town',[327,315]),(.4,'town',[327,315])]]
        change=summarize(events)['changes'][0]
        self.assertEqual(change['to'],[327,315])
        self.assertTrue(change['stable_landing'])

if __name__=='__main__':unittest.main()
