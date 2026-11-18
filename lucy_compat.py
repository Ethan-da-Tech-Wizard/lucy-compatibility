#!/usr/bin/env python3
# ==============================================================================
# Program: lucy_compat.py
# Programmer: Ethan-da-Tech-Wizard
# Last Modified: November 18, 2026
# Purpose: Inspects Minecraft mod JAR metadata for loader and version compatibility
# ==============================================================================
"""Read-only mod metadata compatibility report. Does not load or execute JARs."""
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

MAX_META = 1024 * 1024
META = ('fabric.mod.json', 'META-INF/neoforge.mods.toml', 'META-INF/mods.toml')


def version(v):
    ## Validate input format: must be string of dot-separated integers (e.g. '1.20.1')
    if not isinstance(v, str) or not re.fullmatch(r'\d+(?:\.\d+)*', v):
        return None
    ## Parse each segment into an integer tuple to allow natural numerical comparisons
    return tuple(int(x) for x in v.split('.'))


def cmp_version(a, b):
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
    ## Stream file contents in 64 KiB buffers to calculate SHA-256 with O(1) memory overhead
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def toml_minecraft(text):
    # Narrow parser, intentionally returns unknown for ambiguous/unfamiliar metadata.
    deps = []
    blocks = re.split(r'(?m)^\s*(?=\[\[)', text)
    for block in blocks:
        if not re.match(r'\s*\[\[dependencies\.[^\]]+\]\]', block):
            continue
        mod = re.findall(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        ranges = re.findall(r'(?m)^\s*versionRange\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        if mod == ['minecraft']:
            deps.extend(ranges or ['unknown'])
    return deps


def inspect(path, target, loader):
    result = {'file': str(path), 'sha256': None, 'target_minecraft': target,
              'target_loader': loader, 'loader': None, 'minecraft_constraints': [],
              'status': 'unknown', 'notes': []}
    try:
        result['sha256'] = sha256(path)
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            names = [x.filename for x in infos]
            present = [name for name in META if name in names]
            if any(names.count(n) != 1 for n in present):
                raise ValueError('duplicate metadata entries')
            if len(present) != 1:
                raise ValueError('expected exactly one recognized loader metadata file')
            info = z.getinfo(present[0])
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
    result['loader_match'] = result['loader'] == loader.lower()
    checks = [accepts(s, target) for s in result['minecraft_constraints']]
    if not result['loader_match']:
        result['status'] = 'incompatible'
        result['notes'].append('Declared loader differs from the target loader.')
    elif checks and all(c is False for c in checks):
        result['status'] = 'incompatible'
        result['notes'].append('Declared Minecraft version does not include the target.')
    elif checks and any(c is True for c in checks) and all(c is not None for c in checks):
        result['status'] = 'metadata_match_only'
        result['notes'].append('Metadata matches only; dependencies, APIs and actual gameplay are untested.')
    else:
        result['notes'].append('Minecraft version constraint is missing or not understood; compatibility is unknown.')
    result['notes'].append('This report does not install, modify, port or run a mod.')
    return result


def prism_target(path):
    d = json.loads(path.read_text(encoding='utf-8'))
    versions = {x.get('uid'): x.get('version') for x in d['components'] if isinstance(x, dict)}
    mc = versions.get('net.minecraft')
    loaders = [x for x, uid in [('fabric', 'net.fabricmc.fabric-loader'),
               ('neoforge', 'net.neoforged'), ('forge', 'net.minecraftforge')] if versions.get(uid)]
    if not isinstance(mc, str) or len(loaders) != 1:
        raise ValueError('Prism instance must identify Minecraft and exactly one supported loader')
    return mc, loaders[0]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('jar', type=Path, help='A mod JAR you already have; it is only read')
    p.add_argument('--instance', type=Path, help='Prism instance folder containing mmc-pack.json')
    p.add_argument('--minecraft', default='26.3', help='Target Minecraft version (default 26.3)')
    p.add_argument('--loader', default='fabric', choices=['fabric', 'forge', 'neoforge'])
    a = p.parse_args()
    if a.instance:
        try:
            a.minecraft, a.loader = prism_target(a.instance / 'mmc-pack.json')
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            p.error('Cannot read Prism instance: ' + str(e))
    result = inspect(a.jar, a.minecraft, a.loader)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'metadata_match_only' else 2


if __name__ == '__main__':
    sys.exit(main())
