"""moonglade_mcp.py -- a stand-in for the MCP server, kept for one release (3.20).

The MCP server moved to moonglade/mcp_server.py in 3.20 and runs as
`python -m moonglade.mcp_server`. An MCP client starts it by the command it was registered
with, and the existing registrations name this file's path, so this file keeps them working
until they are updated (see moonglade/mcp_server.py for the new registration).

It prints nothing of its own: an MCP server's stdout is the protocol.

Goes in 3.21, with the other stand-ins.
"""
if __name__ != "__main__":          # imported by old code: run nothing, say where it went
    raise ImportError("moonglade_mcp moved to moonglade.mcp_server")

import runpy

runpy.run_module("moonglade.mcp_server", run_name="__main__", alter_sys=True)
