#!/usr/bin/env python3
# Program: lucy-compatibility - rr_gap_audit.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Reads a Lucy candidate JAR and reports unresolved species and move references (known gaps) in its embedded Radical Red registry.

"""Read-only audit of unresolved references in a Lucy candidate JAR.

Reports evidence; does not repair IDs, run source code, or approve a release.
"""
# Imports: all standard library. argparse = command-line options, hashlib = file
# fingerprint, json = JSON parsing, re = text cleanup, zipfile = reading the JAR,
# Path = file paths.
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

# Constants: MEMBER is the registry file path inside the JAR, MAX_BYTES caps how
# much we read (32 MiB) and PIN is the source commit the registry is expected to
# come from.
MEMBER = 'assets/lucys_game/pokemon/rr-reference.json'
MAX_BYTES = 32 * 1024 * 1024
PIN = '54955790eb71a0fb0a881850f1e8afed3bfe25bd'


def audit(reference):
    """Look for learnset entries that point at unknown species or moves and return a report dictionary with a pass/fail gate."""
    # The registry must be a JSON object.
    if not isinstance(reference, dict):
        raise ValueError('reference must be an object')
    # Fetch the three tables we need: species, moves and learnsets.
    species = reference.get('species')
    moves = reference.get('moves')
    learnsets = reference.get('learnsets')
    # All three must be dictionaries or the file is invalid.
    if not all(isinstance(x, dict) for x in (species, moves, learnsets)):
        raise ValueError('missing or invalid registry sections')
    # Errors the registry says about itself.
    declared = reference.get('validation', {}).get('errors', [])
    if not isinstance(declared, list):
        raise ValueError('invalid validation errors')
    # Aliases map alternate names to real ids.
    aliases = reference.get('aliases', {})
    if not isinstance(aliases, dict):
        raise ValueError('invalid aliases')

    def resolves(key, table):
        """Return True if key is in table, directly or by following aliases."""
        # Remember keys already tried so an alias loop cannot run forever.
        seen = set()
        # Keep following aliases until we find the key, run out of aliases or loop.
        while isinstance(key, str) and key not in seen:
            seen.add(key)
            if key in table:
                return True
            # Look for an alias for this key; if there is none, it cannot be resolved.
            target = aliases.get(key)
            if not isinstance(target, str):
                return False
            # Normalize the alias target: lowercase and keep only letters and digits.
            key = re.sub(r'[^a-z0-9]', '', target.lower())
        return False

    # Collects every learnset with a problem.
    groups = []
    # Go through every learnset in a stable (sorted) order.
    for sid, data in sorted(learnsets.items()):
        if not isinstance(data, dict) or not isinstance(data.get('learnset', {}), dict):
            # Each learnset entry must itself be a dictionary.
            raise ValueError('invalid learnset ' + sid)
        # List the moves in this learnset that do not resolve to a known move.
        missing = sorted(k for k in data.get('learnset', {}) if not resolves(k, moves))
        # Report the learnset if its species is unknown or any move is unknown.
        if not resolves(sid, species) or missing:
            groups.append({'id': sid, 'species_found': resolves(sid, species), 'unknown_moves': missing})
    # Start building the report with a scope note saying this is only a known-gap diagnostic.
    out = {'scope': 'Known-gap diagnostic only; not a completeness, version, gameplay, or correctness certification.', 'source_commit': reference.get('source_commit'), 'source_pin_matches': reference.get('source_commit') == PIN,
           'declared_validation_errors': declared, 'reference_status': reference.get('full_catalog_status', 'unknown'),
           'missing_learnset_references': groups,
           'battle_effects_implemented': reference.get('validation', {}).get('battle_effects_implemented'),
           'items_table_present': isinstance(reference.get('items'), dict)}
    # Special check for Necrozma Ultra: its learnset and its parent form's learnset.
    n = learnsets.get('necrozmaultra', {}).get('learnset', {})
    parent = learnsets.get('necrozma', {}).get('learnset', {})
    # Suggest two likely misspellings (automize, prismlaser) when the corrected move exists in the moves table.
    out['necrozma_possible_spelling_matches'] = [
        {'source_id': old, 'possible_id': new, 'parent_has_candidate': new in parent}
        for old, new in [('automize', 'autotomize'), ('prismlaser', 'prismaticlaser')]
        if old in n and old not in moves and new in moves]
    # Special check for toedscool versus the orphan entry toedscoolcool.
    a = learnsets.get('toedscool', {}).get('learnset', {})
    b = learnsets.get('toedscoolcool', {}).get('learnset', {})
    # If both exist, show moves only in one, only in the other, and shared moves whose data differs.
    if a and b:
        out['toedscoolcool_comparison'] = {'only_standard': sorted(a.keys()-b.keys()), 'only_orphan': sorted(b.keys()-a.keys()),
          'differing_shared_entries': sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}
    # Report the raw values of the missingno species if it is present.
    m = species.get('missingno')
    if isinstance(m, dict):
        out['missingno_source_values'] = {k: m.get(k) for k in ('num', 'types', 'baseStats', 'abilities')}
    # The gate passes only if the commit pin matches, status is COMPLETE, there are no declared errors or unresolved references, an items table exists, and battle effects are implemented.
    out['known_gap_gate_pass'] = bool(out['source_pin_matches'] and out['reference_status'] == 'COMPLETE' and not declared and not groups
                           and out['items_table_present'] and out['battle_effects_implemented'] is True)
    return out


def load_jar(path):
    """Fingerprint the JAR and read its embedded registry; return (SHA-256, parsed registry)."""
    # Make sure we have a Path object.
    path = Path(path)
    # Hash the whole JAR in 1 MiB chunks.
    digest = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            digest.update(chunk)
    # Open the JAR as a ZIP archive.
    with zipfile.ZipFile(path) as z:
        # Find the registry member by exact name.
        infos = [i for i in z.infolist() if i.filename == MEMBER]
        # Reject missing, duplicate, oversized or directory entries.
        if len(infos) != 1 or infos[0].file_size > MAX_BYTES or infos[0].is_dir():
            raise ValueError('missing, duplicate or oversized registry')
        with z.open(infos[0]) as f:
            # Read one byte more than the limit so we can detect an oversized file.
            data = f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('oversized registry')
        # Parse the registry JSON.
        reference = json.loads(data)
    return digest.hexdigest(), reference


def main():
    """Command-line entry point: audit the JAR given as the only argument and print the report; return 0 on gate pass, otherwise 2."""
    # Define the single required argument, the JAR path.
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('jar')
    args = p.parse_args()
    # Expected failures are printed as JSON with an error message.
    try:
        sha, data = load_jar(args.jar)
        report = audit(data)
        # Add the JAR fingerprint to the report.
        report['jar_sha256'] = sha
        # Print the report with sorted keys so the output is stable.
        print(json.dumps(report, indent=2, sort_keys=True))
        # Exit code 0 means the gate passed, 2 means it did not.
        return 0 if report['known_gap_gate_pass'] else 2
    # Report any expected failure as JSON and exit with 2.
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({'known_gap_gate_pass': False, 'error': str(exc)}))
        return 2


# Run main() only when executed directly.
if __name__ == '__main__':
    raise SystemExit(main())
