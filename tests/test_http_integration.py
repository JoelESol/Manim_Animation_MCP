"""Integration test: talk to the animation-mcp server over streamable HTTP."""

import asyncio

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

CODE = """
from manim import Circle, Create, Scene, Square, ReplacementTransform

class CircleToSquare(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.play(ReplacementTransform(circle, Square()))
        self.wait(0.5)
"""

BAD_CODE = """
from manim import Scene

class Broken(Scene):
    def construct(self):
        self.play(object_does_not_exist)
"""


async def main() -> None:
    async with streamable_http_client("http://127.0.0.1:8737/mcp") as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("TOOLS:", sorted(t.name for t in tools.tools))

            result = await session.call_tool("render_manim", {
                "code": CODE, "scene_name": "CircleToSquare", "quality": "l",
            })
            print("RENDER:", str(result.structured_content)[:400])
            assert not result.is_error
            assert result.structured_content, result.content
            data = result.structured_content
            if "job_id" not in data:  # tolerate wrapped payloads
                data = data[list(data)[0]]
            artifacts = [a for a in data["artifacts"] if a.endswith(".mp4")]
            assert artifacts, data

            listed = await session.call_tool("list_artifacts",
                                             {"job_id": data["job_id"]})
            print("ARTIFACTS:", listed.content[0].text[:300])

            # --- download links ---
            urls = data["download_urls"]
            assert urls, data
            import urllib.request
            body = urllib.request.urlopen(urls[0], timeout=10).read()
            print("DOWNLOAD OK:", len(body), "bytes from", urls[0][:80])
            assert body[:4] == b"\x1aE\xdf\xa4" or body[:3] == b"ID3" or len(body) > 1000

            import urllib.parse
            bad = urls[0].replace("token=", "token=deadbeef")
            try:
                urllib.request.urlopen(bad, timeout=10)
                raise AssertionError("tampered token accepted")
            except urllib.error.HTTPError as e:
                print("TAMPERED TOKEN REJECTED:", e.code)
                assert e.code == 403

            expired = urls[0].replace("expires=", "expires=1")
            try:
                urllib.request.urlopen(expired, timeout=10)
                raise AssertionError("expired link accepted")
            except urllib.error.HTTPError as e:
                print("EXPIRED LINK REJECTED:", e.code)
                assert e.code == 403

            link = await session.call_tool("get_download_link", {
                "job_id": data["job_id"],
                "artifact_path": next(a for a in data["artifacts"]
                                      if a.endswith(".png")),
            })
            fresh = link.content[0].text
            print("FRESH LINK:", fresh[:80])
            png = urllib.request.urlopen(fresh, timeout=10).read()
            print("PNG DOWNLOAD:", len(png), "bytes, signature:",
                  png[:8].hex()[:16])
            assert png[:8] == bytes.fromhex("89504e470d0a1a0a")

            path = next(a for a in data["artifacts"] if a.endswith(".png"))
            preview = await session.call_tool("get_preview", {
                "job_id": data["job_id"], "artifact_path": path,
            })
            kinds = [type(c).__name__ for c in preview.content]
            print("PREVIEW CONTENT TYPES:", kinds)
            assert "ImageContent" in kinds

            bad = await session.call_tool("render_manim", {
                "code": BAD_CODE, "scene_name": "Broken",
            })
            text = bad.content[0].text
            print("FAILURE HANDLED:", "is_error:", bad.is_error,
                  "| NameError visible to model:", "NameError" in text)
            assert bad.is_error and "NameError" in text

            traversal = await session.call_tool("get_artifact_base64", {
                "job_id": "../../etc", "artifact_path": "passwd",
            })
            print("TRAVERSAL BLOCKED:", traversal.is_error)
            assert traversal.is_error

            print("ALL INTEGRATION CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
