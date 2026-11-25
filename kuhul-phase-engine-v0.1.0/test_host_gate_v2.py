import unittest
from host_gate import parse_suite,load_signatures,compare,assess

SIG=load_signatures()
def result(text): return {'stdout':'','stderr':text,'exit_code':1,'command_line':['unittest']}
def snap(cases,healthy=True):
    return {'host':'host','command_line':['unittest'],'signature_declarations':SIG,
            'suite':{'summary':{'cases':cases,'complete':True,'ok':healthy}},
            'base_health':{'exit_code':0,'stdout':'unchanged','stderr':''},
            'extension_summary':{'exit_code':0,'stdout':'unchanged','stderr':''}}
def case(name,outcome,signatures=None): return {'test_id':name,'outcome':outcome,'signatures':signatures or []}
class HarnessTests(unittest.TestCase):
    def test_traceback_attribution(self):
        log='''test_a (tests.Test) ... ERROR\ntest_b (tests.Test) ... ok\n\n======================================================================\nERROR: test_a (tests.Test)\n----------------------------------------------------------------------\nTraceback (most recent call last):\n  File "core/extension.py", line 10, in load\nValueError: schema mismatch\n\n----------------------------------------------------------------------\nRan 2 tests in 0.01s\nFAILED (errors=1)\n'''
        parsed=parse_suite(result(log),SIG)
        self.assertEqual(parsed['cases']['tests.Test.test_a']['signatures'],['F14-schema-mismatch'])
        self.assertEqual(parsed['cases']['tests.Test.test_b']['signatures'],[])
        self.assertTrue(parsed['complete'])
    def test_named_recovery_matches_signature(self):
        b=snap({'x':case('x','errored',['F14-schema-mismatch'])},False)
        a=snap({'x':case('x','passed')})
        diff=compare(b,a)
        self.assertEqual(diff['recovered_matched']['F14-schema-mismatch'],['x'])
        self.assertFalse(diff['recovered_unmatched'])
    def test_unmatched_recovery_visible(self):
        b=snap({'x':case('x','failed')},False); a=snap({'x':case('x','passed')})
        self.assertEqual(compare(b,a)['recovered_unmatched'],['x'])
    def test_disappeared_not_recovered(self):
        b=snap({'x':case('x','errored',['F14-schema-mismatch'])},False); a=snap({})
        diff=compare(b,a)
        self.assertFalse(diff['recovered'])
        self.assertEqual(diff['disappeared'][0]['test_id'],'x')
        self.assertEqual(assess(b,a,diff)['verdict']['f14_closed']['status'],'inconclusive')
    def test_health_unchanged_does_not_close(self):
        b=snap({'x':case('x','errored',['F14-schema-mismatch'])},False)
        a=snap({'x':case('x','passed')})
        verdict=assess(b,a,compare(b,a))['verdict']
        self.assertEqual(verdict['f14_closed']['status'],'inconclusive')
        self.assertFalse(verdict['merge_authorized'])
    def test_command_mismatch_blocks(self):
        b=snap({'x':case('x','errored',['F14-schema-mismatch'])},False)
        a=snap({'x':case('x','passed')}); a['command_line']=['other']
        self.assertIn('different suite commands',assess(b,a,compare(b,a))['verdict']['f14_closed']['reasons'])
if __name__=='__main__': unittest.main()
