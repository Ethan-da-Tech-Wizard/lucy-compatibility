# Unit tests for registry_audit using small in-memory registries and a temp JAR.
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import registry_audit as audit

class RegistryAuditTest(unittest.TestCase):
    # Minimal PARTIAL registry (one species, one move, one declared error) plus
    # matching fixtures; individual tests mutate copies of these.
    def setUp(self):
        self.data = {'source_commit':'a','full_catalog_status':'PARTIAL',
                     'species':{'first':{'types':['Fire'],'baseStats':{'hp':1,'atk':2,'def':3,'spa':4,'spd':5,'spe':6},'abilities':{'0':'X'}}},
                     'moves':{'protect':{'name':'Protect','type':'Normal','category':'Status','basePower':0,'accuracy':True,'pp':10,'priority':4}},
                     'abilities':{},'learnsets':{},'types':{},'validation':{'complete_reference_validation':False,'battle_effects_implemented':False,'errors':['gap']}}
        self.fixtures={'revision':'a','fixtures':[{'id':'first','types':['Fire']}]}

    # Status, upstream errors and the missing items table are surfaced verbatim.
    def test_reports_partial_and_missing_items(self):
        result=audit.audit(self.data,self.fixtures)
        self.assertEqual(result['reference_status'],'PARTIAL')
        self.assertEqual(result['upstream_validation_errors'],['gap'])
        self.assertFalse(result['presence_checks']['items_table_present'])
        self.assertEqual(result['species_fixtures']['failures'],[])

    # A fixture revision different from source_commit, and a wrong expected value,
    # must both appear in the report.
    def test_mismatched_fixture_and_revision_are_visible(self):
        self.fixtures={'revision':'other','fixtures':[{'id':'first','types':['Water']}]}
        result=audit.audit(self.data,self.fixtures)
        self.assertFalse(result['species_fixtures']['revision_matches'])
        self.assertEqual(result['species_fixtures']['failures'][0]['field'],'types')

    # accuracy True vs 1 must fail: types are compared exactly.
    def test_bool_is_not_integer_in_fixture(self):
        self.assertFalse(audit.equal_typed(True,1))
        checks={'revision':'a','fixtures':[{'id':'protect','accuracy':1}]}
        self.assertEqual(audit.audit(self.data,self.fixtures,checks)['move_fixtures']['failures'][0]['field'],'accuracy')

    # An empty fixture list would pass vacuously, so it is rejected.
    def test_empty_fixture_not_accepted(self):
        with self.assertRaises(ValueError): audit.audit(self.data,{'fixtures':[]})

    # Two zip entries with the registry name make the archive ambiguous.
    def test_duplicate_registry_entries_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x.jar'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr(audit.ENTRY,'{}')
                with self.assertWarns(UserWarning): z.writestr(audit.ENTRY,'{}')
            with self.assertRaises(ValueError): audit.read_registry(p)

    # Deleting basePower from a move shows up in moves_missing_fields.
    def test_coverage_flags_missing_power(self):
        del self.data['moves']['protect']['basePower']
        self.assertEqual(audit.audit(self.data,self.fixtures)['presence_checks']['moves_missing_fields']['basePower'],1)

if __name__ == '__main__': unittest.main()
