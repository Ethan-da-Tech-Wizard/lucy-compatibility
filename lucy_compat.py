#!/usr/bin/env python3
# Program: lucy-compatibility - lucy_compat.py
# Programmer: Ethan-da-Tech-Wizard (written with Claude, an AI assistant)
# Last Modified: 2026-11-18
# Purpose: Reads a Minecraft mod JAR (without running it) and reports whether its declared loader and Minecraft version match a target.

"""Read-only mod metadata compatibility report. Does not load or execute JARs."""
# ==============================================================================
# SECTION 1: IMPORTS
# These are standard-library modules only, so nothing extra needs installing.
# argparse reads command-line options, hashlib makes SHA-256 fingerprints,
# json parses JSON text, re does pattern matching, sys gives the exit code,
# and zipfile opens JAR files (a JAR is just a ZIP archive).
# ==============================================================================
import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

# ==============================================================================
# SECTION 2: CONSTANTS
# ==============================================================================
# MAX_META is the biggest metadata file we are willing to read (1 MiB), so a
# hostile or broken JAR cannot make the program eat all of the memory.
# META lists the metadata file names we recognize inside a JAR: Fabric uses
# fabric.mod.json, NeoForge uses neoforge.mods.toml, Forge uses mods.toml.
MAX_META = 1024 * 1024
META = ('fabric.mod.json', 'META-INF/neoforge.mods.toml', 'META-INF/mods.toml')


# ==============================================================================
# SECTION 3: VERSION HELPERS
# ==============================================================================
def version(v):
    """Turn a version string like "1.21.1" into a tuple (1, 21, 1), or return None if it is not plain dotted numbers."""
    # Anything that is not a string of digits separated by dots is rejected.
    if not isinstance(v, str) or not re.fullmatch(r'\d+(?:\.\d+)*', v):
        return None
    # Split on dots and convert each piece to a whole number so versions compare correctly.
    return tuple(int(x) for x in v.split('.'))


def cmp_version(a, b):
    """Compare two version tuples: return -1 if a is older, 0 if equal, 1 if a is newer."""
    # Pad the shorter tuple with zeros so 1.21 and 1.21.0 are treated as equal.
    n = max(len(a), len(b))
    a, b = a + (0,) * (n-len(a)), b + (0,) * (n-len(b))
    # Python trick: True/False count as 1/0, so this yields -1, 0 or 1.
    return (a > b) - (a < b)


def accepts(spec, target):
    """Known Maven ranges and exact numeric versions; uncertainty stays unknown."""
    t = version(target)
    if t is None or not isinstance(spec, str):
        return None
    # Remove stray spaces around the requirement text.
    spec = spec.strip()
    # First check whether the requirement is a single exact version.
    v = version(spec)
    # An exact version only accepts the target when they are equal.
    if v is not None:
        return cmp_version(t, v) == 0
    # Otherwise try to read a Maven-style range such as [1.21.1,1.21.2): the first bracket says whether the low end is included, the last says the same for the high end.
    m = re.fullmatch(r'([\[(])\s*(\d+(?:\.\d+)*)?\s*,\s*(\d+(?:\.\d+)*)?\s*([\])])', spec)
    # If it is not a range we understand (or both ends are empty), answer None meaning "unknown".
    if not m or (not m[2] and not m[3]):
        return None
    # Check the lower bound: the target must not be below it, and must not equal it when the bound is exclusive "(".
    if m[2]:
        c = cmp_version(t, version(m[2]))
        if c < 0 or (c == 0 and m[1] == '('):
            return False
    # Check the upper bound the same way: target must not be above it, nor equal when the bound is exclusive ")".
    if m[3]:
        c = cmp_version(t, version(m[3]))
        if c > 0 or (c == 0 and m[4] == ')'):
            return False
    # The target passed every bound, so this requirement accepts it.
    return True


