# Program: lucy-compatibility - test_rr_gap_audit.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Unit tests for rr_gap_audit.py checking the gap gate, alias resolution and invalid input handling.

# Test imports: copy makes independent copies of data, unittest is the test framework, g is the module being tested.
import copy
import unittest
import rr_gap_audit as g


def sample():
    """Build a small made-up registry with a few species, moves and learnsets, including deliberate gaps (misspelled Necrozma moves and an orphan toedscoolcool entry)."""
    return {'source_commit': g.PIN, 'full_catalog_status': 'COMPLETE', 'validation': {'errors': [], 'battle_effects_implemented': True},
            'species': {'necrozmaultra': {}, 'necrozma': {}, 'toedscool': {}},
            'moves': {'autotomize': {}, 'prismaticlaser': {}, 'tackle': {}}, 'aliases': {}, 'items': {},
            'learnsets': {'necrozma': {'learnset': {'autotomize': ['9L'], 'prismaticlaser': ['9L']}},
                          'necrozmaultra': {'learnset': {'automize': ['9R'], 'prismlaser': ['9R']}},
                          'toedscool': {'learnset': {'tackle': ['9L']}},
                          'toedscoolcool': {'learnset': {'tackle': ['9L'], 'coolspikes': ['9M']}}}}

class GapAudit(unittest.TestCase):
    """Tests for the known-gap audit."""
    def test_original_errors_are_reported_without_automatic_repairs(self):
        """Known gaps must be reported and the input data must not be changed; the gate must fail."""
        data = sample(); before = copy.deepcopy(data); r = g.audit(data)
        self.assertFalse(r['known_gap_gate_pass']); self.assertEqual(data, before)
        self.assertEqual(r['toedscoolcool_comparison']['only_orphan'], ['coolspikes'])
        self.assertEqual(len(r['necrozma_possible_spelling_matches']), 2)
        self.assertFalse(next(x for x in r['missing_learnset_references'] if x['id']=='toedscoolcool')['species_found'])
    def test_complete_requires_no_unresolved_refs(self):
        """With no unresolved learnsets the gate passes, but one declared upstream error makes it fail."""
        d=sample(); d['learnsets']={'toedscool': {'learnset': {'tackle':['9L']}}}
        self.assertTrue(g.audit(d)['known_gap_gate_pass']); d['validation']['errors']=['upstream issue']; self.assertFalse(g.audit(d)['known_gap_gate_pass'])
    def test_missing_items_or_effects_or_pin_fails_closed(self):
        """Removing the items table or changing the source commit must make the gate fail."""
        d=sample(); d['learnsets']={}; self.assertTrue(g.audit(d)['known_gap_gate_pass'])
        del d['items']; self.assertFalse(g.audit(d)['known_gap_gate_pass']); d['items']={}; d['source_commit']='other'; self.assertFalse(g.audit(d)['known_gap_gate_pass'])
    def test_alias_requires_resolved_target(self):
        """An alias only counts if it points at something that exists."""
        d=sample(); d['learnsets']={'regionalform': {'learnset': {'movealias':['9L']}}}
        d['aliases']={'regionalform':'Toedscool', 'movealias':'Tackle'}
        self.assertEqual(g.audit(d)['missing_learnset_references'], [])
        d['aliases']['movealias']='Missing Move'
        self.assertEqual(g.audit(d)['missing_learnset_references'][0]['unknown_moves'], ['movealias'])
    def test_invalid_sections_rejected(self):
        """A registry whose sections have the wrong type must raise ValueError."""
        with self.assertRaises(ValueError): g.audit({'species':[], 'moves':{}, 'learnsets':{}})

# Run all tests when this file is executed directly.
if __name__ == '__main__': unittest.main()
