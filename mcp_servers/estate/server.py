"""Read-only, audited MCP server ``estate`` (stdio).

Started by VS Code from ``.vscode/mcp.json``::

    <venv python> -m mcp_servers.estate.server

stdout is the MCP channel, so this process logs to stderr only.
"""

import logging
import sys

from mcp.server.fastmcp import FastMCP

from mcp_servers.estate import tools

INSTRUCTIONS = (
    "Read-only, audited view behind the UI of the simulated Contoso payout estate (synthetic data). "
    "Use it to verify what really happened in a payout run: control DB status and step exit codes, "
    "VM lifecycle, files on the shares, payout totals and the payment file, logs and configuration. "
    "Every call is written to runtime/logs/mcp-audit.jsonl. Nothing here can change the estate."
)

logger = logging.getLogger("mcp_servers.estate")


def build_server() -> FastMCP:
    """Create the FastMCP server and register the read-only tools."""
    server = FastMCP("estate", instructions=INSTRUCTIONS)
    annotations = None
    try:  # Tool annotations need a recent SDK; older SDKs simply skip them.
        from mcp.types import ToolAnnotations

        annotations = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                                      openWorldHint=False)
    except ImportError:  # pragma: no cover - depends on the installed SDK version
        pass
    for function in tools.TOOLS:
        if annotations is not None:
            try:
                server.add_tool(function, annotations=annotations)
                continue
            except TypeError:  # pragma: no cover - SDK without the annotations parameter
                pass
        server.add_tool(function)
    return server


mcp = build_server()


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tools.configure()
    logger.info("estate MCP server starting (stdio, %d read-only tools)", len(tools.TOOLS))
    mcp.run()


if __name__ == "__main__":
    main()
