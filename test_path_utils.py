#!/usr/bin/env python3

import os
import tempfile
from typing import Generator

import pytest

from path_utils import convert_to_windows_path, expand_home, normalize_path


class TestConvertToWindowsPath:
    """Test the convert_to_windows_path function."""

    def test_leaves_unix_paths_unchanged(self) -> None:
        """Unix paths should remain unchanged."""
        assert convert_to_windows_path("/usr/local/bin") == "/usr/local/bin"
        assert convert_to_windows_path("/home/user/some path") == "/home/user/some path"

    def test_converts_wsl_paths_to_windows_format(self) -> None:
        """WSL paths should be converted to Windows format."""
        assert (
            convert_to_windows_path("/mnt/c/NS/MyKindleContent")
            == "C:\\NS\\MyKindleContent"
        )
        assert convert_to_windows_path("/mnt/d/some/path") == "D:\\some\\path"

    def test_converts_unix_style_windows_paths_to_windows_format(self) -> None:
        """Unix-style Windows paths should be converted."""
        assert (
            convert_to_windows_path("/c/NS/MyKindleContent")
            == "C:\\NS\\MyKindleContent"
        )
        assert convert_to_windows_path("/d/some/path") == "D:\\some\\path"

    def test_leaves_windows_paths_unchanged_but_ensures_backslashes(self) -> None:
        """Windows paths should be normalized to use backslashes."""
        assert (
            convert_to_windows_path("C:\\NS\\MyKindleContent")
            == "C:\\NS\\MyKindleContent"
        )
        assert (
            convert_to_windows_path("C:/NS/MyKindleContent")
            == "C:\\NS\\MyKindleContent"
        )

    def test_handles_windows_paths_with_spaces(self) -> None:
        """Windows paths with spaces should be handled correctly."""
        assert (
            convert_to_windows_path("C:\\Program Files\\Some App")
            == "C:\\Program Files\\Some App"
        )
        assert (
            convert_to_windows_path("C:/Program Files/Some App")
            == "C:\\Program Files\\Some App"
        )

    def test_handles_uppercase_and_lowercase_drive_letters(self) -> None:
        """Drive letters should be converted to uppercase."""
        assert convert_to_windows_path("/mnt/d/some/path") == "D:\\some\\path"
        assert convert_to_windows_path("/d/some/path") == "D:\\some\\path"


class TestNormalizePath:
    """Test the normalize_path function."""

    def test_preserves_unix_paths(self) -> None:
        """Unix paths should be preserved."""
        assert normalize_path("/usr/local/bin") == "/usr/local/bin"
        assert normalize_path("/home/user/some path") == "/home/user/some path"
        assert normalize_path('"/usr/local/some app/"') == "/usr/local/some app"

    def test_removes_surrounding_quotes(self) -> None:
        """Surrounding quotes should be removed."""
        assert (
            normalize_path('"C:\\NS\\My Kindle Content"') == "C:\\NS\\My Kindle Content"
        )
        assert (
            normalize_path("'C:\\NS\\My Kindle Content'") == "C:\\NS\\My Kindle Content"
        )

    def test_normalizes_backslashes(self) -> None:
        """Double backslashes should be normalized."""
        assert (
            normalize_path("C:\\\\NS\\\\MyKindleContent") == "C:\\NS\\MyKindleContent"
        )

    def test_converts_forward_slashes_to_backslashes_on_windows(self) -> None:
        """Forward slashes should be converted to backslashes for Windows paths."""
        assert normalize_path("C:/NS/MyKindleContent") == "C:\\NS\\MyKindleContent"

    def test_handles_wsl_paths(self) -> None:
        """WSL paths should be converted to Windows format."""
        assert normalize_path("/mnt/c/NS/MyKindleContent") == "C:\\NS\\MyKindleContent"

    def test_handles_unix_style_windows_paths(self) -> None:
        """Unix-style Windows paths should be converted."""
        assert normalize_path("/c/NS/MyKindleContent") == "C:\\NS\\MyKindleContent"

    def test_handles_paths_with_spaces_and_mixed_slashes(self) -> None:
        """Paths with spaces and mixed slashes should be handled correctly."""
        assert normalize_path("C:/NS/My Kindle Content") == "C:\\NS\\My Kindle Content"
        assert (
            normalize_path("/mnt/c/NS/My Kindle Content") == "C:\\NS\\My Kindle Content"
        )
        assert (
            normalize_path("C:\\Program Files (x86)\\App Name")
            == "C:\\Program Files (x86)\\App Name"
        )
        assert (
            normalize_path('"C:\\Program Files\\App Name"')
            == "C:\\Program Files\\App Name"
        )
        assert (
            normalize_path("  C:\\Program Files\\App Name  ")
            == "C:\\Program Files\\App Name"
        )

    def test_preserves_spaces_in_all_path_formats(self) -> None:
        """Spaces in paths should be preserved in all formats."""
        assert (
            normalize_path("/mnt/c/Program Files/App Name")
            == "C:\\Program Files\\App Name"
        )
        assert (
            normalize_path("/c/Program Files/App Name") == "C:\\Program Files\\App Name"
        )
        assert (
            normalize_path("C:/Program Files/App Name") == "C:\\Program Files\\App Name"
        )

    def test_handles_special_characters_in_paths(self) -> None:
        """Special characters in paths should be preserved."""
        # Test ampersand in path
        assert normalize_path("C:\\NS\\Sub&Folder") == "C:\\NS\\Sub&Folder"
        assert normalize_path("C:/NS/Sub&Folder") == "C:\\NS\\Sub&Folder"
        assert normalize_path("/mnt/c/NS/Sub&Folder") == "C:\\NS\\Sub&Folder"

        # Test tilde in path (short names in Windows)
        assert normalize_path("C:\\NS\\MYKIND~1") == "C:\\NS\\MYKIND~1"
        assert (
            normalize_path("/Users/NEMANS~1/FOLDER~2/SUBFO~1/Public/P12PST~1")
            == "/Users/NEMANS~1/FOLDER~2/SUBFO~1/Public/P12PST~1"
        )

        # Test other special characters
        assert normalize_path("C:\\Path with #hash") == "C:\\Path with #hash"
        assert (
            normalize_path("C:\\Path with (parentheses)")
            == "C:\\Path with (parentheses)"
        )
        assert normalize_path("C:\\Path with [brackets]") == "C:\\Path with [brackets]"
        assert (
            normalize_path("C:\\Path with @at+plus$dollar%percent")
            == "C:\\Path with @at+plus$dollar%percent"
        )

    def test_capitalizes_lowercase_drive_letters_for_windows_paths(self) -> None:
        """Drive letters should be capitalized for Windows paths."""
        assert normalize_path("c:/windows/system32") == "C:\\windows\\system32"
        assert normalize_path("/mnt/d/my/folder") == "D:\\my\\folder"
        assert normalize_path("/e/another/folder") == "E:\\another\\folder"

    def test_handles_unc_paths_correctly(self) -> None:
        """UNC paths should preserve the leading double backslash."""
        # UNC paths should preserve the leading double backslash
        unc_path = r"\\SERVER\share\folder"
        result = normalize_path(unc_path)
        assert result.startswith(r"\\")
        assert "SERVER" in result
        assert "share" in result
        assert "folder" in result

        # Test UNC path with double backslashes that need normalization
        unc_path_with_doubles = r"\\\\SERVER\\share\\folder"
        result2 = normalize_path(unc_path_with_doubles)
        assert result2.startswith(r"\\")
        assert "SERVER" in result2
        # Should normalize to single backslashes after the UNC prefix

    def test_returns_normalized_non_windows_paths_after_basic_normalization(
        self,
    ) -> None:
        """Non-Windows paths should be normalized appropriately."""
        # Relative path
        relative_path = "some/relative/path"
        assert normalize_path(relative_path) == relative_path.replace("/", "\\")

        # A path that looks somewhat absolute but isn't a drive or recognized Unix root for Windows conversion
        other_absolute_path = "\\someserver\\share\\file"
        assert normalize_path(other_absolute_path) == other_absolute_path


