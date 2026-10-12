"""Governed, read-only MCP server ``estate``: agents look behind the wall of the simulated estate.

* ``tools.py``  - the tool functions (no MCP dependency, so they are unit-testable).
* ``audit.py``  - append-only JSON Lines audit trail (``runtime/logs/mcp-audit.jsonl``).
* ``server.py`` - registers the tools with FastMCP and serves them over stdio.
"""
