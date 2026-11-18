#!/usr/bin/env python3
# Program: lucy-compatibility - registry_audit.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Audits the Radical Red reference registry embedded in a Lucy JAR by comparing it with independent species and move fixture files.

"""Read-only audit of Lucy's embedded Radical Red reference; never loads mod code."""
# Imports: all standard library. argparse = command-line options, hashlib = SHA-256
# fingerprints, json = JSON parsing, sys = stderr and exit, zipfile = reading the
# JAR (a ZIP file), Path = file paths.
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

# Constants: ENTRY is the path of the registry file inside the JAR, LIMIT caps how
# many bytes we will read (32 MiB), STAT_KEYS are the six base stats every species
# should have, and MOVE_FIELDS are the fields every move should have.
ENTRY = 'assets/lucys_game/pokemon/rr-reference.json'
LIMIT = 32 * 1024 * 1024
STAT_KEYS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
MOVE_FIELDS = ('name', 'type', 'category', 'basePower', 'accuracy', 'pp', 'priority')


def read_registry(path):
    """Open the JAR at path, read the one embedded registry JSON file and return (data dict, SHA-256 of the registry text)."""
    # Open the JAR as a ZIP archive.
    with zipfile.ZipFile(path) as archive:
        # Find archive members whose name is exactly the registry path.
        entries = [item for item in archive.infolist() if item.filename == ENTRY]
        # There must be exactly one such file; none or duplicates are rejected.
        if len(entries) != 1:
            raise ValueError('expected exactly one embedded reference registry')
        info = entries[0]
        # Check the size the ZIP header claims before reading anything.
        if info.file_size > LIMIT:
            raise ValueError('registry exceeds 32 MiB limit')
        # Read the bytes, then check the real size too, because a header can lie.
        raw = archive.read(info)
        if len(raw) > LIMIT:
            raise ValueError('registry exceeds 32 MiB limit')
        # Parse the registry JSON text.
        data = json.loads(raw)
    # The top level must be a JSON object (dictionary).
    if not isinstance(data, dict):
        raise ValueError('registry must be an object')
    # Return the data plus a fingerprint of the exact bytes that were read.
    return data, hashlib.sha256(raw).hexdigest()


def compare_fixtures(records, fixtures):
    """Check every expected fixture against the matching record and return a list of failures (empty means all matched)."""
    # Collects one entry per mismatch.
    failures = []
    # Each fixture has an id plus the field values we expect.
    for fixture in fixtures:
        name = fixture.get('id')
        # Look up the real record by its id.
        record = records.get(name)
        # A missing or malformed record counts as a failure.
        if not isinstance(record, dict):
            failures.append({'id': name, 'field': '<record>', 'reason': 'missing or invalid'})
            continue
        # Compare every expected field (except the id) using the strict comparison below.
        for field, expected in fixture.items():
            if field != 'id' and not equal_typed(record.get(field), expected):
                failures.append({'id': name, 'field': field, 'reason': 'value differs'})
    return failures


def equal_typed(actual, expected):
    """Compare JSON values without treating booleans as integers."""
    # Different JSON types are never equal (this keeps True from equalling 1).
    if type(actual) is not type(expected):
        return False
    # Dictionaries must have the same keys and equal values, compared recursively.
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equal_typed(actual[k], v) for k, v in expected.items())
    # Lists must be the same length and equal item by item, compared recursively.
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equal_typed(a, b) for a, b in zip(actual, expected))
    # Plain values (strings, numbers) are compared normally.
    return actual == expected


