#!/usr/bin/env python3

import asyncio
import difflib
import json
import os
import shutil
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    TextContent,
    Tool,
)
from pydantic import BaseModel, Field


class ReadFileArgs(BaseModel):
    path: str
    tail: Optional[int] = Field(
        None, description="If provided, returns only the last N lines of the file"
    )
    head: Optional[int] = Field(
        None, description="If provided, returns only the first N lines of the file"
    )


class ReadMultipleFilesArgs(BaseModel):
    paths: List[str]


class WriteFileArgs(BaseModel):
    path: str
    content: str


class EditOperation(BaseModel):
    oldText: str = Field(description="Text to search for - must match exactly")
    newText: str = Field(description="Text to replace with")


class EditFileArgs(BaseModel):
    path: str
    edits: List[EditOperation]
    dryRun: bool = Field(
        False, description="Preview changes using git-style diff format"
    )


class CreateDirectoryArgs(BaseModel):
    path: str


class ListDirectoryArgs(BaseModel):
    path: str


class ListDirectoryWithSizesArgs(BaseModel):
    path: str
    sortBy: str = Field("name", description="Sort entries by name or size")


class DirectoryTreeArgs(BaseModel):
    path: str


class MoveFileArgs(BaseModel):
    source: str
    destination: str


class SearchFilesArgs(BaseModel):
    path: str
    pattern: str
    excludePatterns: List[str] = Field(default_factory=list)


class GetFileInfoArgs(BaseModel):
    path: str


@dataclass
class FileInfo:
    size: int
    created: str
    modified: str
    accessed: str
    isDirectory: bool
    isFile: bool
    permissions: str


# Global variables for allowed directories
allowed_directories: List[str] = []


def normalize_path(p: str) -> str:
    """Normalize a path consistently."""
    return os.path.normpath(p)


def expand_home(filepath: str) -> str:
    """Expand ~ to home directory."""
    if filepath.startswith("~/") or filepath == "~":
        return os.path.join(os.path.expanduser("~"), filepath[1:].lstrip("/"))
    return filepath


async def validate_path(requested_path: str) -> str:
    """Validate that a path is within allowed directories."""
    expanded_path = expand_home(requested_path)
    absolute = os.path.abspath(expanded_path)
    normalized_requested = normalize_path(absolute)

    # Normalize allowed directories to their real paths for consistent comparison
    normalized_allowed_dirs = [
        normalize_path(os.path.realpath(dir_path)) for dir_path in allowed_directories
    ]

    # Check if path is within allowed directories
    # For symlinks, we need to check the symlink path itself first, not its target
    if os.path.islink(absolute):
        # For symlinks, get the real path of the symlink location (not target)
        symlink_parent = os.path.dirname(absolute)
        try:
            real_symlink_parent = os.path.realpath(symlink_parent)
            real_symlink_path = os.path.join(
                real_symlink_parent, os.path.basename(absolute)
            )
            normalized_symlink = normalize_path(real_symlink_path)
        except OSError:
            normalized_symlink = normalized_requested

        # Check if the symlink itself is in an allowed directory
        is_symlink_allowed = any(
            normalized_symlink.startswith(dir_path)
            for dir_path in normalized_allowed_dirs
        )
        if not is_symlink_allowed:
            raise ValueError(
                f"Access denied - path outside allowed directories: {absolute} not in {', '.join(allowed_directories)}"
            )
    else:
        # For non-symlinks, get the real path for comparison
        try:
            real_requested_path = os.path.realpath(absolute)
            normalized_real_requested = normalize_path(real_requested_path)
        except OSError:
            # If we can't get the real path, use the normalized absolute path
            normalized_real_requested = normalized_requested

        # Check if the path is within allowed directories
        is_path_allowed = any(
            normalized_real_requested.startswith(dir_path)
            for dir_path in normalized_allowed_dirs
        )

        # If the path isn't even in an allowed directory, reject immediately
        if not is_path_allowed:
            raise ValueError(
                f"Access denied - path outside allowed directories: {absolute} not in {', '.join(allowed_directories)}"
            )

    # For nonexistent files, check that the parent directory exists
    if not os.path.exists(absolute):
        parent_dir = os.path.dirname(absolute)
        if not os.path.exists(parent_dir):
            raise ValueError(f"Parent directory does not exist: {parent_dir}")

    # Handle symlinks by checking their real path
    if os.path.islink(absolute):
        try:
            real_path = os.path.realpath(absolute)
            normalized_real = normalize_path(real_path)
            is_real_path_allowed = any(
                normalized_real.startswith(dir_path)
                for dir_path in normalized_allowed_dirs
            )
            if not is_real_path_allowed:
                raise ValueError(
                    "Access denied - symlink target outside allowed directories"
                )
            return real_path
        except OSError:
            raise ValueError("Access denied - could not resolve symlink")

    # For regular files that exist, resolve their real path
    if os.path.exists(absolute):
        try:
            real_path = os.path.realpath(absolute)
            return real_path
        except OSError:
            return absolute

    # For nonexistent files, handle parent directory validation
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


