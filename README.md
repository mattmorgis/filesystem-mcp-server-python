# Filesystem MCP Server (Python)

> This project aims to be a **feature-parity Python port** of the original Node.js [`filesystem`](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem) published by the Model Context Protocol org.

## Quick start

### 1. Install dependencies (Python 3.12+)

```bash
# create & activate a virtual-env (optional but recommended)
uv venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# install runtime + dev dependencies
uv sync
```

### 2. Launch the server

```bash
uv run main.py /absolute/path/to/allowed/dir1 /another/allowed/dir
```

You should see something like:

```
Secure MCP Filesystem Server running on stdio
Allowed directories: ['/absolute/path/to/allowed/dir1', '/another/allowed/dir']
```

The server now waits on **stdin/stdout** for MCP messages. You can:

1. attach an **MCP capable client** (e.g. [Claude Desktop](https://claude.ai/download) or the `mcp` CLI)

---

## Available tools

| Tool                        | Description                                                |
| --------------------------- | ---------------------------------------------------------- |
| `read_file`                 | Return the contents of a file (`head` / `tail` supported). |
| `read_multiple_files`       | Batch variant of `read_file`.                              |
| `write_file`                | Create / overwrite a file with new content.                |
| `edit_file`                 | Apply line-based replacements; returns a git-style diff.   |
| `create_directory`          | `mkdir -p` semantics.                                      |
| `list_directory`            | One-level listing distinguishing files / directories.      |
| `list_directory_with_sizes` | Listing + size + summary, sortable by name/size.           |
| `directory_tree`            | Recursive JSON tree – handy for LLM context.               |
| `move_file`                 | Move or rename a file / directory.                         |
| `search_files`              | Case-insensitive glob-less substring search.               |
| `get_file_info`             | Stat a path (size, timestamps, permissions, …).            |
| `list_allowed_directories`  | Return the server-side sandbox roots.                      |

---

## Development & testing

Run linters, type-checker and tests locally:

```bash
# formatting / style
uv run ruff check
uv run ruff format

# static types (strict mode)
uv run mypy .

# pytest with asyncio auto mode
uv run pytest
```
