#!/usr/bin/env python3
# ==============================================================================
# Program: rr_gap_audit.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Audit gap analysis and move fixture validation for Pokémon registries
# ==============================================================================
"""Read-only audit of unresolved references in a Lucy candidate JAR.

Reports evidence; does not repair IDs, run source code, or approve a release.
"""
# Standard library only; the JAR is read as a zip and nothing in it is executed.
import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

# Registry entry path inside the candidate JAR.
MEMBER = 'assets/lucys_game/pokemon/rr-reference.json'
# 32 MiB cap on the registry, enforced on declared size and on bytes read.
MAX_BYTES = 32 * 1024 * 1024
# Upstream source commit the registry is expected to be generated from;
# 'source_pin_matches' in the report compares against this value.
PIN = '54955790eb71a0fb0a881850f1e8afed3bfe25bd'


def audit(reference):
    """Analyse a parsed registry for unresolved learnset references.

    Returns a report dict; 'known_gap_gate_pass' is True only when the pin
    matches, status is COMPLETE, no errors are declared, nothing is unresolved,
    an items table exists and battle effects are flagged as implemented.
    Raises ValueError if the registry's sections are structurally invalid.
    """
    if not isinstance(reference, dict):
        raise ValueError('reference must be an object')
    species = reference.get('species')
    moves = reference.get('moves')
    learnsets = reference.get('learnsets')
    if not all(isinstance(x, dict) for x in (species, moves, learnsets)):
        raise ValueError('missing or invalid registry sections')
    declared = reference.get('validation', {}).get('errors', [])
    if not isinstance(declared, list):
        raise ValueError('invalid validation errors')
    aliases = reference.get('aliases', {})
    if not isinstance(aliases, dict):
        raise ValueError('invalid aliases')

    # Return True if `key` is in `table`, following the alias map as needed.
    # Aliases are normalised to lowercase alphanumerics (the registry's id form)
    # and `seen` guards against alias cycles.
    def resolves(key, table):
        seen = set()
        while isinstance(key, str) and key not in seen:
            seen.add(key)
            if key in table:
                return True
            target = aliases.get(key)
            if not isinstance(target, str):
                return False
            key = re.sub(r'[^a-z0-9]', '', target.lower())
        return False

    # Collect every learnset whose species or moves cannot be resolved.
    groups = []
    for sid, data in sorted(learnsets.items()):
        if not isinstance(data, dict) or not isinstance(data.get('learnset', {}), dict):
            raise ValueError('invalid learnset ' + sid)
        missing = sorted(k for k in data.get('learnset', {}) if not resolves(k, moves))
        if not resolves(sid, species) or missing:
            groups.append({'id': sid, 'species_found': resolves(sid, species), 'unknown_moves': missing})
    # Base report. The scope string is intentionally explicit so the output is
    # not mistaken for a completeness or correctness certification.
    out = {'scope': 'Known-gap diagnostic only; not a completeness, version, gameplay, or correctness certification.', 'source_commit': reference.get('source_commit'), 'source_pin_matches': reference.get('source_commit') == PIN,
           'declared_validation_errors': declared, 'reference_status': reference.get('full_catalog_status', 'unknown'),
           'missing_learnset_references': groups,
           'battle_effects_implemented': reference.get('validation', {}).get('battle_effects_implemented'),
           'items_table_present': isinstance(reference.get('items'), dict)}
    # Known-gap diagnostic: Necrozma-Ultra lists moves that look like misspellings
    # of real moves (automize -> autotomize, prismlaser -> prismaticlaser).
    # These are reported as candidates only; nothing is repaired automatically.
    n = learnsets.get('necrozmaultra', {}).get('learnset', {})
    parent = learnsets.get('necrozma', {}).get('learnset', {})
    out['necrozma_possible_spelling_matches'] = [
        {'source_id': old, 'possible_id': new, 'parent_has_candidate': new in parent}
        for old, new in [('automize', 'autotomize'), ('prismlaser', 'prismaticlaser')]
        if old in n and old not in moves and new in moves]
    # Known-gap diagnostic: 'toedscoolcool' is an orphan learnset with no species;
    # compare it to the genuine 'toedscool' entry to show what differs.
    a = learnsets.get('toedscool', {}).get('learnset', {})
    b = learnsets.get('toedscoolcool', {}).get('learnset', {})
    if a and b:
        out['toedscoolcool_comparison'] = {'only_standard': sorted(a.keys()-b.keys()), 'only_orphan': sorted(b.keys()-a.keys()),
          'differing_shared_entries': sorted(k for k in a.keys() & b.keys() if a[k] != b[k])}
    # Surface the source's raw MissingNo values for human review.
    m = species.get('missingno')
    if isinstance(m, dict):
        out['missingno_source_values'] = {k: m.get(k) for k in ('num', 'types', 'baseStats', 'abilities')}
    # Strict AND of all release-gate conditions; any unknown fails closed.
    out['known_gap_gate_pass'] = bool(out['source_pin_matches'] and out['reference_status'] == 'COMPLETE' and not declared and not groups
                           and out['items_table_present'] and out['battle_effects_implemented'] is True)
    return out


def load_jar(path):
    """Return (jar_sha256, parsed_registry) for a candidate JAR path."""
    path = Path(path)
    digest = hashlib.sha256()
    # Stream-hash the whole JAR so the report is tied to an exact file.
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            digest.update(chunk)
    with zipfile.ZipFile(path) as z:
        infos = [i for i in z.infolist() if i.filename == MEMBER]
        # Require exactly one regular, size-bounded registry entry.
        if len(infos) != 1 or infos[0].file_size > MAX_BYTES or infos[0].is_dir():
            raise ValueError('missing, duplicate or oversized registry')
        with z.open(infos[0]) as f:
            # Read one byte past the cap so oversize is detectable without unbounded reads.
            data = f.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('oversized registry')
        reference = json.loads(data)
    return digest.hexdigest(), reference


def main():
    """CLI entry: print the JSON report; exit 0 on gate pass, else 2."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('jar')
    args = p.parse_args()
    try:
        sha, data = load_jar(args.jar)
        report = audit(data)
        report['jar_sha256'] = sha
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if report['known_gap_gate_pass'] else 2
    except (OSError, ValueError, TypeError, KeyError, zipfile.BadZipFile) as exc:
        print(json.dumps({'known_gap_gate_pass': False, 'error': str(exc)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
