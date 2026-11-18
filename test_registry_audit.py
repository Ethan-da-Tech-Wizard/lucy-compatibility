# Program: lucy-compatibility - test_registry_audit.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Unit tests for registry_audit.py checking partial registries, fixture mismatches, strict typing and duplicate entries.

# Test imports: json, tempfile and zipfile build fake data and JARs, unittest is the test framework, Path handles file paths.
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

# audit is the module being tested.
import registry_audit as audit

class RegistryAuditTest(unittest.TestCase):
    """Tests for the Radical Red registry audit."""
    def setUp(self):
        """Before each test, build a tiny registry (one species, one move) and a matching species fixture list."""
        self.data = {'source_commit':'a','full_catalog_status':'PARTIAL',
                     'species':{'first':{'types':['Fire'],'baseStats':{'hp':1,'atk':2,'def':3,'spa':4,'spd':5,'spe':6},'abilities':{'0':'X'}}},
                     'moves':{'protect':{'name':'Protect','type':'Normal','category':'Status','basePower':0,'accuracy':True,'pp':10,'priority':4}},
                     'abilities':{},'learnsets':{},'types':{},'validation':{'complete_reference_validation':False,'battle_effects_implemented':False,'errors':['gap']}}
        self.fixtures={'revision':'a','fixtures':[{'id':'first','types':['Fire']}]}

    def test_reports_partial_and_missing_items(self):
        """A PARTIAL registry with an upstream error and no items table must be reported as such."""
        result=audit.audit(self.data,self.fixtures)
        self.assertEqual(result['reference_status'],'PARTIAL')
        self.assertEqual(result['upstream_validation_errors'],['gap'])
        self.assertFalse(result['presence_checks']['items_table_present'])
        self.assertEqual(result['species_fixtures']['failures'],[])

    def test_mismatched_fixture_and_revision_are_visible(self):
        """A wrong revision and a wrong type must show up in the report."""
        self.fixtures={'revision':'other','fixtures':[{'id':'first','types':['Water']}]}
        result=audit.audit(self.data,self.fixtures)
        self.assertFalse(result['species_fixtures']['revision_matches'])
        self.assertEqual(result['species_fixtures']['failures'][0]['field'],'types')

    def test_bool_is_not_integer_in_fixture(self):
        """True must not equal 1: a move fixture with accuracy 1 fails against accuracy True."""
        self.assertFalse(audit.equal_typed(True,1))
        checks={'revision':'a','fixtures':[{'id':'protect','accuracy':1}]}
        self.assertEqual(audit.audit(self.data,self.fixtures,checks)['move_fixtures']['failures'][0]['field'],'accuracy')

    def test_empty_fixture_not_accepted(self):
        """An empty fixture list is an error, since it would prove nothing."""
        with self.assertRaises(ValueError): audit.audit(self.data,{'fixtures':[]})

    def test_duplicate_registry_entries_rejected(self):
        """A JAR containing the registry file twice must be rejected."""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'x.jar'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr(audit.ENTRY,'{}')
                with self.assertWarns(UserWarning): z.writestr(audit.ENTRY,'{}')
            with self.assertRaises(ValueError): audit.read_registry(p)

    def test_coverage_flags_missing_power(self):
        """Removing basePower from a move must be counted in the coverage numbers."""
        del self.data['moves']['protect']['basePower']
        self.assertEqual(audit.audit(self.data,self.fixtures)['presence_checks']['moves_missing_fields']['basePower'],1)

# Run all tests when this file is executed directly.
if __name__ == '__main__': unittest.main()