def normalize_line_endings(text: str) -> str:
    """Normalize line endings to LF."""
    return text.replace("\r\n", "\n")


def create_unified_diff(
    original_content: str, new_content: str, filepath: str = "file"
) -> str:
    """Create a unified diff between two strings."""
    normalized_original = normalize_line_endings(original_content)
    normalized_new = normalize_line_endings(new_content)

    diff = difflib.unified_diff(
        normalized_original.splitlines(keepends=True),
        normalized_new.splitlines(keepends=True),
        fromfile=f"{filepath} (original)",
        tofile=f"{filepath} (modified)",
        lineterm="",
    )
    return "".join(diff)


async def apply_file_edits(
    file_path: str, edits: List[EditOperation], dry_run: bool = False
) -> str:
    """Apply a series of edits to a file."""
    # Read file content and normalize line endings
    with open(file_path, "r", encoding="utf-8") as f:
        content = normalize_line_endings(f.read())

    # Apply edits sequentially
    modified_content = content
    for edit in edits:
        normalized_old = normalize_line_endings(edit.oldText)
        normalized_new = normalize_line_endings(edit.newText)

        # If exact match exists, use it
        if normalized_old in modified_content:
            modified_content = modified_content.replace(normalized_old, normalized_new)
            continue

        # Otherwise, try line-by-line matching with flexibility for whitespace
        old_lines = normalized_old.split("\n")
        content_lines = modified_content.split("\n")
        match_found = False

        for i in range(len(content_lines) - len(old_lines) + 1):
            potential_match = content_lines[i : i + len(old_lines)]

            # Compare lines with normalized whitespace
            is_match = all(
                old_line.strip() == content_line.strip()
                for old_line, content_line in zip(old_lines, potential_match)
            )

            if is_match:
                # Preserve original indentation of first line
                original_indent = content_lines[i][
                    : len(content_lines[i]) - len(content_lines[i].lstrip())
                ]
                new_lines = normalized_new.split("\n")

                if new_lines:
                    new_lines[0] = original_indent + new_lines[0].lstrip()
                    # For subsequent lines, preserve relative indentation
                    for j in range(1, len(new_lines)):
                        if j < len(old_lines):
                            old_indent = old_lines[j][
                                : len(old_lines[j]) - len(old_lines[j].lstrip())
                            ]
                            new_indent = new_lines[j][
                                : len(new_lines[j]) - len(new_lines[j].lstrip())
                            ]
                            if old_indent and new_indent:
                                relative_indent = len(new_indent) - len(old_indent)
                                new_lines[j] = (
                                    original_indent
                                    + " " * max(0, relative_indent)
                                    + new_lines[j].lstrip()
                                )

                content_lines[i : i + len(old_lines)] = new_lines
                modified_content = "\n".join(content_lines)
                match_found = True
                break

        if not match_found:
            raise ValueError(f"Could not find exact match for edit:\n{edit.oldText}")

    # Create unified diff
    diff = create_unified_diff(content, modified_content, file_path)

    # Format diff with code blocks
    formatted_diff = f"```diff\n{diff}```\n\n"

    if not dry_run:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(modified_content)

    return formatted_diff


