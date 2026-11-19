# Unit tests for rr_gap_audit using a compact synthetic registry.
import copy
import unittest
import rr_gap_audit as g


# Synthetic registry that satisfies the pin/status/items conditions but has
# the known gaps (misspelled Necrozma moves, orphan 'toedscoolcool' learnset).
def sample():
    return {'source_commit': g.PIN, 'full_catalog_status': 'COMPLETE', 'validation': {'errors': [], 'battle_effects_implemented': True},
            'species': {'necrozmaultra': {}, 'necrozma': {}, 'toedscool': {}},
            'moves': {'autotomize': {}, 'prismaticlaser': {}, 'tackle': {}}, 'aliases': {}, 'items': {},
            'learnsets': {'necrozma': {'learnset': {'autotomize': ['9L'], 'prismaticlaser': ['9L']}},
                          'necrozmaultra': {'learnset': {'automize': ['9R'], 'prismlaser': ['9R']}},
                          'toedscool': {'learnset': {'tackle': ['9L']}},
                          'toedscoolcool': {'learnset': {'tackle': ['9L'], 'coolspikes': ['9M']}}}}

class GapAudit(unittest.TestCase):
    # The audit must not mutate its input, must fail the gate, and must report
    # the orphan-only move and the two possible spelling matches.
    def test_original_errors_are_reported_without_automatic_repairs(self):
        data = sample(); before = copy.deepcopy(data); r = g.audit(data)
        self.assertFalse(r['known_gap_gate_pass']); self.assertEqual(data, before)
        self.assertEqual(r['toedscoolcool_comparison']['only_orphan'], ['coolspikes'])
        self.assertEqual(len(r['necrozma_possible_spelling_matches']), 2)
        self.assertFalse(next(x for x in r['missing_learnset_references'] if x['id']=='toedscoolcool')['species_found'])
    # Gate passes only when nothing is unresolved and no upstream errors remain.
    def test_complete_requires_no_unresolved_refs(self):
        d=sample(); d['learnsets']={'toedscool': {'learnset': {'tackle':['9L']}}}
        self.assertTrue(g.audit(d)['known_gap_gate_pass']); d['validation']['errors']=['upstream issue']; self.assertFalse(g.audit(d)['known_gap_gate_pass'])
    # Removing items table or changing the pin each flips the gate to False.
    def test_missing_items_or_effects_or_pin_fails_closed(self):
        d=sample(); d['learnsets']={}; self.assertTrue(g.audit(d)['known_gap_gate_pass'])
        del d['items']; self.assertFalse(g.audit(d)['known_gap_gate_pass']); d['items']={}; d['source_commit']='other'; self.assertFalse(g.audit(d)['known_gap_gate_pass'])
    # Aliases resolve only when their target exists in the table.
    def test_alias_requires_resolved_target(self):
        d=sample(); d['learnsets']={'regionalform': {'learnset': {'movealias':['9L']}}}
        d['aliases']={'regionalform':'Toedscool', 'movealias':'Tackle'}
        self.assertEqual(g.audit(d)['missing_learnset_references'], [])
        d['aliases']['movealias']='Missing Move'
        self.assertEqual(g.audit(d)['missing_learnset_references'][0]['unknown_moves'], ['movealias'])
    # Non-dict sections raise ValueError instead of being coerced.
    def test_invalid_sections_rejected(self):
        with self.assertRaises(ValueError): g.audit({'species':[], 'moves':{}, 'learnsets':{}})

if __name__ == '__main__': unittest.main()
