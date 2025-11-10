#!/usr/bin/env python3
"""
Prepare pybrid-computing package for Cython compilation.

This script:
1. Copies the entire pybrid/ package to a temporary build directory
2. Renames .py files to .pyx (except __init__.py and protobuf files)
3. Generates a setup.py from a template with Extension objects
4. Extracts metadata from pyproject.toml
"""

import os
import shutil
import sys
from pathlib import Path
from typing import List, Dict, Any
import tomllib
from jinja2 import Template


# Files to exclude from Cython compilation (keep as .py)
EXCLUDE_FROM_COMPILATION = [
    "__init__.py",           # Keep all __init__.py as Python
    "main_pb2.py",          # Protobuf-generated files
]

# Patterns to exclude
EXCLUDE_PATTERNS = [
    "*_pb2.py",             # All protobuf-generated files
]


def should_exclude_file(file_path: Path) -> bool:
    """Check if a file should be excluded from Cython compilation."""
    # Check exact filename matches
    if file_path.name in EXCLUDE_FROM_COMPILATION:
        return True

    # Check pattern matches
    for pattern in EXCLUDE_PATTERNS:
        if file_path.match(pattern):
            return True

    return False


def copy_and_transform_package(source_dir: Path, build_dir: Path) -> List[str]:
    """
    Copy package to build directory and transform .py -> .pyx where appropriate.

    Returns:
        List of module paths that were converted to .pyx (for Extension generation)
    """
    pyx_modules = []

    # Remove build dir if it exists
    if build_dir.exists():
        shutil.rmtree(build_dir)

    # Copy entire package
    shutil.copytree(source_dir, build_dir)

    # Find all .py files and rename to .pyx (except excluded ones)
    for py_file in build_dir.rglob("*.py"):
        if should_exclude_file(py_file):
            print(f"  Keeping as .py: {py_file.relative_to(build_dir)}")
            continue

        # Rename to .pyx
        pyx_file = py_file.with_suffix(".pyx")
        py_file.rename(pyx_file)

        # Calculate module path (e.g., "pybrid.base.transport.serial")
        rel_path = pyx_file.relative_to(build_dir.parent)
        module_path = str(rel_path.with_suffix("")).replace(os.sep, ".")
        pyx_modules.append(module_path)

        print(f"  Converted: {py_file.relative_to(build_dir)} -> {pyx_file.name}")

    return sorted(pyx_modules)


def extract_metadata(pyproject_path: Path) -> Dict[str, Any]:
    """Extract package metadata from pyproject.toml."""
    with open(pyproject_path, "rb") as f:
        pyproject = tomllib.load(f)

    project = pyproject["project"]

    metadata = {
        "name": project["name"],
        "version": project["version"],
        "description": project["description"],
        "author": project["authors"][0]["name"] if project.get("authors") else "",
        "author_email": project["authors"][0]["email"] if project.get("authors") else "",
        "url": project.get("homepage", ""),
        "license": project.get("license", ""),
        "classifiers": project.get("classifiers", []),
        "python_requires": project.get("requires-python", ">=3.11"),
        "install_requires": project.get("dependencies", []),
        "entry_points": {},
    }

    # Extract entry points
    if "scripts" in project:
        metadata["entry_points"]["console_scripts"] = [
            f"{name} = {target}"
            for name, target in project["scripts"].items()
        ]

    return metadata


def generate_setup_py(template_path: Path, output_path: Path, metadata: Dict[str, Any], modules: List[str]):
    """Generate setup.py from template."""
    with open(template_path, "r") as f:
        template = Template(f.read())

    setup_content = template.render(
        metadata=metadata,
        modules=modules,
    )

    with open(output_path, "w") as f:
        f.write(setup_content)

    print(f"\nGenerated setup.py with {len(modules)} extensions")


def generate_build_pyproject_toml(output_path: Path, metadata: Dict[str, Any]):
    """Generate a minimal pyproject.toml for the build directory with Cython as a build requirement."""
    # Format dependencies as TOML array
    deps_toml = "[\n"
    for dep in metadata['install_requires']:
        deps_toml += f'    "{dep}",\n'
    deps_toml += "]"

    pyproject_content = f"""# Generated pyproject.toml for binary build
# This file declares build-time dependencies including Cython

[build-system]
requires = [
    "setuptools >= 40.8.0",
    "wheel",
    "Cython >= 3.1.6",
]
build-backend = "setuptools.build_meta"

[project]
name = "{metadata['name']}"
version = "{metadata['version']}"
description = "{metadata['description']}"
requires-python = "{metadata['python_requires']}"
dependencies = {deps_toml}

[project.scripts]
"""

    # Add console scripts if they exist
    if metadata['entry_points'].get('console_scripts'):
        for script in metadata['entry_points']['console_scripts']:
            name, target = script.split(' = ')
            pyproject_content += f'{name} = "{target}"\n'

    with open(output_path, "w") as f:
        f.write(pyproject_content)

    print(f"Generated pyproject.toml with Cython build requirement")


def main():
    # Paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    source_dir = project_root / "pybrid"
    build_dir = project_root / "build-temp" / "pybrid"
    template_path = script_dir / "setup.py.template"
    output_setup = project_root / "build-temp" / "setup.py"
    pyproject_path = project_root / "pyproject.toml"

    print("="*70)
    print("Preparing pybrid-computing for Cython compilation")
    print("="*70)

    # Verify source directory exists
    if not source_dir.exists():
        print(f"ERROR: Source directory not found: {source_dir}")
        sys.exit(1)

    # Verify template exists
    if not template_path.exists():
        print(f"ERROR: Template not found: {template_path}")
        sys.exit(1)

    # Step 1: Copy and transform package
    print(f"\nStep 1: Copying and transforming package...")
    print(f"  Source: {source_dir}")
    print(f"  Build:  {build_dir}")
    pyx_modules = copy_and_transform_package(source_dir, build_dir)
    print(f"\n  Converted {len(pyx_modules)} modules to .pyx")

    # Step 2: Extract metadata
    print(f"\nStep 2: Extracting metadata from pyproject.toml...")
    metadata = extract_metadata(pyproject_path)
    print(f"  Package: {metadata['name']} v{metadata['version']}")
    print(f"  Dependencies: {len(metadata['install_requires'])}")

    # Step 3: Generate pyproject.toml with build requirements
    print(f"\nStep 3: Generating pyproject.toml with build requirements...")
    output_pyproject = project_root / "build-temp" / "pyproject.toml"
    generate_build_pyproject_toml(output_pyproject, metadata)

    # Step 4: Generate setup.py
    print(f"\nStep 4: Generating setup.py...")
    generate_setup_py(template_path, output_setup, metadata, pyx_modules)

    # Copy additional files
    print(f"\nStep 5: Copying additional files...")
    files_to_copy = ["README.md", "LICENSE"]
    for filename in files_to_copy:
        src = project_root / filename
        if src.exists():
            dst = project_root / "build-temp" / filename
            shutil.copy2(src, dst)
            print(f"  Copied: {filename}")

    print("\n" + "="*70)
    print("Preparation complete!")
    print("="*70)
    print(f"\nBuild directory: {project_root / 'build-temp'}")
    print(f"Setup.py: {output_setup}")
    print(f"Extensions: {len(pyx_modules)}")
    print("\nNext step: Run 'python setup.py build_ext' or use cibuildwheel")


if __name__ == "__main__":
    main()
