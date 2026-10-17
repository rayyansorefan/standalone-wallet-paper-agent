"""Exercise GitHub workflow's real git publication protocol against a local bare remote.

A concurrent code-only merge is retried. A concurrent newer PAPER ledger
must never be overwritten, even when the remote branch has moved.
"""
import pathlib
import subprocess
import tempfile
import textwrap
import unittest


class GitRacePublication(unittest.TestCase):
    @staticmethod
    def git(where,*args):
        p=subprocess.run(['git',*args],cwd=where,capture_output=True,text=True)
        if p.returncode:
            raise AssertionError(p.stderr or p.stdout)
        return p.stdout.strip()

    @classmethod
    def setUpClass(cls):
        src=pathlib.Path('.github/workflows/paper.yml').read_text()
        src=src.split('      - name: Save cycle state and updated visualiser feed\n',1)[1]
        src=src.split('      - name: Fail visibly if key market feeds were unavailable\n',1)[0]
        cls.script=textwrap.dedent(src.split('        run: |\n',1)[1])
        assert 'base_state_blob' in cls.script
        assert 'git rebase origin/main' in cls.script
        assert 'latest_state_blob' in cls.script

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=pathlib.Path(self.tmp.name)
        self.remote=root/'remote.git';self.seed=root/'seed'
        self.runner=root/'runner';self.peer=root/'peer'
        self.git(root,'init','--quiet','--bare','--initial-branch=main',str(self.remote))
        self.git(root,'clone','--quiet',str(self.remote),str(self.seed))
        self.git(self.seed,'config','user.email','test@example.invalid')
        self.git(self.seed,'config','user.name','test')
        (self.seed/'state').mkdir();(self.seed/'docs').mkdir()
        (self.seed/'state'/'state.json').write_text('{"cycle":100}')
        (self.seed/'docs'/'state.json').write_text('{"cycle":100}')
        (self.seed/'docs'/'health.json').write_text('{"cycle":100}')
        (self.seed/'README.md').write_text('baseline')
        self.git(self.seed,'add','.')
        self.git(self.seed,'commit','--quiet','-m','initial')
        self.git(self.seed,'push','--quiet','origin','main')
        self.git(root,'clone','--quiet',str(self.remote),str(self.runner))
        self.git(root,'clone','--quiet',str(self.remote),str(self.peer))
        self.git(self.peer,'config','user.email','peer@example.invalid')
        self.git(self.peer,'config','user.name','peer')

    def local_paper_cycle(self):
        (self.runner/'state'/'state.json').write_text('{"cycle":101}')
        (self.runner/'docs'/'state.json').write_text('{"cycle":101}')
        (self.runner/'docs'/'health.json').write_text('{"cycle":101}')

    def publish(self):
        return subprocess.run(['bash','-e','-c',self.script],cwd=self.runner,
                              capture_output=True,text=True)

    def test_concurrent_code_merge_does_not_lose_paper_cycle(self):
        self.local_paper_cycle()
        (self.peer/'README.md').write_text('updated strategy documentation')
        self.git(self.peer,'add','README.md')
        self.git(self.peer,'commit','--quiet','-m','code change')
        self.git(self.peer,'push','--quiet','origin','main')
        result=self.publish()
        self.assertEqual(result.returncode,0,result.stderr+'\n'+result.stdout)
        self.git(self.runner,'fetch','--quiet','origin','main')
        self.assertEqual((self.runner/'state'/'state.json').read_text(),'{"cycle":101}')
        self.assertEqual((self.runner/'README.md').read_text(),'updated strategy documentation')
        self.assertEqual(self.git(self.runner,'show','origin/main:state/state.json'),'{"cycle":101}')
        self.assertEqual(self.git(self.runner,'show','origin/main:docs/health.json'),'{"cycle":101}')

    def test_concurrent_newer_ledger_is_not_overwritten(self):
        self.local_paper_cycle()
        (self.peer/'state'/'state.json').write_text('{"cycle":102}')
        (self.peer/'docs'/'state.json').write_text('{"cycle":102}')
        self.git(self.peer,'add','state/state.json','docs/state.json')
        self.git(self.peer,'commit','--quiet','-m','newer paper cycle')
        self.git(self.peer,'push','--quiet','origin','main')
        result=self.publish()
        self.assertEqual(result.returncode,3,result.stderr+'\n'+result.stdout)
        self.assertIn('Refusing to overwrite',result.stdout)
        self.git(self.runner,'fetch','--quiet','origin','main')
        self.assertEqual(self.git(self.runner,'show','origin/main:state/state.json'),'{"cycle":102}')
        self.assertEqual(self.git(self.runner,'show','origin/main:docs/state.json'),'{"cycle":102}')

if __name__=='__main__':
    unittest.main()
