import asyncio
import os
import signal
import socket
import sys
from pathlib import Path

import grpc
from catalog.v1 import catalog_pb2
from stand_core.grpc.healthcheck import check

EXAMPLE = Path(__file__).with_name("example_main.py")


async def _wait_serving(addr: str, process: asyncio.subprocess.Process) -> None:
    for _ in range(100):
        if process.returncode is not None:
            raise AssertionError(f"service exited with {process.returncode}")
        if await check(addr, deadline=0.2):
            return
        await asyncio.sleep(0.1)
    raise AssertionError("service did not become SERVING")


async def test_worker_serves_injected_handlers_and_stops_gracefully() -> None:
    with socket.socket() as sock:
        sock.bind(("localhost", 0))
        port = sock.getsockname()[1]
    env = {**os.environ, "GRPC_PORT": str(port), "STAND_API_KEY": "key"}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(EXAMPLE),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        addr = f"localhost:{port}"
        await _wait_serving(addr, process)
        async with grpc.aio.insecure_channel(addr) as channel:
            call = channel.unary_unary(
                "/catalog.v1.CatalogService/GetProduct",
                request_serializer=catalog_pb2.GetProductRequest.SerializeToString,
                response_deserializer=catalog_pb2.GetProductResponse.FromString,
            )
            unary_call = call(catalog_pb2.GetProductRequest(product_id="p1"), timeout=2)
            response = await unary_call
            initial_metadata = await unary_call.initial_metadata()

        process.send_signal(signal.SIGTERM)
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
    finally:
        if process.returncode is None:
            process.kill()
            await process.communicate()

    assert response.product.name == "connected"
    assert dict(initial_metadata)["x-request-id"]
    assert b'"event": "grpc.call"' in stdout
    # nuke-di завершает Run по сигналу кодом 128 + номер сигнала, как это видит shell
    assert process.returncode == 128 + signal.SIGTERM, stderr
    assert b"grpc.server_stopping" in stdout
    assert b"Traceback" not in stderr
