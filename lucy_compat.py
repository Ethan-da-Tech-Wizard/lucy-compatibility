#!/usr/bin/env python3
# ==============================================================================
# Program: lucy_compat.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Inspects Minecraft mod JAR metadata for loader and version compatibility
# ==============================================================================
"""Read-only mod metadata compatibility report. Does not load or execute JARs."""
# Standard-library only on purpose: the tool must run anywhere Python 3 exists
# and must never import or execute code from the JARs it inspects.
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

# Upper bound (1 MiB) on the size of a loader metadata file we are willing to
# decompress. Guards against zip bombs: the metadata is attacker-controlled
# input because the JAR comes from a third party.
MAX_META = 1024 * 1024
# Metadata entry names we recognise, one per supported loader:
# fabric.mod.json (Fabric), neoforge.mods.toml (NeoForge), mods.toml (Forge).
# A JAR must contain exactly one of these to be inspectable.
META = ('fabric.mod.json', 'META-INF/neoforge.mods.toml', 'META-INF/mods.toml')


def version(v):
    """Parse a dotted numeric version ('1.20.1') into an int tuple.

    Returns None for anything that is not strictly digits separated by dots
    (snapshots, 'x' wildcards, empty strings, non-strings), so callers can
    treat "cannot parse" as "unknown" instead of guessing.
    """
    ## Validate input format: must be string of dot-separated integers (e.g. '1.20.1')
    if not isinstance(v, str) or not re.fullmatch(r'\d+(?:\.\d+)*', v):
        return None
    ## Parse each segment into an integer tuple to allow natural numerical comparisons
    return tuple(int(x) for x in v.split('.'))


def cmp_version(a, b):
    """Three-way compare two version tuples; returns -1, 0 or 1.

    Shorter tuples are zero-padded so that (1, 20) equals (1, 20, 0).
    """
    # Padding is done on local copies; the caller's tuples are not mutated.
    ## Normalize tuple lengths with trailing zeros so that (1, 20) matches (1, 20, 0)
    n = max(len(a), len(b))
    a, b = a + (0,) * (n-len(a)), b + (0,) * (n-len(b))
    ## Three-way comparison operator returning -1, 0, or 1
    return (a > b) - (a < b)


def accepts(spec, target):
    """Known Maven ranges and exact numeric versions; uncertainty stays unknown.
    
    Parameters:
        spec (str): Version requirement (e.g. '1.20.1', '[1.20, 1.21)', '(, 1.19.4]').
        target (str): Concrete Minecraft version string to test against the specification.
    Returns:
        bool | None: True if satisfied, False if violated, None if unparseable / ambiguous.
    """
    t = version(target)
    if t is None or not isinstance(spec, str):
        return None
    spec = spec.strip()
    v = version(spec)
    ## Exact version equality check
    if v is not None:
        return cmp_version(t, v) == 0
    ## Parse Maven-style interval notation: [lower, upper], (lower, upper), etc.
    m = re.fullmatch(r'([\[(])\s*(\d+(?:\.\d+)*)?\s*,\s*(\d+(?:\.\d+)*)?\s*([\])])', spec)
    if not m or (not m[2] and not m[3]):
        return None
    ## Validate lower boundary condition (inclusive vs exclusive)
    if m[2]:
        c = cmp_version(t, version(m[2]))
        if c < 0 or (c == 0 and m[1] == '('):
            return False
    ## Validate upper boundary condition (inclusive vs exclusive)
    if m[3]:
        c = cmp_version(t, version(m[3]))
        if c > 0 or (c == 0 and m[4] == ')'):
            return False
    return True