def format_size(bytes_count: int) -> str:
    """Format file size in human readable format."""
    units = ["B", "KB", "MB", "GB", "TB"]
    if bytes_count == 0:
        return "0 B"

    i = min(len(units) - 1, int(len(f"{bytes_count:b}") / 10))
    if i == 0:
        return f"{bytes_count} {units[i]}"

    return f"{bytes_count / (1024**i):.2f} {units[i]}"


async def tail_file(file_path: str, num_lines: int) -> str:
    """Get the last N lines of a file efficiently."""
    with open(file_path, "rb") as f:
        # Go to end of file
        f.seek(0, 2)
        file_size = f.tell()

        if file_size == 0:
            return ""

        # Read chunks from the end
        chunk_size = 1024
        lines: List[str] = []
        lines_found = 0
        position = file_size

        while position > 0 and lines_found < num_lines:
            chunk_size = min(chunk_size, position)
            position -= chunk_size
            f.seek(position)

            chunk = f.read(chunk_size).decode("utf-8", errors="ignore")
            chunk_lines = normalize_line_endings(chunk).split("\n")

            # If not at beginning of file, first line might be incomplete
            if position > 0:
                chunk_lines = chunk_lines[1:]

            # Add lines from end
            for line in reversed(chunk_lines):
                if lines_found < num_lines:
                    lines.insert(0, line)
                    lines_found += 1

        return "\n".join(lines[:num_lines])


async def head_file(file_path: str, num_lines: int) -> str:
    """Get the first N lines of a file efficiently."""
    lines = []
    with open(file_path, "r", encoding="utf-8") as f:
        for _ in range(num_lines):
            line = f.readline()
            if not line:
                break
            lines.append(line.rstrip("\n\r"))

    return "\n".join(lines)


async def get_file_stats(file_path: str) -> FileInfo:
    """Get detailed file statistics."""
    stat = os.stat(file_path)
    return FileInfo(
        size=stat.st_size,
        created=str(stat.st_ctime),
        modified=str(stat.st_mtime),
        accessed=str(stat.st_atime),
        isDirectory=os.path.isdir(file_path),
        isFile=os.path.isfile(file_path),
        permissions=oct(stat.st_mode)[-3:],
    )


async def search_files(
    root_path: str, pattern: str, exclude_patterns: Optional[List[str]] = None
) -> List[str]:
    """Recursively search for files matching a pattern."""
    if exclude_patterns is None:
        exclude_patterns = []

    results = []

    for root, dirs, files in os.walk(root_path):
        try:
            await validate_path(root)
        except ValueError:
            continue

        # Check directories and files
        for name in dirs + files:
            full_path = os.path.join(root, name)

            try:
                await validate_path(full_path)
            except ValueError:
                continue

            # Check exclude patterns
            relative_path = os.path.relpath(full_path, root_path)
            should_exclude = any(
                pattern in relative_path or name in pattern
                for pattern in exclude_patterns
            )

            if should_exclude:
                continue

            if pattern.lower() in name.lower():
                results.append(full_path)

    return results


# Initialize MCP server
server: Server = Server("secure-filesystem-server")  # type: ignore[type-arg]


