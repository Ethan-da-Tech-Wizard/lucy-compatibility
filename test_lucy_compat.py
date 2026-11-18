import json, tempfile, unittest, zipfile
from pathlib import Path
import lucy_compat as h

class HarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def jar(self, entries):
        p=self.root/'mod.jar'
        with zipfile.ZipFile(p,'w') as z:
            for k,v in entries: z.writestr(k,v)
        return p
    def test_realistic_fabric_match(self):
        p=self.jar([('fabric.mod.json',json.dumps({'id':'lucys_game','depends':{'minecraft':'26.3'}}))])
        r=h.inspect(p,'26.3','fabric'); self.assertEqual(r['status'],'metadata_match_only')
        self.assertIn('untested',r['notes'][0])
    def test_neoforge_and_version_mismatch(self):
        p=self.jar([('META-INF/neoforge.mods.toml','[[dependencies.pixelmon]]\nmodId="minecraft"\nversionRange="[1.21.1,1.21.2)"\n')])
        r=h.inspect(p,'26.3','fabric'); self.assertEqual(r['status'],'incompatible'); self.assertEqual(r['loader'],'neoforge')
        self.assertEqual(r['minecraft_constraints'],['[1.21.1,1.21.2)'])
        self.assertFalse(h.accepts(r['minecraft_constraints'][0],'26.3'))
    def test_nonmatching_version_same_loader(self):
        p=self.jar([('fabric.mod.json',json.dumps({'depends':{'minecraft':'1.21.1'}}))])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'incompatible')
    def test_unknown_constraint_fails_closed(self):
        p=self.jar([('fabric.mod.json',json.dumps({'depends':{'minecraft':'>=26.3'}}))])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_absent_malformed_and_oversized(self):
        self.assertEqual(h.inspect(self.root/'missing.jar','26.3','fabric')['status'],'unknown')
        p=self.jar([('fabric.mod.json','{bad')]); self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
        p=self.jar([('fabric.mod.json','x'*(h.MAX_META+1))]); self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_duplicate_metadata(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore'); p=self.jar([('fabric.mod.json','{}'),('fabric.mod.json','{}')])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_range_boundaries(self):
        self.assertTrue(h.accepts('[1.21.1,1.21.2)','1.21.1'))
        self.assertFalse(h.accepts('[1.21.1,1.21.2)','1.21.2'))
        self.assertIsNone(h.accepts('>=1.0','26.3'))
    def test_prism(self):
        f=self.root/'mmc-pack.json'; f.write_text(json.dumps({'components':[{'uid':'net.minecraft','version':'26.3'},{'uid':'net.fabricmc.fabric-loader','version':'0.19.5'}]}))
        self.assertEqual(h.prism_target(f),('26.3','fabric'))

if __name__ == '__main__': unittest.main()
