#!/usr/bin/env python3

import os
import re


def convert_to_windows_path(p: str) -> str:
    """
    Converts WSL or Unix-style Windows paths to Windows format.

    Args:
        p: The path to convert

    Returns:
        Converted Windows path
    """
    # Handle WSL paths (/mnt/c/...)
    if p.startswith("/mnt/"):
        if len(p) > 5:
            drive_letter = p[5].upper()
            path_part = p[6:].replace("/", "\\")
            return f"{drive_letter}:{path_part}"

    # Handle Unix-style Windows paths (/c/...)
    if re.match(r"^/[a-zA-Z]/", p):
        drive_letter = p[1].upper()
        path_part = p[2:].replace("/", "\\")
        return f"{drive_letter}:{path_part}"

    # Handle standard Windows paths, ensuring backslashes
    if re.match(r"^[a-zA-Z]:", p):
        return p.replace("/", "\\")

    # Leave non-Windows paths unchanged
    return p


def normalize_path(p: str) -> str:
    """
    Normalizes path by standardizing format while preserving OS-specific behavior.

    Args:
        p: The path to normalize

    Returns:
        Normalized path
    """
    # Remove any surrounding quotes and whitespace
    p = p.strip().strip("\"'")

    # Check if this is a Unix path (starts with / but not a Windows or WSL path)
    is_unix_path = (
        p.startswith("/")
        and not re.match(r"^/mnt/[a-z]/", p, re.IGNORECASE)
        and not re.match(r"^/[a-zA-Z]/", p)
    )

    if is_unix_path:
        # For Unix paths, just normalize without converting to Windows format
        # Replace double slashes with single slashes and remove trailing slashes
        return re.sub(r"/+", "/", p).rstrip("/")

    # Convert WSL or Unix-style Windows paths to Windows format
    p = convert_to_windows_path(p)

    # Handle double backslashes, preserving leading UNC \\
    if p.startswith("\\\\"):
        # For UNC paths, handle excessive leading backslashes
        # Count leading backslashes
        leading_backslashes = 0
        for char in p:
            if char == "\\":
                leading_backslashes += 1
            else:
                break

        # Get the path after leading backslashes
        path_after_leading = p[leading_backslashes:]

        # Reconstruct with exactly 2 leading backslashes + normalized path
        rest_normalized = path_after_leading.replace("\\\\", "\\")
        p = "\\\\" + rest_normalized
    else:
        # For non-UNC paths, normalize all double backslashes
        p = p.replace("\\\\", "\\")

    # Use os.path.normpath for normalization, which handles . and .. segments
    try:
        normalized = os.path.normpath(p)

        # Fix UNC paths after normalization (normpath can affect UNC paths)
        if p.startswith("\\\\") and not normalized.startswith("\\\\"):
            normalized = "\\" + normalized

    except (OSError, ValueError):
        # If normpath can't handle it, do basic normalization
        normalized = p

    # Handle Windows paths: convert slashes and ensure drive letter is capitalized
    if re.match(r"^[a-zA-Z]:", normalized):
        result = normalized.replace("/", "\\")
        # Capitalize drive letter if present
        if re.match(r"^[a-z]:", result):
            result = result[0].upper() + result[1:]
        return result

    # For all other paths (including relative paths), convert forward slashes to backslashes
    # This ensures relative paths like "some/relative/path" become "some\\relative\\path"
    return normalized.replace("/", "\\")


def expand_home(filepath: str) -> str:
    """
    Expands home directory tildes in paths.

    Args:
        filepath: The path to expand

    Returns:
        Expanded path
    """
    if filepath.startswith("~/") or filepath == "~":
        return os.path.join(os.path.expanduser("~"), filepath[1:].lstrip("/"))
    return filepath


def normalize_path_cross_platform(p: str) -> str:
    """
    Cross-platform path normalization that respects the current OS.

    Args:
        p: The path to normalize

    Returns:
        Normalized path appropriate for the current OS
    """
    # Remove quotes and whitespace
    p = p.strip().strip("\"'")

    # On Windows, use our Windows-specific normalization
    if os.name == "nt":
        return normalize_path(p)

    # On Unix systems, use standard path normalization
    expanded = expand_home(p)
    return os.path.normpath(expanded)