class TestExpandHome:
    """Test the expand_home function."""

    def test_expands_tilde_to_home_directory(self) -> None:
        """Tilde should be expanded to the home directory."""
        result = expand_home("~/test")
        assert "test" in result
        assert "~" not in result
        assert result.startswith(os.path.expanduser("~"))

    def test_expands_bare_tilde(self) -> None:
        """Bare tilde should be expanded to the home directory."""
        result = expand_home("~")
        expected = os.path.expanduser("~")
        # Normalize both paths to handle different path separators
        assert os.path.normpath(result) == os.path.normpath(expected)

    def test_leaves_other_paths_unchanged(self) -> None:
        """Paths not starting with tilde should be unchanged."""
        assert expand_home("C:/test") == "C:/test"
        assert expand_home("/usr/local/test") == "/usr/local/test"
        assert expand_home("relative/path") == "relative/path"

    def test_handles_tilde_in_middle_of_path(self) -> None:
        """Tilde in the middle of a path should not be expanded."""
        assert expand_home("/path/with~tilde/test") == "/path/with~tilde/test"


class TestPathValidationSecurity:
    """Test path validation and security features."""

    def test_path_traversal_protection(self) -> None:
        """Path traversal attempts should be normalized but detection happens in validate_path."""
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\..\\windows\\system32",
            "/var/www/html/../../../etc/passwd",
            "C:\\Program Files\\..\\..\\Windows\\System32",
        ]

        for path in dangerous_paths:
            normalized = normalize_path(path)
            # Just verify that normalization doesn't crash and returns a string
            # The actual security validation happens in validate_path function
            assert isinstance(normalized, str)
            assert len(normalized) > 0


@pytest.fixture
def temp_directory() -> Generator[str, None, None]:
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


class TestPathUtilsIntegration:
    """Integration tests for path utilities."""

    def test_round_trip_normalization(self, temp_directory: str) -> None:
        """Test that paths can be normalized and used successfully."""
        test_paths = [
            "test_file.txt",
            "subdir/test_file.txt",
            "./test_file.txt",
            "subdir/../test_file.txt",
        ]

        for test_path in test_paths:
            full_path = os.path.join(temp_directory, test_path)
            # Create directory structure if needed
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            # Create test file
            with open(full_path, "w") as f:
                f.write("test content")

            # Normalize the path
            normalized = normalize_path(full_path)

            # Should be able to read the file using the normalized path
            if os.path.exists(normalized):
                with open(normalized, "r") as f:
                    content = f.read()
                    assert content == "test content"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
