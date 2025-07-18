#!/usr/bin/env python3

import os
import tempfile
from pathlib import Path
from typing import Dict, Generator, List, Union
from unittest.mock import patch

import pytest

from path_utils import expand_home, normalize_path

# Type alias for test directory fixture
TestDirectories = Dict[str, Union[str, List[str]]]


async def validate_path_with_allowed(
    requested_path: str, allowed_dirs: list[str]
) -> str:
    """Test version of validate_path that takes allowed directories as parameter."""
    expanded_path = expand_home(requested_path)
    absolute = os.path.abspath(expanded_path)
    normalized_requested = normalize_path(absolute)

    # Normalize allowed directories to their real paths for consistent comparison
    normalized_allowed_dirs = [
        normalize_path(os.path.realpath(dir_path)) for dir_path in allowed_dirs
    ]

    # Check if path is within allowed directories (use real path for comparison)
    try:
        real_requested_path = os.path.realpath(absolute)
        normalized_real_requested = normalize_path(real_requested_path)
    except OSError:
        # If we can't get the real path, use the normalized absolute path
        normalized_real_requested = normalized_requested

    is_allowed = any(
        normalized_real_requested.startswith(dir_path)
        for dir_path in normalized_allowed_dirs
    )
    if not is_allowed:
        raise ValueError(
            f"Access denied - path outside allowed directories: {absolute} not in {', '.join(allowed_dirs)}"
        )

    # For nonexistent files, check that the parent directory exists
    if not os.path.exists(absolute):
        parent_dir = os.path.dirname(absolute)
        if not os.path.exists(parent_dir):
            raise ValueError(f"Parent directory does not exist: {parent_dir}")

    # Handle symlinks by checking their real path
    try:
        real_path = os.path.realpath(absolute)
        normalized_real = normalize_path(real_path)
        is_real_path_allowed = any(
            normalized_real.startswith(dir_path) for dir_path in normalized_allowed_dirs
        )
        if not is_real_path_allowed:
            raise ValueError(
                "Access denied - symlink target outside allowed directories"
            )
        return real_path
    except OSError:
        # For new files that don't exist yet, verify parent directory
        parent_dir = os.path.dirname(absolute)

        # Check if parent directory actually exists
        if not os.path.exists(parent_dir):
            raise ValueError(f"Parent directory does not exist: {parent_dir}")

        try:
            real_parent_path = os.path.realpath(parent_dir)
            normalized_parent = normalize_path(real_parent_path)
            is_parent_allowed = any(
                normalized_parent.startswith(dir_path)
                for dir_path in normalized_allowed_dirs
            )
            if not is_parent_allowed:
                raise ValueError(
                    "Access denied - parent directory outside allowed directories"
                )
            return absolute
        except OSError:
            raise ValueError(f"Parent directory does not exist: {parent_dir}")


@pytest.fixture
def temp_directory() -> Generator[str, None, None]:
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def test_directories(temp_directory: str) -> TestDirectories:
    """Set up test directories."""
    allowed_dir1 = os.path.join(temp_directory, "allowed1")
    allowed_dir2 = os.path.join(temp_directory, "allowed2")
    forbidden_dir = os.path.join(temp_directory, "forbidden")

    os.makedirs(allowed_dir1, exist_ok=True)
    os.makedirs(allowed_dir2, exist_ok=True)
    os.makedirs(forbidden_dir, exist_ok=True)

    return {
        "allowed_dirs": [allowed_dir1, allowed_dir2],
        "allowed1": allowed_dir1,
        "allowed2": allowed_dir2,
        "forbidden": forbidden_dir,
        "temp": temp_directory,
    }


