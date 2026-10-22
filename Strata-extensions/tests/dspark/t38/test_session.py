import itertools,json,os,pathlib,subprocess,unittest
from fractions import Fraction
import reference as Q
EXE=pathlib.Path(os.environ.get('T38_EXE','missing-t38-fixture.exe'))
def invoke(*args,ok=True):
    p=subprocess.run([str(EXE),*map(str,args)],capture_output=True,text=True,encoding='utf-8')
    if ok:
        if p.returncode:raise AssertionError(p.stderr)
        return json.loads(p.stdout)
    if p.returncode==0:raise AssertionError('negative accepted')
class SessionTests(unittest.TestCase):
    def test_exact_distribution_identity(self):
        for p,q in [(['1/2','1/3','1/6'],['1/6','1/2','1/3']),(['1','0'],['0','1']),(['1/2','1/2'],['1/2','1/2'])]:
            self.assertEqual(Q.path_mass(p,q),list(map(Fraction,p)))
    def test_decisions_against_independent_oracle(self):
        for p,q in [(['0.5','0.25','0.25'],['0.25','0.5','0.25']),(['1','0'],['0','1']),(['0.5','0.5'],['0.5','0.5'])]:
            for i in range(len(p)):
                if not Fraction(q[i]):continue
                for a,r in itertools.product(['0','0.499999999','0.75','0.999999999'],repeat=2):
                    observed=invoke('decision',','.join(p),','.join(q),i,a,r)
                    accepted,token=Q.decision(p,q,i,a,r)
                    self.assertEqual((observed['accepted'],observed['id']),(accepted,token))
    def test_emitted_processed_terminal_boundary(self):
        for maximum in [0,1,2,3,4]:
            for ids in [[2,3,4,5],[1,3,4,5],[2,1,4,5],[2,3,1,5],[2,3,4,1]]:
                for stop in [-1,0,1,2]:
                    self.assertEqual(invoke('run',maximum,','.join(map(str,ids)),stop),Q.ledger(maximum,ids,stop_after=stop))
        self.assertEqual(invoke('run',2,'2,3',-1)['cursor'],5)
    def test_rng_namespace_mt64(self):
        for seed in [0,1,18446744073709551615]:
            observed=invoke('rng',seed,12)
            for space in range(5):
                rng=Q.MT64(seed if space==0 else Q.mix(seed^space))
                self.assertEqual(observed[space],[rng.draw()>>11 for _ in range(12)])
    def test_invalid_probability_or_draw(self):
        for args in [('0.9,0','0.5,0.5',0,0,0),('nan,0','1,0',0,0,0),('1,0','0,1',0,0,0),('1,0','1,0',0,1,0),('1,0','1,0',0,-.1,0)]:invoke('decision',*args,ok=False)
    def test_transaction_adapter_and_protocol_negatives(self):
        result=invoke('selftest')
        self.assertGreaterEqual(result['assertions'],20)
        self.assertEqual(result['gpu_executed'],False)
        self.assertEqual(result['network_connected'],False)
if __name__=='__main__':unittest.main()
