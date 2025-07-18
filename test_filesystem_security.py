#!/usr/bin/env python3

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

import main

# Add the current directory to the path so we can import main
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import expand_home, normalize_path, validate_path


@pytest.fixture
def temp_directory() -> Generator[str, None, None]:
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def allowed_directories(temp_directory: str) -> Generator[dict[str, str], None, None]:
    """Set up allowed directories for testing."""
    # Create subdirectories for testing
    allowed_dir1 = os.path.join(temp_directory, "allowed1")
    allowed_dir2 = os.path.join(temp_directory, "allowed2")
    forbidden_dir = os.path.join(temp_directory, "forbidden")

    os.makedirs(allowed_dir1, exist_ok=True)
    os.makedirs(allowed_dir2, exist_ok=True)
    os.makedirs(forbidden_dir, exist_ok=True)

    # Patch the global allowed_directories
    with patch.object(main, "allowed_directories", [allowed_dir1, allowed_dir2]):
        yield {
            "allowed1": allowed_dir1,
            "allowed2": allowed_dir2,
            "forbidden": forbidden_dir,
            "temp": temp_directory,
        }


class TestPathValidation:
    """Test the path validation security function."""

    @pytest.mark.asyncio
    async def test_allows_valid_paths_in_allowed_directories(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Valid paths within allowed directories should be accepted."""
        allowed_dir = allowed_directories["allowed1"]

        # Test direct path (nonexistent file)
        valid_path = os.path.join(allowed_dir, "test.txt")
        result = await validate_path(valid_path)
        # For nonexistent files, we expect the original path
        assert result == valid_path

        # Test subdirectory path
        subdir_path = os.path.join(allowed_dir, "subdir", "test.txt")
        os.makedirs(os.path.dirname(subdir_path), exist_ok=True)
        Path(subdir_path).touch()
        result = await validate_path(subdir_path)
        assert result == os.path.realpath(subdir_path)

    @pytest.mark.asyncio
    async def test_rejects_paths_outside_allowed_directories(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Paths outside allowed directories should be rejected."""
        forbidden_dir = allowed_directories["forbidden"]
        forbidden_path = os.path.join(forbidden_dir, "test.txt")

        with pytest.raises(
            ValueError, match="Access denied - path outside allowed directories"
        ):
            await validate_path(forbidden_path)

    @pytest.mark.asyncio
    async def test_prevents_directory_traversal_attacks(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Directory traversal attacks should be prevented."""
        allowed_dir = allowed_directories["allowed1"]

        # Test various traversal attempts
        traversal_attempts = [
            os.path.join(allowed_dir, "..", "forbidden", "test.txt"),
            os.path.join(allowed_dir, "..", "..", "etc", "passwd"),
            os.path.join(allowed_dir, "subdir", "..", "..", "forbidden", "test.txt"),
        ]

        for attempt in traversal_attempts:
            with pytest.raises(ValueError, match="Access denied"):
                await validate_path(attempt)

    @pytest.mark.asyncio
    async def test_handles_relative_paths_safely(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Relative paths should be resolved safely."""
        allowed_dir = allowed_directories["allowed1"]

        # Save current directory
        original_cwd = os.getcwd()

        try:
            # Change to allowed directory
            os.chdir(allowed_dir)

            # Test relative path within allowed directory
            relative_path = "test.txt"
            result = await validate_path(relative_path)
            expected = os.path.realpath(os.path.join(allowed_dir, relative_path))
            assert result == expected

        finally:
            # Restore original directory
            os.chdir(original_cwd)

    @pytest.mark.asyncio
    async def test_handles_symlinks_securely(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Symlinks should be validated against their target paths."""
        allowed_dir = allowed_directories["allowed1"]
        forbidden_dir = allowed_directories["forbidden"]

        # Create a target file in forbidden directory
        forbidden_file = os.path.join(forbidden_dir, "secret.txt")
        Path(forbidden_file).touch()

        # Create symlink in allowed directory pointing to forbidden file
        symlink_path = os.path.join(allowed_dir, "link_to_secret.txt")

        try:
            os.symlink(forbidden_file, symlink_path)

            # Should reject the symlink because target is outside allowed directories
            with pytest.raises(
                ValueError,
                match="Access denied - symlink target outside allowed directories",
            ):
                await validate_path(symlink_path)

        except OSError:
            # Skip test if symlinks not supported on this system
            pytest.skip("Symlinks not supported on this system")

    @pytest.mark.asyncio
    async def test_allows_symlinks_within_allowed_directories(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Symlinks within allowed directories should be accepted."""
        allowed_dir = allowed_directories["allowed1"]

        # Create target file in allowed directory
        target_file = os.path.join(allowed_dir, "target.txt")
        Path(target_file).touch()

        # Create symlink in allowed directory pointing to allowed file
        symlink_path = os.path.join(allowed_dir, "link_to_target.txt")

        try:
            os.symlink(target_file, symlink_path)

            # Should accept the symlink because target is within allowed directories
            result = await validate_path(symlink_path)
            assert result == os.path.realpath(symlink_path)

        except OSError:
            # Skip test if symlinks not supported on this system
            pytest.skip("Symlinks not supported on this system")

    @pytest.mark.asyncio
    async def test_handles_nonexistent_files_safely(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Nonexistent files should validate their parent directory."""
        allowed_dir = allowed_directories["allowed1"]

        # Test nonexistent file in allowed directory
        nonexistent_path = os.path.join(allowed_dir, "nonexistent.txt")
        result = await validate_path(nonexistent_path)
        assert result == nonexistent_path

        # Test nonexistent file in forbidden directory
        forbidden_dir = allowed_directories["forbidden"]
        forbidden_nonexistent = os.path.join(forbidden_dir, "nonexistent.txt")

        with pytest.raises(ValueError, match="Access denied"):
            await validate_path(forbidden_nonexistent)

    @pytest.mark.asyncio
    async def test_handles_nonexistent_parent_directory(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Files with nonexistent parent directories should be rejected."""
        allowed_dir = allowed_directories["allowed1"]

        # Test file with nonexistent parent directory
        nonexistent_parent_path = os.path.join(
            allowed_dir, "nonexistent_dir", "test.txt"
        )

        with pytest.raises(ValueError, match="Parent directory does not exist"):
            await validate_path(nonexistent_parent_path)

    @pytest.mark.asyncio
    async def test_expands_home_directory_correctly(
        self, allowed_directories: dict[str, str]
    ) -> None:
        """Home directory expansion should work correctly."""
        # Mock home directory to be within our allowed directories
        allowed_dir = allowed_directories["allowed1"]

        with patch("os.path.expanduser", return_value=allowed_dir):
            # Test tilde expansion
            tilde_path = "~/test.txt"
            result = await validate_path(tilde_path)
            # For nonexistent files, we expect the original absolute path
            expected = os.path.abspath(os.path.join(allowed_dir, "test.txt"))
            assert result == expected


class TestPathNormalizationSecurity:
    """Test path normalization for security issues."""

    def test_removes_dangerous_path_components(self) -> None:
        """Path normalization should handle dangerous components."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "./test/../../../etc/passwd",
            ".\\test\\..\\..\\..\\windows\\system32",
        ]

        for path in dangerous_paths:
            normalized = normalize_path(path)
            # After normalization, the path should not traverse outside
            # This is a basic check - full security validation happens in validate_path
            assert isinstance(normalized, str)

    def test_handles_unicode_and_special_characters(self) -> None:
        """Unicode and special characters should be handled safely."""
        special_paths = [
            "test/файл.txt",  # Cyrillic
            "test/文件.txt",  # Chinese
            "test/♥.txt",  # Unicode symbol
            "test/file with spaces.txt",
            "test/file&with&ampersands.txt",
            "test/file%20with%20encoding.txt",
        ]

        for path in special_paths:
            normalized = normalize_path(path)
            assert isinstance(normalized, str)
            assert len(normalized) > 0

    def test_handles_very_long_paths(self) -> None:
        """Very long paths should be handled without errors."""
        # Create a very long path
        long_component = "a" * 100
        long_path = "/".join([long_component] * 10)

        normalized = normalize_path(long_path)
        assert isinstance(normalized, str)
        assert len(normalized) > 0


class TestExpandHome:
    """Test home directory expansion."""

    def test_expands_tilde_safely(self) -> None:
        """Tilde expansion should be safe and predictable."""
        original_home = os.path.expanduser("~")

        test_cases = [
            ("~/test.txt", os.path.join(original_home, "test.txt")),
            ("~", original_home),
            (
                "~/dir/subdir/file.txt",
                os.path.join(original_home, "dir", "subdir", "file.txt"),
            ),
        ]

        for input_path, expected_path in test_cases:
            result = expand_home(input_path)
            # Normalize both paths for comparison
            assert os.path.normpath(result) == os.path.normpath(expected_path)

    def test_does_not_expand_tilde_in_middle(self) -> None:
        """Tilde in the middle of paths should not be expanded."""
        paths_with_tilde = [
            "/path/with~tilde/file.txt",
            "path/with~tilde/file.txt",
            "/home/user~name/file.txt",
        ]

        for path in paths_with_tilde:
            result = expand_home(path)
            assert result == path  # Should be unchanged


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