def sha256(path):
    """Return the hex SHA-256 of the file at `path`, reading it in chunks."""
    # Stream the file in 1 MiB chunks (f.read(1024 * 1024) below) so SHA-256 needs O(1) memory
    # regardless of jar size.
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def toml_minecraft(text):
    """Extract the 'minecraft' dependency version ranges from a mods.toml body.

    A deliberately narrow regex parser (no TOML library in the stdlib on older
    Pythons). Only [[dependencies.<modid>]] tables whose modId is exactly
    'minecraft' are considered. A matching table with no versionRange yields the
    sentinel 'unknown', which accepts() later treats as not understood.
    """
    # Narrow parser, intentionally returns unknown for ambiguous/unfamiliar metadata.
    deps = []
    # Split into chunks that each begin at an array-of-tables header "[[...",
    # so that modId/versionRange lines are only paired within one dependency.
    blocks = re.split(r'(?m)^\s*(?=\[\[)', text)
    for block in blocks:
        # Skip any block that is not a dependency table (e.g. [[mods]] or preamble).
        if not re.match(r'\s*\[\[dependencies\.[^\]]+\]\]', block):
            continue
        mod = re.findall(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        ranges = re.findall(r'(?m)^\s*versionRange\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        # Exactly one modId line equal to 'minecraft'; anything else is ignored.
        if mod == ['minecraft']:
            deps.extend(ranges or ['unknown'])
    return deps


def inspect(path, target, loader):
    """Inspect one JAR and return a JSON-serialisable compatibility report.

    Status values: 'incompatible' (loader mismatch or version range excludes
    the target), 'metadata_match_only' (metadata is consistent with the target;
    nothing beyond metadata is verified) and 'unknown' (cannot inspect, or the
    constraint is missing/not understood). Never raises for bad JARs: problems
    are recorded in result['notes'].
    """
    # Start from the pessimistic default ('unknown'); each check can only move
    # the status to something more specific.
    result = {'file': str(path), 'sha256': None, 'target_minecraft': target,
              'target_loader': loader, 'loader': None, 'minecraft_constraints': [],
              'status': 'unknown', 'notes': []}
    try:
        # Hash first so even an unreadable/odd archive still gets an identity.
        result['sha256'] = sha256(path)
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [x.filename for x in infos]
            present = [name for name in META if name in names]
            # A duplicated metadata entry would let two different parsers disagree about
            # which one wins (a known zip-ambiguity trick), so refuse such archives.
            if any(names.count(n) != 1 for n in present):
                raise ValueError('duplicate metadata entries')
            if len(present) != 1:
                raise ValueError('expected exactly one recognized loader metadata file')
            info = z.getinfo(present[0])
            # Check the declared uncompressed size before reading, to bound memory use.
            if info.file_size > MAX_META:
                raise ValueError('metadata exceeds size limit')
            text = z.read(info).decode('utf-8')
            if present[0] == 'fabric.mod.json':
                result['loader'] = 'fabric'
                data = json.loads(text)
                result['mod_id'] = data.get('id')
                spec = data.get('depends', {}).get('minecraft')
                result['minecraft_constraints'] = spec if isinstance(spec, list) else ([spec] if spec else [])
            else:
                result['loader'] = 'neoforge' if 'neoforge' in present[0] else 'forge'
                result['minecraft_constraints'] = toml_minecraft(text)
    except (OSError, zipfile.BadZipFile, ValueError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError) as e:
        result['notes'].append('Cannot inspect metadata: ' + str(e))
        return result
    # Everything below is pure comparison of already-extracted metadata.
    result['loader_match'] = result['loader'] == loader.lower()
    # One tri-state result per declared constraint: True / False / None (unknown).
    checks = [accepts(s, target) for s in result['minecraft_constraints']]
    if not result['loader_match']:
        result['status'] = 'incompatible'
        result['notes'].append('Declared loader differs from the target loader.')
    # Every declared range excludes the target version: definitely incompatible.
    elif checks and all(c is False for c in checks):
        result['status'] = 'incompatible'
        result['notes'].append('Declared Minecraft version does not include the target.')
    # At least one range accepts the target and none are unparseable. This is only
    # a metadata match; it says nothing about dependencies or runtime behaviour.
    elif checks and any(c is True for c in checks) and all(c is not None for c in checks):
        result['status'] = 'metadata_match_only'
        result['notes'].append('Metadata matches only; dependencies, APIs and actual gameplay are untested.')
    # No constraint, or at least one that accepts() could not interpret.
    else:
        result['notes'].append('Minecraft version constraint is missing or not understood; compatibility is unknown.')
    # Always state the scope limit so the output is not over-read as a guarantee.
    result['notes'].append('This report does not install, modify, port or run a mod.')
    return result


def prism_target(path):
    """Read (minecraft_version, loader) from a Prism Launcher mmc-pack.json.

    Raises ValueError unless the instance names Minecraft and exactly one
    supported loader, since the target would otherwise be ambiguous.
    """
    d = json.loads(path.read_text(encoding='utf-8'))
    # Map component uid -> version for the entries that are dicts.
    versions = {x.get('uid'): x.get('version') for x in d['components'] if isinstance(x, dict)}
    mc = versions.get('net.minecraft')
    # Prism component uids that identify each loader; keep those present.
    loaders = [x for x, uid in [('fabric', 'net.fabricmc.fabric-loader'),
               ('neoforge', 'net.neoforged'), ('forge', 'net.minecraftforge')] if versions.get(uid)]
    if not isinstance(mc, str) or len(loaders) != 1:
        raise ValueError('Prism instance must identify Minecraft and exactly one supported loader')
    return mc, loaders[0]


def main():
    """CLI entry point. Exit codes: 0 metadata match, 2 anything else."""
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('jar', type=Path, help='A mod JAR you already have; it is only read')
    p.add_argument('--instance', type=Path, help='Prism instance folder containing mmc-pack.json')
    p.add_argument('--minecraft', default='26.3', help='Target Minecraft version (default 26.3)')
    p.add_argument('--loader', default='fabric', choices=['fabric', 'forge', 'neoforge'])
    a = p.parse_args()
    # An instance folder overrides --minecraft/--loader with what it declares.
    if a.instance:
        try:
            a.minecraft, a.loader = prism_target(a.instance / 'mmc-pack.json')
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            p.error('Cannot read Prism instance: ' + str(e))
    result = inspect(a.jar, a.minecraft, a.loader)
    print(json.dumps(result, indent=2))
    # Non-zero for every outcome except a metadata match so scripts can gate on it.
    return 0 if result['status'] == 'metadata_match_only' else 2


if __name__ == '__main__':
    sys.exit(main())