# ==============================================================================
# SECTION 4: FILE FINGERPRINT AND TOML PARSING
# ==============================================================================
def sha256(path):
    """Return the SHA-256 hex fingerprint of the file at path, reading it in 1 MiB pieces so big files do not fill memory."""
    # Create the hash object that we feed the file bytes into.
    h = hashlib.sha256()
    with path.open('rb') as f:
        # Keep reading until the file runs out.
        while True:
            chunk = f.read(1024 * 1024)
            # An empty chunk means end of file, so stop.
            if not chunk:
                break
            # Add this piece of the file to the running hash.
            h.update(chunk)
    return h.hexdigest()


def toml_minecraft(text):
    """Pull the Minecraft version ranges out of a Forge/NeoForge mods.toml text; return ['unknown'] entries when a range is missing."""
    # Narrow parser, intentionally returns unknown for ambiguous/unfamiliar metadata.
    # This list collects every Minecraft version range found.
    deps = []
    # Cut the text into blocks, each starting at a [[...]] table header.
    blocks = re.split(r'(?m)^\s*(?=\[\[)', text)
    # Look at each block one at a time.
    for block in blocks:
        # Skip blocks that are not [[dependencies.something]] tables.
        if not re.match(r'\s*\[\[dependencies\.[^\]]+\]\]', block):
            continue
        # Find the modId value inside this block.
        mod = re.findall(r'(?m)^\s*modId\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        # Find the versionRange value inside this block.
        ranges = re.findall(r'(?m)^\s*versionRange\s*=\s*["\']([^"\']+)["\']\s*(?:#.*)?$', block)
        # Only keep ranges from the dependency whose modId is exactly minecraft.
        if mod == ['minecraft']:
            deps.extend(ranges or ['unknown'])
    # Hand back the ranges (possibly empty).
    return deps


# ==============================================================================
# SECTION 5: MAIN INSPECTION LOGIC
# ==============================================================================
def inspect(path, target, loader):
    """Open one mod JAR read-only and return a dict describing its loader, Minecraft constraints and a compatibility status."""
    # Start with a result dict where everything is "unknown" until we learn otherwise.
    result = {'file': str(path), 'sha256': None, 'target_minecraft': target,
              'target_loader': loader, 'loader': None, 'minecraft_constraints': [],
              'status': 'unknown', 'notes': []}
    # Wrap all file reading in try so a broken JAR becomes a note instead of a crash.
    try:
        # Record the JAR fingerprint so the report can be tied to the exact file.
        result['sha256'] = sha256(path)
        # Open the JAR as a ZIP archive (this only reads it).
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            # List the names of every file inside the archive.
            names = [x.filename for x in infos]
            # Find which of the known metadata files exist.
            present = [name for name in META if name in names]
            # A metadata name that appears twice is ambiguous and could hide something, so refuse it.
            if any(names.count(n) != 1 for n in present):
                raise ValueError('duplicate metadata entries')
            # We need exactly one recognized metadata file to know the loader.
            if len(present) != 1:
                raise ValueError('expected exactly one recognized loader metadata file')
            # Get the ZIP entry details for that metadata file.
            info = z.getinfo(present[0])
            # Refuse metadata files larger than the size limit.
            if info.file_size > MAX_META:
                raise ValueError('metadata exceeds size limit')
            # Read the metadata file and decode it as UTF-8 text.
            text = z.read(info).decode('utf-8')
            # Fabric metadata is JSON, so parse it as JSON.
            if present[0] == 'fabric.mod.json':
                result['loader'] = 'fabric'
                data = json.loads(text)
                result['mod_id'] = data.get('id')
                # Look up the Minecraft requirement under "depends".
                spec = data.get('depends', {}).get('minecraft')
                # Always store constraints as a list: use the list as-is, wrap a single value, or use an empty list if missing.
                result['minecraft_constraints'] = spec if isinstance(spec, list) else ([spec] if spec else [])
            # Anything else is a Forge or NeoForge TOML file; the file name tells us which.
            else:
                result['loader'] = 'neoforge' if 'neoforge' in present[0] else 'forge'
                result['minecraft_constraints'] = toml_minecraft(text)
    # If anything went wrong while reading, record why and return early with status "unknown".
    except (OSError, zipfile.BadZipFile, ValueError, UnicodeError, json.JSONDecodeError, AttributeError, TypeError) as e:
        result['notes'].append('Cannot inspect metadata: ' + str(e))
        return result
    # Does the loader declared in the JAR equal the loader we are targeting?
    result['loader_match'] = result['loader'] == loader.lower()
    # Test every Minecraft requirement against the target version (True, False or None for unknown).
    checks = [accepts(s, target) for s in result['minecraft_constraints']]
    # Wrong loader: the mod cannot work on the target.
    if not result['loader_match']:
        result['status'] = 'incompatible'
        result['notes'].append('Declared loader differs from the target loader.')
    # Every requirement rejects the target version: incompatible.
    elif checks and all(c is False for c in checks):
        result['status'] = 'incompatible'
        result['notes'].append('Declared Minecraft version does not include the target.')
    # At least one requirement accepts and none are unknown: metadata matches (this is not proof it works).
    elif checks and any(c is True for c in checks) and all(c is not None for c in checks):
        result['status'] = 'metadata_match_only'
        result['notes'].append('Metadata matches only; dependencies, APIs and actual gameplay are untested.')
    # Otherwise we cannot tell, so we say so honestly and keep status "unknown".
    else:
        result['notes'].append('Minecraft version constraint is missing or not understood; compatibility is unknown.')
    # Always remind the reader that this tool only reads files.
    result['notes'].append('This report does not install, modify, port or run a mod.')
    return result


# ==============================================================================
# SECTION 6: PRISM LAUNCHER AND COMMAND-LINE ENTRY POINT
# ==============================================================================
def prism_target(path):
    """Read a Prism Launcher mmc-pack.json and return the (minecraft version, loader name) the instance uses."""
    # Load the instance's JSON file.
    d = json.loads(path.read_text(encoding='utf-8'))
    # Build a lookup from component id (uid) to its version.
    versions = {x.get('uid'): x.get('version') for x in d['components'] if isinstance(x, dict)}
    # The Minecraft version of this instance.
    mc = versions.get('net.minecraft')
    # Collect which supported loaders (fabric, neoforge, forge) the instance has installed.
    loaders = [x for x, uid in [('fabric', 'net.fabricmc.fabric-loader'),
               ('neoforge', 'net.neoforged'), ('forge', 'net.minecraftforge')] if versions.get(uid)]
    # The instance must name a Minecraft version and exactly one loader, otherwise we cannot choose a target.
    if not isinstance(mc, str) or len(loaders) != 1:
        raise ValueError('Prism instance must identify Minecraft and exactly one supported loader')
    return mc, loaders[0]


def main():
    """Parse command-line options, inspect the JAR and print the JSON report; return 0 only on a metadata match, otherwise 2."""
    # Set up the command-line parser, reusing the module docstring as the help text.
    p = argparse.ArgumentParser(description=__doc__)
    # The one required argument: the JAR file to inspect.
    p.add_argument('jar', type=Path, help='A mod JAR you already have; it is only read')
    # Optional: a Prism instance folder whose settings override the options below.
    p.add_argument('--instance', type=Path, help='Prism instance folder containing mmc-pack.json')
    # Target Minecraft version (default 26.3 as written in the code).
    p.add_argument('--minecraft', default='26.3', help='Target Minecraft version (default 26.3)')
    # Target loader, limited to the three supported choices.
    p.add_argument('--loader', default='fabric', choices=['fabric', 'forge', 'neoforge'])
    # Read what the user typed on the command line.
    a = p.parse_args()
    # If a Prism instance was given, take the version and loader from it instead.
    if a.instance:
        try:
            a.minecraft, a.loader = prism_target(a.instance / 'mmc-pack.json')
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            p.error('Cannot read Prism instance: ' + str(e))
    # Run the inspection.
    result = inspect(a.jar, a.minecraft, a.loader)
    # Print the report as readable JSON.
    print(json.dumps(result, indent=2))
    # Exit code 0 means a metadata match; 2 means incompatible or unknown.
    return 0 if result['status'] == 'metadata_match_only' else 2


# Run main() only when this file is executed directly, not when imported (the tests import it).
if __name__ == '__main__':
    sys.exit(main())