class TestPathValidationCore:
    """Test the core path validation functionality."""

    async def test_allows_valid_paths_in_allowed_directories(
        self, test_directories: TestDirectories
    ) -> None:
        """Valid paths within allowed directories should be accepted."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Test direct path
        valid_path = os.path.join(allowed_dir, "test.txt")
        result = await validate_path_with_allowed(valid_path, allowed_dirs)
        assert result == os.path.realpath(valid_path)

        # Test subdirectory path
        subdir_path = os.path.join(allowed_dir, "subdir", "test.txt")
        os.makedirs(os.path.dirname(subdir_path), exist_ok=True)
        Path(subdir_path).touch()
        result = await validate_path_with_allowed(subdir_path, allowed_dirs)
        assert result == os.path.realpath(subdir_path)

    async def test_rejects_paths_outside_allowed_directories(
        self, test_directories: TestDirectories
    ) -> None:
        """Paths outside allowed directories should be rejected."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        forbidden_dir = test_directories["forbidden"]
        assert isinstance(forbidden_dir, str)
        forbidden_path = os.path.join(forbidden_dir, "test.txt")

        with pytest.raises(
            ValueError, match="Access denied - path outside allowed directories"
        ):
            await validate_path_with_allowed(forbidden_path, allowed_dirs)

    async def test_prevents_directory_traversal_attacks(
        self, test_directories: TestDirectories
    ) -> None:
        """Directory traversal attacks should be prevented."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Test various traversal attempts
        traversal_attempts = [
            os.path.join(allowed_dir, "..", "forbidden", "test.txt"),
            os.path.join(allowed_dir, "..", "..", "etc", "passwd"),
            os.path.join(allowed_dir, "subdir", "..", "..", "forbidden", "test.txt"),
        ]

        for attempt in traversal_attempts:
            with pytest.raises(ValueError, match="Access denied"):
                await validate_path_with_allowed(attempt, allowed_dirs)

    async def test_handles_relative_paths_safely(
        self, test_directories: TestDirectories
    ) -> None:
        """Relative paths should be resolved safely."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Save current directory
        original_cwd = os.getcwd()

        try:
            # Change to allowed directory
            os.chdir(allowed_dir)

            # Test relative path within allowed directory
            relative_path = "test.txt"
            result = await validate_path_with_allowed(relative_path, allowed_dirs)
            expected = os.path.realpath(os.path.join(allowed_dir, relative_path))
            assert result == expected

        finally:
            # Restore original directory
            os.chdir(original_cwd)

    async def test_handles_symlinks_securely(
        self, test_directories: TestDirectories
    ) -> None:
        """Symlinks should be validated against their target paths."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)
        forbidden_dir = test_directories["forbidden"]
        assert isinstance(forbidden_dir, str)

        # Create a target file in forbidden directory
        forbidden_file = os.path.join(forbidden_dir, "secret.txt")
        Path(forbidden_file).touch()

        # Create symlink in allowed directory pointing to forbidden file
        symlink_path = os.path.join(allowed_dir, "link_to_secret.txt")

        try:
            os.symlink(forbidden_file, symlink_path)

            # Should reject the symlink because target is outside allowed directories
            with pytest.raises(ValueError, match="Access denied"):
                await validate_path_with_allowed(symlink_path, allowed_dirs)

        except OSError:
            # Skip test if symlinks not supported on this system
            pytest.skip("Symlinks not supported on this system")

    async def test_allows_symlinks_within_allowed_directories(
        self, test_directories: TestDirectories
    ) -> None:
        """Symlinks within allowed directories should be accepted."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Create target file in allowed directory
        target_file = os.path.join(allowed_dir, "target.txt")
        Path(target_file).touch()

        # Create symlink in allowed directory pointing to allowed file
        symlink_path = os.path.join(allowed_dir, "link_to_target.txt")

        try:
            os.symlink(target_file, symlink_path)

            # Should accept the symlink because target is within allowed directories
            result = await validate_path_with_allowed(symlink_path, allowed_dirs)
            assert result == os.path.realpath(symlink_path)

        except OSError:
            # Skip test if symlinks not supported on this system
            pytest.skip("Symlinks not supported on this system")

    async def test_handles_nonexistent_files_safely(
        self, test_directories: TestDirectories
    ) -> None:
        """Nonexistent files should validate their parent directory."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Test nonexistent file in allowed directory
        nonexistent_path = os.path.join(allowed_dir, "nonexistent.txt")
        result = await validate_path_with_allowed(nonexistent_path, allowed_dirs)
        # The result might be the real path version due to symlink resolution
        assert (
            nonexistent_path in result or os.path.basename(result) == "nonexistent.txt"
        )

        # Test nonexistent file in forbidden directory
        forbidden_dir = test_directories["forbidden"]
        assert isinstance(forbidden_dir, str)
        forbidden_nonexistent = os.path.join(forbidden_dir, "nonexistent.txt")

        with pytest.raises(ValueError, match="Access denied"):
            await validate_path_with_allowed(forbidden_nonexistent, allowed_dirs)

    async def test_handles_nonexistent_parent_directory(
        self, test_directories: TestDirectories
    ) -> None:
        """Files with nonexistent parent directories should be rejected."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Test file with nonexistent parent directory
        nonexistent_parent_path = os.path.join(
            allowed_dir, "nonexistent_dir", "test.txt"
        )

        with pytest.raises(ValueError, match="Parent directory does not exist"):
            await validate_path_with_allowed(nonexistent_parent_path, allowed_dirs)

    async def test_expands_home_directory_correctly(
        self, test_directories: TestDirectories
    ) -> None:
        """Home directory expansion should work correctly."""
        allowed_dirs = test_directories["allowed_dirs"]
        assert isinstance(allowed_dirs, list)
        allowed_dir = test_directories["allowed1"]
        assert isinstance(allowed_dir, str)

        # Mock home directory to be within our allowed directories
        with patch("os.path.expanduser", return_value=allowed_dir):
            # Test tilde expansion
            tilde_path = "~/test.txt"
            result = await validate_path_with_allowed(tilde_path, allowed_dirs)
            expected = os.path.realpath(os.path.join(allowed_dir, "test.txt"))
            assert result == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
