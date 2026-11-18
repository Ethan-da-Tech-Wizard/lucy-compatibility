#!/usr/bin/env python3
# ==============================================================================
# Program: registry_audit.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Radical Red registry audit against verified species and move fixtures
# ==============================================================================
"""Read-only audit of Lucy's embedded Radical Red reference; never loads mod code."""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ENTRY = 'assets/lucys_game/pokemon/rr-reference.json'
LIMIT = 32 * 1024 * 1024
STAT_KEYS = ('hp', 'atk', 'def', 'spa', 'spd', 'spe')
MOVE_FIELDS = ('name', 'type', 'category', 'basePower', 'accuracy', 'pp', 'priority')


def read_registry(path):
    with zipfile.ZipFile(path) as archive:
        entries = [item for item in archive.infolist() if item.filename == ENTRY]
        if len(entries) != 1:
            raise ValueError('expected exactly one embedded reference registry')
        info = entries[0]
        if info.file_size > LIMIT:
            raise ValueError('registry exceeds 32 MiB limit')
        raw = archive.read(info)
        if len(raw) > LIMIT:
            raise ValueError('registry exceeds 32 MiB limit')
        data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('registry must be an object')
    return data, hashlib.sha256(raw).hexdigest()


def compare_fixtures(records, fixtures):
    failures = []
    for fixture in fixtures:
        name = fixture.get('id')
        record = records.get(name)
        if not isinstance(record, dict):
            failures.append({'id': name, 'field': '<record>', 'reason': 'missing or invalid'})
            continue
        for field, expected in fixture.items():
            if field != 'id' and not equal_typed(record.get(field), expected):
                failures.append({'id': name, 'field': field, 'reason': 'value differs'})
    return failures


def equal_typed(actual, expected):
    """Compare JSON values without treating booleans as integers."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(equal_typed(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(equal_typed(a, b) for a, b in zip(actual, expected))
    return actual == expected


def audit(data, fixtures, move_fixtures=None):
    tables = {}
    for name in ('species', 'moves', 'abilities', 'learnsets', 'types'):
        value = data.get(name)
        if not isinstance(value, dict) or any(not isinstance(x, dict) for x in value.values()):
            # Some tables (types/learnsets) may legitimately contain non-object entries.
            if not isinstance(value, dict):
                raise ValueError(name + ' table is missing or invalid')
        tables[name] = value
    species, moves = tables['species'], tables['moves']
    if any(not isinstance(x, dict) for x in species.values()) or any(not isinstance(x, dict) for x in moves.values()):
        raise ValueError('species/moves records must be objects')
    coverage = {
        'species_missing_types': sum(not isinstance(x.get('types'), list) or not x['types'] for x in species.values()),
        'species_missing_six_numeric_stats': sum(not isinstance(x.get('baseStats'), dict) or any(type(x['baseStats'].get(k)) not in (int, float) for k in STAT_KEYS) for x in species.values()),
        'species_missing_nonempty_abilities': sum(not isinstance(x.get('abilities'), dict) or not any(x['abilities'].values()) for x in species.values()),
        'moves_missing_fields': {field: sum(field not in x for x in moves.values()) for field in MOVE_FIELDS},
        'items_table_present': isinstance(data.get('items'), dict),
    }
    if not isinstance(fixtures, dict) or not isinstance(fixtures.get('fixtures'), list) or not fixtures['fixtures']:
        raise ValueError('invalid species fixtures')
    species_failures = compare_fixtures(species, fixtures['fixtures'])
    fixture_revision = fixtures.get('revision')
    source_commit = data.get('source_commit')
    revision_match = bool(fixture_revision and fixture_revision == source_commit)
    moves_check = None
    if move_fixtures is not None:
        if not isinstance(move_fixtures, dict) or not isinstance(move_fixtures.get('fixtures'), list) or not move_fixtures['fixtures']:
            raise ValueError('invalid move fixtures')
        moves_check = {'revision_matches': bool(move_fixtures.get('revision') and move_fixtures['revision'] == source_commit),
                       'count': len(move_fixtures['fixtures']), 'failures': compare_fixtures(moves, move_fixtures['fixtures'])}
    validation = data.get('validation') if isinstance(data.get('validation'), dict) else {}
    errors = validation.get('errors') if isinstance(validation.get('errors'), list) else []
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('jar', type=Path)
    parser.add_argument('--fixtures', required=True, type=Path, help='independent species fixtures JSON')
    parser.add_argument('--move-fixtures', type=Path, help='independent move fixtures JSON, if available')
    parser.add_argument('--expected-sha256', help='optional expected whole JAR SHA-256')
    args = parser.parse_args()
    try:
        digest = hashlib.sha256()
        with args.jar.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        sha = digest.hexdigest()
        if args.expected_sha256 and sha.lower() != args.expected_sha256.lower():
            raise ValueError('whole JAR SHA-256 does not match expected value')
        data, registry_sha = read_registry(args.jar)
        fixtures = json.loads(args.fixtures.read_text(encoding='utf-8'))
        move_fixtures = json.loads(args.move_fixtures.read_text(encoding='utf-8')) if args.move_fixtures else None
        result = audit(data, fixtures, move_fixtures)
        result['jar_sha256'], result['registry_sha256'] = sha, registry_sha
        print(json.dumps(result, indent=2))
        bad_fixture = result['species_fixtures']['failures'] or not result['species_fixtures']['revision_matches']
        bad_moves = result['move_fixtures'] and (result['move_fixtures']['failures'] or not result['move_fixtures']['revision_matches'])
        # Exit 2 means incomplete or mismatched, even when all supplied fixtures pass.
        if (bad_fixture or bad_moves or result['reference_status'] != 'COMPLETE'
                or result['complete_reference_validation'] is not True
                or result['battle_effects_implemented'] is not True
                or not result['presence_checks']['items_table_present']
                or result['upstream_validation_errors']):
            return 2
        return 0
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'error', 'message': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
