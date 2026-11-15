"""Read-only connection checks. Report counts and tool names, never response bodies."""

import asyncio
import json


async def probe(name, command, tool):
    proc = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, limit=8 * 1024 * 1024)
    try:
        async def message(method, params, request_id=None):
            request = {"jsonrpc": "2.0", "method": method, "params": params}
            if request_id is not None:
                request["id"] = request_id
            proc.stdin.write(json.dumps(request).encode() + b"\n")
            await proc.stdin.drain()
            if request_id is None:
                return None
            while line := await proc.stdout.readline():
                response = json.loads(line)
                if response.get("id") == request_id:
                    if "error" in response:
                        raise ValueError(f"{name}: {method} returned an MCP error")
                    return response["result"]
            raise ValueError(f"{name}: server stopped before it answered {method}")

        async with asyncio.timeout(90):
            await message("initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "agent-setup-check", "version": "1"}}, 1)
            await message("notifications/initialized", {})
            tools = (await message("tools/list", {}, 2))["tools"]
            print(f"{name}: connected, {len(tools)} tools")
            if tool:
                if tool["name"] not in {t["name"] for t in tools}:
                    raise ValueError(f"{name}: configured read-only check tool is missing")
                result = await message("tools/call", tool, 3)
                if result.get("isError") or not result.get("content"):
                    raise ValueError(f"{name}: {tool['name']} failed; check VPN and account access")
                for block in result["content"]:
                    if block.get("type") == "text":
                        try:
                            data = json.loads(block["text"])
                        except ValueError:
                            continue
                        if isinstance(data, dict) and (data.get("success") is False or data.get("error")):
                            raise ValueError(f"{name}: {tool['name']} returned a service error")
                print(f"{name}: authenticated read via {tool['name']} succeeded")
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
                await proc.wait()


def check_stdio(name, command, tool):
    try:
        asyncio.run(probe(name, command, tool))
    except TimeoutError:
        raise ValueError(f"{name}: timed out; check VPN and service availability") from None


def check_http(name, url):
    # Streamable HTTP supports either a JSON response or a stream of SSE events.
    from urllib.request import Request, urlopen

    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}

    def send(method, params, request_id=None):
        body = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urlopen(request, timeout=20) as response:
            session = response.headers.get("MCP-Session-Id")
            if session:
                headers["MCP-Session-Id"] = session
            if request_id is None:
                return None
            if response.headers.get_content_type() == "application/json":
                result = json.load(response)
            else:
                result = {}
                event = []
                for raw in response:
                    line = raw.decode().rstrip("\r\n")
                    if line.startswith("data:"):
                        event.append(line[5:].lstrip(" "))
                    elif not line and event:
                        result = json.loads("\n".join(event))
                        event = []
                        if result.get("id") == request_id:
                            break
            if result.get("id") != request_id or "result" not in result:
                raise ValueError(f"{name}: {method} returned an unexpected MCP response")
            return result["result"]

    init = send("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "agent-setup-check", "version": "1"}}, 1)
    headers["MCP-Protocol-Version"] = init["protocolVersion"]
    send("notifications/initialized", {})
    tools = send("tools/list", {}, 2)["tools"]
    if not tools:
        raise ValueError(f"{name}: connected but server returned no tools")
    print(f"{name}: connected, {len(tools)} tools")