@server.list_tools()  # type: ignore[misc,no-untyped-call]
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="read_file",
            description=(
                "Read the complete contents of a file from the file system. "
                "Handles various text encodings and provides detailed error messages "
                "if the file cannot be read. Use this tool when you need to examine "
                "the contents of a single file. Use the 'head' parameter to read only "
                "the first N lines of a file, or the 'tail' parameter to read only "
                "the last N lines of a file. Only works within allowed directories."
            ),
            inputSchema=ReadFileArgs.model_json_schema(),
        ),
        Tool(
            name="read_multiple_files",
            description=(
                "Read the contents of multiple files simultaneously. This is more "
                "efficient than reading files one by one when you need to analyze "
                "or compare multiple files. Each file's content is returned with its "
                "path as a reference. Failed reads for individual files won't stop "
                "the entire operation. Only works within allowed directories."
            ),
            inputSchema=ReadMultipleFilesArgs.model_json_schema(),
        ),
        Tool(
            name="write_file",
            description=(
                "Create a new file or completely overwrite an existing file with new content. "
                "Use with caution as it will overwrite existing files without warning. "
                "Handles text content with proper encoding. Only works within allowed directories."
            ),
            inputSchema=WriteFileArgs.model_json_schema(),
        ),
        Tool(
            name="edit_file",
            description=(
                "Make line-based edits to a text file. Each edit replaces exact line sequences "
                "with new content. Returns a git-style diff showing the changes made. "
                "Only works within allowed directories."
            ),
            inputSchema=EditFileArgs.model_json_schema(),
        ),
        Tool(
            name="create_directory",
            description=(
                "Create a new directory or ensure a directory exists. Can create multiple "
                "nested directories in one operation. If the directory already exists, "
                "this operation will succeed silently. Perfect for setting up directory "
                "structures for projects or ensuring required paths exist. Only works within allowed directories."
            ),
            inputSchema=CreateDirectoryArgs.model_json_schema(),
        ),
        Tool(
            name="list_directory",
            description=(
                "Get a detailed listing of all files and directories in a specified path. "
                "Results clearly distinguish between files and directories with [FILE] and [DIR] "
                "prefixes. This tool is essential for understanding directory structure and "
                "finding specific files within a directory. Only works within allowed directories."
            ),
            inputSchema=ListDirectoryArgs.model_json_schema(),
        ),
        Tool(
            name="list_directory_with_sizes",
            description=(
                "Get a detailed listing of all files and directories in a specified path, including sizes. "
                "Results clearly distinguish between files and directories with [FILE] and [DIR] "
                "prefixes. This tool is useful for understanding directory structure and "
                "finding specific files within a directory. Only works within allowed directories."
            ),
            inputSchema=ListDirectoryWithSizesArgs.model_json_schema(),
        ),
        Tool(
            name="directory_tree",
            description=(
                "Get a recursive tree view of files and directories as a JSON structure. "
                "Each entry includes 'name', 'type' (file/directory), and 'children' for directories. "
                "Files have no children array, while directories always have a children array (which may be empty). "
                "The output is formatted with 2-space indentation for readability. Only works within allowed directories."
            ),
            inputSchema=DirectoryTreeArgs.model_json_schema(),
        ),
        Tool(
            name="move_file",
            description=(
                "Move or rename files and directories. Can move files between directories "
                "and rename them in a single operation. If the destination exists, the "
                "operation will fail. Works across different directories and can be used "
                "for simple renaming within the same directory. Both source and destination must be within allowed directories."
            ),
            inputSchema=MoveFileArgs.model_json_schema(),
        ),
        Tool(
            name="search_files",
            description=(
                "Recursively search for files and directories matching a pattern. "
                "Searches through all subdirectories from the starting path. The search "
                "is case-insensitive and matches partial names. Returns full paths to all "
                "matching items. Great for finding files when you don't know their exact location. "
                "Only searches within allowed directories."
            ),
            inputSchema=SearchFilesArgs.model_json_schema(),
        ),
        Tool(
            name="get_file_info",
            description=(
                "Retrieve detailed metadata about a file or directory. Returns comprehensive "
                "information including size, creation time, last modified time, permissions, "
                "and type. This tool is perfect for understanding file characteristics "
                "without reading the actual content. Only works within allowed directories."
            ),
            inputSchema=GetFileInfoArgs.model_json_schema(),
        ),
        Tool(
            name="list_allowed_directories",
            description=(
                "Returns the list of directories that this server is allowed to access. "
                "Use this to understand which directories are available before trying to access files."
            ),
            inputSchema={},
        ),
    ]


