"""清洗代理:把 sglang /v1/responses SSE 流里的 "created_at":<float> 改成整数,
codex 0.158 的 serde 拒收浮点 unix 时间戳导致 "error decoding response body"。
监听 127.0.0.1:4102 → 转发 DS 内网端点,SSE 其余内容逐字节透传。"""
import json
import re
from aiohttp import web, ClientSession

UPSTREAM = "http://s-20261015140447-hc45n.ailab-ma4agismall.pjh-service.org.cn"
FLOAT_INT = re.compile(rb'"(created_at|sequence_number|input_tokens|output_tokens|total_tokens|created)":(\d+)\.0+\b')


def clean(chunk: bytes) -> bytes:
    return FLOAT_INT.sub(rb'"\1":\2', chunk)


def clean_request(body: dict) -> bool:
    changed = False
    if "reasoning" in body:
        body.pop("reasoning")
        changed = True
    inc = body.get("include")
    if isinstance(inc, list):
        filtered = [x for x in inc if not str(x).startswith("reasoning.")]
        if len(filtered) != len(inc):
            body["include"] = filtered
            changed = True
    for item in body.get("input", []):
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "output_text":
                part["type"] = "text"
                changed = True
    return changed


async def forward(request: web.Request) -> web.StreamResponse:
    raw = await request.read()
    if request.path.startswith("/v1/responses"):
        # sglang dies mid-stream on reasoning.summary / encrypted_content includes
        try:
            body = json.loads(raw)
            if clean_request(body):
                raw = json.dumps(body).encode()
        except Exception:
            pass
    headers = {"Content-Type": "application/json"}
    if "Authorization" in request.headers:
        headers["Authorization"] = request.headers["Authorization"]
    session: ClientSession = request.app["client"]
    upstream = await session.post(
        f"{UPSTREAM}{request.path_qs}", data=raw, headers=headers
    )
    resp = web.StreamResponse(status=upstream.status, headers={
        "Content-Type": upstream.headers.get("Content-Type", "application/json"),
        "Cache-Control": "no-cache",
    })
    await resp.prepare(request)
    dump = None
    if request.path.startswith("/v1/responses"):
        import time as _t
        dump = open(f"/tmp/ds-dump-{_t.time():.0f}.txt", "wb")
    try:
        if "text/event-stream" in upstream.headers.get("Content-Type", ""):
            async for chunk in upstream.content.iter_any():
                if dump is not None:
                    dump.write(chunk)
                await resp.write(clean(chunk))
        else:
            async for chunk in upstream.content.iter_any():
                if dump is not None:
                    dump.write(chunk)
                await resp.write(chunk)
    finally:
        if dump is not None:
            dump.close()
    await resp.write_eof()
    return resp


async def on_startup(app: web.Application):
    app["client"] = ClientSession()


async def on_cleanup(app: web.Application):
    await app["client"].close()


app = web.Application()
app.router.add_route("*", "/{tail:.*}", forward)
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)

if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=4102, print=None)
