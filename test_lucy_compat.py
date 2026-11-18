# Program: lucy-compatibility - test_lucy_compat.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Unit tests for lucy_compat.py covering loader detection, version ranges, bad input and Prism instance parsing.

# Test imports: json builds fake metadata, tempfile makes a throwaway folder, unittest is the test framework, zipfile builds fake JARs.
import json, tempfile, unittest, zipfile
from pathlib import Path
# h is the module being tested.
import lucy_compat as h

class HarnessTest(unittest.TestCase):
    """Tests for the mod metadata compatibility checker."""
    def setUp(self):
        """Make a temporary folder before every test and delete it afterwards."""
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def jar(self, entries):
        """Build a small fake JAR in the temp folder from (name, text) pairs and return its path."""
        p=self.root/'mod.jar'
        with zipfile.ZipFile(p,'w') as z:
            for k,v in entries: z.writestr(k,v)
        return p
    def test_realistic_fabric_match(self):
        """A Fabric mod asking for Minecraft 26.3 matches target 26.3, with a note that it is untested."""
        p=self.jar([('fabric.mod.json',json.dumps({'id':'lucys_game','depends':{'minecraft':'26.3'}}))])
        r=h.inspect(p,'26.3','fabric'); self.assertEqual(r['status'],'metadata_match_only')
        self.assertIn('untested',r['notes'][0])
    def test_neoforge_and_version_mismatch(self):
        """A NeoForge mod for 1.21.1 is incompatible with a Fabric 26.3 target, and the range rejects 26.3."""
        p=self.jar([('META-INF/neoforge.mods.toml','[[dependencies.pixelmon]]\nmodId="minecraft"\nversionRange="[1.21.1,1.21.2)"\n')])
        r=h.inspect(p,'26.3','fabric'); self.assertEqual(r['status'],'incompatible'); self.assertEqual(r['loader'],'neoforge')
        self.assertEqual(r['minecraft_constraints'],['[1.21.1,1.21.2)'])
        self.assertFalse(h.accepts(r['minecraft_constraints'][0],'26.3'))
    def test_nonmatching_version_same_loader(self):
        """Same loader but wrong Minecraft version gives "incompatible"."""
        p=self.jar([('fabric.mod.json',json.dumps({'depends':{'minecraft':'1.21.1'}}))])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'incompatible')
    def test_unknown_constraint_fails_closed(self):
        """A requirement the code does not understand (">=26.3") gives "unknown" rather than a guess."""
        p=self.jar([('fabric.mod.json',json.dumps({'depends':{'minecraft':'>=26.3'}}))])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_absent_malformed_and_oversized(self):
        """A missing file, broken JSON and an oversized metadata file all give "unknown" instead of crashing."""
        self.assertEqual(h.inspect(self.root/'missing.jar','26.3','fabric')['status'],'unknown')
        p=self.jar([('fabric.mod.json','{bad')]); self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
        p=self.jar([('fabric.mod.json','x'*(h.MAX_META+1))]); self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_duplicate_metadata(self):
        """Two metadata files with the same name are rejected as "unknown"."""
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore'); p=self.jar([('fabric.mod.json','{}'),('fabric.mod.json','{}')])
        self.assertEqual(h.inspect(p,'26.3','fabric')['status'],'unknown')
    def test_range_boundaries(self):
        """Square brackets include the end value, round brackets exclude it, and unsupported syntax returns None."""
        self.assertTrue(h.accepts('[1.21.1,1.21.2)','1.21.1'))
        self.assertFalse(h.accepts('[1.21.1,1.21.2)','1.21.2'))
        self.assertIsNone(h.accepts('>=1.0','26.3'))
    def test_prism(self):
        """A Prism mmc-pack.json with Minecraft and Fabric gives ('26.3', 'fabric')."""
        f=self.root/'mmc-pack.json'; f.write_text(json.dumps({'components':[{'uid':'net.minecraft','version':'26.3'},{'uid':'net.fabricmc.fabric-loader','version':'0.19.5'}]}))
        self.assertEqual(h.prism_target(f),('26.3','fabric'))

# Run all tests when this file is executed directly.
if __name__ == '__main__': unittest.main()