@server.call_tool()  # type: ignore[misc,no-untyped-call]
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls."""
    try:
        if name == "read_file":
            read_args = ReadFileArgs.model_validate(arguments)

            if read_args.head and read_args.tail:
                raise ValueError(
                    "Cannot specify both head and tail parameters simultaneously"
                )

            valid_path = await validate_path(read_args.path)

            if read_args.tail:
                content = await tail_file(valid_path, read_args.tail)
            elif read_args.head:
                content = await head_file(valid_path, read_args.head)
            else:
                with open(valid_path, "r", encoding="utf-8") as f:
                    content = f.read()

            return [TextContent(type="text", text=content)]

        elif name == "read_multiple_files":
            multi_read_args = ReadMultipleFilesArgs.model_validate(arguments)
            results = []

            for file_path in multi_read_args.paths:
                try:
                    valid_path = await validate_path(file_path)
                    with open(valid_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    results.append(f"{file_path}:\n{content}\n")
                except Exception as e:
                    results.append(f"{file_path}: Error - {str(e)}")

            return [TextContent(type="text", text="\n---\n".join(results))]

        elif name == "write_file":
            write_args = WriteFileArgs.model_validate(arguments)
            valid_path = await validate_path(write_args.path)

            with open(valid_path, "w", encoding="utf-8") as f:
                f.write(write_args.content)

            return [
                TextContent(
                    type="text", text=f"Successfully wrote to {write_args.path}"
                )
            ]

        elif name == "edit_file":
            edit_args = EditFileArgs.model_validate(arguments)
            valid_path = await validate_path(edit_args.path)
            result = await apply_file_edits(
                valid_path, edit_args.edits, edit_args.dryRun
            )

            return [TextContent(type="text", text=result)]

        elif name == "create_directory":
            create_args = CreateDirectoryArgs.model_validate(arguments)
            valid_path = await validate_path(create_args.path)

            os.makedirs(valid_path, exist_ok=True)

            return [
                TextContent(
                    type="text",
                    text=f"Successfully created directory {create_args.path}",
                )
            ]

        elif name == "list_directory":
            list_args = ListDirectoryArgs.model_validate(arguments)
            valid_path = await validate_path(list_args.path)

            dir_entries = []
            for entry in os.listdir(valid_path):
                entry_path = os.path.join(valid_path, entry)
                if os.path.isdir(entry_path):
                    dir_entries.append(f"[DIR] {entry}")
                else:
                    dir_entries.append(f"[FILE] {entry}")

            return [TextContent(type="text", text="\n".join(dir_entries))]

        elif name == "list_directory_with_sizes":
            sizes_args = ListDirectoryWithSizesArgs.model_validate(arguments)
            valid_path = await validate_path(sizes_args.path)

            size_entries: List[tuple[str, bool, int, float]] = []
            total_files = 0
            total_dirs = 0
            total_size = 0

            for entry in os.listdir(valid_path):
                entry_path = os.path.join(valid_path, entry)
                try:
                    stat = os.stat(entry_path)
                    if os.path.isdir(entry_path):
                        size_entries.append((entry, True, 0, stat.st_mtime))
                        total_dirs += 1
                    else:
                        size_entries.append((entry, False, stat.st_size, stat.st_mtime))
                        total_files += 1
                        total_size += stat.st_size
                except OSError:
                    size_entries.append((entry, os.path.isdir(entry_path), 0, 0.0))

            # Sort entries
            if sizes_args.sortBy == "size":
                size_entries.sort(key=lambda x: x[2], reverse=True)
            else:
                size_entries.sort(key=lambda x: x[0])

            # Format output
            formatted_entries = []
            for name, is_dir, size, _ in size_entries:
                prefix = "[DIR]" if is_dir else "[FILE]"
                size_str = "" if is_dir else format_size(size).rjust(10)
                formatted_entries.append(f"{prefix} {name.ljust(30)} {size_str}")

            # Add summary
            summary = [
                "",
                f"Total: {total_files} files, {total_dirs} directories",
                f"Combined size: {format_size(total_size)}",
            ]

            return [
                TextContent(type="text", text="\n".join(formatted_entries + summary))
            ]

        elif name == "directory_tree":
            tree_args = DirectoryTreeArgs.model_validate(arguments)

            async def build_tree(current_path: str) -> List[Dict[str, Any]]:
                valid_path = await validate_path(current_path)
                result: List[Dict[str, Any]] = []

                for entry in os.listdir(valid_path):
                    entry_path = os.path.join(current_path, entry)
                    entry_data: Dict[str, Any] = {
                        "name": entry,
                        "type": "directory" if os.path.isdir(entry_path) else "file",
                    }

                    if os.path.isdir(entry_path):
                        entry_data["children"] = await build_tree(entry_path)

                    result.append(entry_data)

                return result

            tree_data = await build_tree(tree_args.path)
            return [TextContent(type="text", text=json.dumps(tree_data, indent=2))]

        elif name == "move_file":
            move_args = MoveFileArgs.model_validate(arguments)
            valid_source = await validate_path(move_args.source)
            valid_dest = await validate_path(move_args.destination)

            shutil.move(valid_source, valid_dest)

            return [
                TextContent(
                    type="text",
                    text=f"Successfully moved {move_args.source} to {move_args.destination}",
                )
            ]

        elif name == "search_files":
            search_args = SearchFilesArgs.model_validate(arguments)
            valid_path = await validate_path(search_args.path)
            results = await search_files(
                valid_path, search_args.pattern, search_args.excludePatterns
            )

            if results:
                return [TextContent(type="text", text="\n".join(results))]
            else:
                return [TextContent(type="text", text="No matches found")]

        elif name == "get_file_info":
            info_args = GetFileInfoArgs.model_validate(arguments)
            valid_path = await validate_path(info_args.path)

            info = await get_file_stats(valid_path)
            info_text = "\n".join(
                [
                    f"size: {info.size}",
                    f"created: {info.created}",
                    f"modified: {info.modified}",
                    f"accessed: {info.accessed}",
                    f"isDirectory: {info.isDirectory}",
                    f"isFile: {info.isFile}",
                    f"permissions: {info.permissions}",
                ]
            )

            return [TextContent(type="text", text=info_text)]

        elif name == "list_allowed_directories":
            return [
                TextContent(
                    type="text",
                    text="Allowed directories:\n" + "\n".join(allowed_directories),
                )
            ]

        else:
            raise ValueError(f"Unknown tool: {name}")

    except Exception as e:
        return [TextContent(type="text", text=f"Error: {str(e)}")]


async def main() -> None:
    """Main entry point."""
    global allowed_directories

    # Parse command line arguments
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: python main.py <allowed-directory> [additional-directories...]",
            file=sys.stderr,
        )
        sys.exit(1)

    # Normalize and validate all allowed directories
    for directory in args:
        expanded_dir = expand_home(directory)
        if not os.path.exists(expanded_dir):
            print(f"Error: Directory {directory} does not exist", file=sys.stderr)
            sys.exit(1)
        if not os.path.isdir(expanded_dir):
            print(f"Error: {directory} is not a directory", file=sys.stderr)
            sys.exit(1)

        normalized_dir = normalize_path(os.path.abspath(expanded_dir))
        allowed_directories.append(normalized_dir)

    print("Secure MCP Filesystem Server running on stdio", file=sys.stderr)
    print(f"Allowed directories: {allowed_directories}", file=sys.stderr)

    # Run the server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