def audit(data, fixtures, move_fixtures=None):
    """Check the registry tables, count missing fields, compare fixtures and return one report dictionary."""
    # Will hold the five main tables once they are checked.
    tables = {}
    # Check each required table exists and is a dictionary.
    for name in ('species', 'moves', 'abilities', 'learnsets', 'types'):
        value = data.get(name)
        # Some tables may hold non-object entries, so only a missing or non-dict table is an error here.
        if not isinstance(value, dict) or any(not isinstance(x, dict) for x in value.values()):
            # Some tables (types/learnsets) may legitimately contain non-object entries.
            if not isinstance(value, dict):
                raise ValueError(name + ' table is missing or invalid')
        tables[name] = value
    # Shortcuts for the two tables we inspect in detail.
    species, moves = tables['species'], tables['moves']
    # Every species and move record must itself be an object.
    if any(not isinstance(x, dict) for x in species.values()) or any(not isinstance(x, dict) for x in moves.values()):
        raise ValueError('species/moves records must be objects')
    # Coverage counts: how many records lack types, the six numeric stats, abilities, or required move fields, and whether an items table exists.
    coverage = {
        'species_missing_types': sum(not isinstance(x.get('types'), list) or not x['types'] for x in species.values()),
        'species_missing_six_numeric_stats': sum(not isinstance(x.get('baseStats'), dict) or any(type(x['baseStats'].get(k)) not in (int, float) for k in STAT_KEYS) for x in species.values()),
        'species_missing_nonempty_abilities': sum(not isinstance(x.get('abilities'), dict) or not any(x['abilities'].values()) for x in species.values()),
        'moves_missing_fields': {field: sum(field not in x for x in moves.values()) for field in MOVE_FIELDS},
        'items_table_present': isinstance(data.get('items'), dict),
    }
    # The species fixture file must contain a non-empty list called fixtures.
    if not isinstance(fixtures, dict) or not isinstance(fixtures.get('fixtures'), list) or not fixtures['fixtures']:
        raise ValueError('invalid species fixtures')
    # Compare expected species values with the registry.
    species_failures = compare_fixtures(species, fixtures['fixtures'])
    # Does the fixtures file claim the same source commit as the registry? If not, the fixtures may be for different data.
    fixture_revision = fixtures.get('revision')
    source_commit = data.get('source_commit')
    revision_match = bool(fixture_revision and fixture_revision == source_commit)
    # Move fixtures are optional; this stays None when none were given.
    moves_check = None
    # Validate and compare the move fixtures the same way as species.
    if move_fixtures is not None:
        if not isinstance(move_fixtures, dict) or not isinstance(move_fixtures.get('fixtures'), list) or not move_fixtures['fixtures']:
            raise ValueError('invalid move fixtures')
        moves_check = {'revision_matches': bool(move_fixtures.get('revision') and move_fixtures['revision'] == source_commit),
                       'count': len(move_fixtures['fixtures']), 'failures': compare_fixtures(moves, move_fixtures['fixtures'])}
    # The registry's own validation block, if it is a dictionary.
    validation = data.get('validation') if isinstance(data.get('validation'), dict) else {}
    # Errors reported by the upstream data, if they are a list.
    errors = validation.get('errors') if isinstance(validation.get('errors'), list) else []
    # Build the final report: source info, status, counts, presence checks, fixture results and a notice that this is not a full verification.
    return {
        'source_repository': data.get('source_repository'), 'source_commit': source_commit,
        'reference_status': data.get('full_catalog_status', 'UNKNOWN'),
        'radical_red_dex_equivalence': data.get('radical_red_dex_equivalence', 'unknown'),
        'battle_effects_implemented': validation.get('battle_effects_implemented', 'unknown'),
        'complete_reference_validation': validation.get('complete_reference_validation', 'unknown'),
        'counts': {name: len(value) for name, value in tables.items()}, 'presence_checks': coverage,
        'upstream_validation_errors': errors, 'species_fixtures': {'revision_matches': revision_match,
             'count': len(fixtures['fixtures']), 'failures': species_failures}, 'move_fixtures': moves_check,
        'notice': 'Metadata and fixture comparison only; this does not verify complete data, effects, game launch or multiplayer.',
    }


def main():
    """Command-line entry point: audit the JAR and print the JSON report; return 0 only when everything is complete and matches, otherwise 2."""
    # Describe the command-line options: the JAR, required species fixtures, optional move fixtures and an optional expected JAR hash.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jar', type=Path)
    parser.add_argument('--fixtures', required=True, type=Path, help='independent species fixtures JSON')
    parser.add_argument('--move-fixtures', type=Path, help='independent move fixtures JSON, if available')
    parser.add_argument('--expected-sha256', help='optional expected whole JAR SHA-256')
    args = parser.parse_args()
    # Any expected failure below is caught and printed as an error message.
    try:
        # Compute the SHA-256 of the whole JAR in 1 MiB chunks.
        digest = hashlib.sha256()
        with args.jar.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        sha = digest.hexdigest()
        # If an expected hash was supplied, stop when it does not match.
        if args.expected_sha256 and sha.lower() != args.expected_sha256.lower():
            raise ValueError('whole JAR SHA-256 does not match expected value')
        # Read the embedded registry.
        data, registry_sha = read_registry(args.jar)
        # Load the fixture file(s) from disk.
        fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
        move_fixtures = json.loads(args.move_fixtures.read_text(encoding='utf-8')) if args.move_fixtures else None
        # Run the audit and attach both fingerprints.
        result = audit(data, fixtures, move_fixtures)
        result['jar_sha256'], result['registry_sha256'] = sha, registry_sha
        print(json.dumps(result, indent=2))
        # Flags for failed fixtures or mismatched revisions.
        bad_fixture = result['species_fixtures']['failures'] or not result['species_fixtures']['revision_matches']
        bad_moves = result['move_fixtures'] and (result['move_fixtures']['failures'] or not result['move_fixtures']['revision_matches'])
        # Exit 2 means incomplete or mismatched, even when all supplied fixtures pass.
        # Any problem or any "not complete" status gives exit code 2.
        if (bad_fixture or bad_moves or result['reference_status'] != 'COMPLETE'
                or result['complete_reference_validation'] is not True
                or result['battle_effects_implemented'] is not True
                or not result['presence_checks']['items_table_present']
                or result['upstream_validation_errors']):
            return 2
        # All checks passed.
        return 0
    # Print a JSON error to stderr and exit with 2.
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 2


# Run main() only when executed directly.
if __name__ == '__main__':
    sys.exit(main())
