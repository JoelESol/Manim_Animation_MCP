"""Live concurrency test: cap=1, two parallel renders -> one busy error."""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CODE = """
from manim import Circle, Create, Scene

class Busy(Scene):
    def construct(self):
        self.play(Create(Circle()))
        self.wait(1)
"""


async def render_once(session: ClientSession) -> tuple[bool, str]:
    res = await session.call_tool("render_manim", {
        "code": CODE, "scene_name": "Busy"})
    return res.is_error, res.content[0].text


async def main() -> None:
    async with streamable_http_client("http://127.0.0.1:8737/mcp") as (r1, w1), \
               streamable_http_client("http://127.0.0.1:8737/mcp") as (r2, w2):
        async with ClientSession(r1, w1) as s1, ClientSession(r2, w2) as s2:
            await asyncio.gather(s1.initialize(), s2.initialize())
            results = await asyncio.gather(
                render_once(s1), render_once(s2))
            busy = [text for err, text in results if err]
            ok = [text for err, text in results if not err]
            print("SUCCESSFUL RENDERS:", len(ok), "| BUSY ERRORS:", len(busy))
            if busy:
                print("BUSY MESSAGE:", busy[0][:150])
            assert len(ok) == 1 and len(busy) == 1
            assert "queue full" in busy[0]
            print("CONCURRENCY CAP VERIFIED")


if __name__ == "__main__":
    asyncio.run(main())
