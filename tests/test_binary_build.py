"""
Tests for binary wheel build validation.

These tests verify that the built binary wheels:
1. Contain compiled extensions (.so/.pyd)
2. Don't expose source code (except __init__.py and _pb2.py)
3. Can be imported successfully
4. Have working CLI entry points
"""

import sys
import subprocess
import zipfile
from pathlib import Path
import pytest


# Find the project root and dist directory
PROJECT_ROOT = Path(__file__).parent.parent
DIST_DIR = PROJECT_ROOT / "dist"


def find_wheels():
    """Find all wheel files in the dist directory."""
    if not DIST_DIR.exists():
        return []
    return list(DIST_DIR.glob("*.whl"))


class TestBinaryWheelContents:
    """Test the contents of binary wheels."""

    @pytest.fixture
    def wheel_files(self):
        """Get list of wheel files to test."""
        wheels = find_wheels()
        if not wheels:
            pytest.skip("No wheels found in dist/ directory. Run build first.")
        return wheels

    def test_wheels_exist(self, wheel_files):
        """Test that at least one wheel was built."""
        assert len(wheel_files) > 0, "No wheels found in dist/"

    def test_wheel_has_compiled_extensions(self, wheel_files):
        """Test that wheels contain compiled extensions (.so on Linux, .pyd on Windows)."""
        for wheel_path in wheel_files:
            with zipfile.ZipFile(wheel_path, 'r') as zf:
                files = zf.namelist()

                # Check for compiled extensions
                so_files = [f for f in files if f.endswith('.so')]
                pyd_files = [f for f in files if f.endswith('.pyd')]
                compiled_files = so_files + pyd_files

                assert len(compiled_files) > 0, \
                    f"Wheel {wheel_path.name} contains no compiled extensions"

                print(f"\n{wheel_path.name}: Found {len(compiled_files)} compiled extensions")

    def test_wheel_has_no_source_code(self, wheel_files):
        """Test that wheels don't contain Python source code (except allowed files)."""
        allowed_patterns = [
            '__init__.py',      # Package initialization files
            '_pb2.py',          # Protobuf-generated files
            '__pycache__',      # Bytecode cache (shouldn't be there but allowed)
            '.dist-info',       # Wheel metadata
            '.data',            # Wheel data files
        ]

        for wheel_path in wheel_files:
            with zipfile.ZipFile(wheel_path, 'r') as zf:
                files = zf.namelist()

                # Find Python source files
                py_files = [f for f in files if f.endswith('.py')]

                # Filter out allowed files
                disallowed_files = []
                for py_file in py_files:
                    if not any(pattern in py_file for pattern in allowed_patterns):
                        disallowed_files.append(py_file)

                if disallowed_files:
                    print(f"\n{wheel_path.name}: Found disallowed source files:")
                    for f in disallowed_files:
                        print(f"  - {f}")

                assert len(disallowed_files) == 0, \
                    f"Wheel {wheel_path.name} contains {len(disallowed_files)} source files"

    def test_wheel_has_required_metadata(self, wheel_files):
        """Test that wheels have proper metadata."""
        for wheel_path in wheel_files:
            with zipfile.ZipFile(wheel_path, 'r') as zf:
                files = zf.namelist()

                # Check for dist-info directory
                dist_info_dirs = [f for f in files if '.dist-info/' in f]
                assert len(dist_info_dirs) > 0, \
                    f"Wheel {wheel_path.name} missing .dist-info directory"

                # Check for METADATA file
                metadata_files = [f for f in files if 'METADATA' in f]
                assert len(metadata_files) > 0, \
                    f"Wheel {wheel_path.name} missing METADATA file"

    def test_wheel_size_reasonable(self, wheel_files):
        """Test that wheel sizes are reasonable (not too large)."""
        MAX_SIZE_MB = 100  # Maximum expected size in MB

        for wheel_path in wheel_files:
            size_mb = wheel_path.stat().st_size / (1024 * 1024)
            print(f"\n{wheel_path.name}: {size_mb:.2f} MB")

            assert size_mb < MAX_SIZE_MB, \
                f"Wheel {wheel_path.name} is too large: {size_mb:.2f} MB"


class TestBinaryWheelFunctionality:
    """Test that the binary wheels work correctly."""

    @pytest.fixture
    def wheel_files(self):
        """Get list of wheel files to test."""
        wheels = find_wheels()
        if not wheels:
            pytest.skip("No wheels found in dist/ directory. Run build first.")
        return wheels

    def test_wheel_installable(self, wheel_files, tmp_path):
        """Test that wheels can be installed in a clean virtualenv."""
        # This test requires being run outside of a build environment
        # It's more of an integration test
        pytest.skip("Requires manual testing with fresh virtualenv")

    def test_import_pybrid(self):
        """Test that pybrid can be imported."""
        # Only run if we're testing an installed wheel
        try:
            import pybrid
            assert pybrid is not None
            print(f"\nSuccessfully imported pybrid from: {pybrid.__file__}")
        except ImportError:
            pytest.skip("pybrid not installed - test only runs on installed wheels")

    def test_cli_entry_point(self):
        """Test that the pybrid CLI entry point works."""
        try:
            result = subprocess.run(
                ["pybrid", "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            assert result.returncode == 0, "pybrid --help failed"
            assert "pybrid" in result.stdout.lower() or "usage" in result.stdout.lower()
            print(f"\nCLI entry point works")
        except FileNotFoundError:
            pytest.skip("pybrid command not found - test only runs on installed wheels")


class TestCythonAsyncSupport:
    """Test that Cython-compiled async functions work correctly."""

    def test_coroutine_detection(self):
        """Test that async functions are properly detected as coroutines."""
        pytest.skip("Requires installed wheel with async functionality")

    def test_async_transport(self):
        """Test that async transport layer works."""
        pytest.skip("Requires hardware or mocking - manual test")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
