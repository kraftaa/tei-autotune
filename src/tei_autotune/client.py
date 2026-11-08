from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Any, Callable

import httpx

from .models import RunResult, WorkloadItem


class TeiClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 120.0,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.transport = transport

    async def get_info(self) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers=self.headers,
            transport=self.transport,
        ) as client:
            try:
                response = await client.get(f"{self.base_url}/info")
                response.raise_for_status()
                value = response.json()
                return value if isinstance(value, dict) else {}
            except (httpx.HTTPError, ValueError):
                return {}

    async def check_embed(self, text: str) -> int | None:
        """Verify endpoint semantics and return server-reported token usage if present."""
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            headers=self.headers,
            transport=self.transport,
        ) as client:
            response = await client.post(
                f"{self.base_url}/embed",
                json={"inputs": [text]},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list) or len(payload) != 1:
                raise ValueError("/embed returned an unexpected response shape")
            return _compute_tokens(response)

    async def run_cell(
        self,
        corpus: list[WorkloadItem],
        *,
        batch_size: int,
        concurrency: int,
        duration_seconds: float,
        warmup_seconds: float,
        repetitions: int,
        progress: Callable[[str], None] | None = None,
    ) -> list[RunResult]:
        limits = httpx.Limits(
            max_connections=max(concurrency * 2, 10),
            max_keepalive_connections=max(concurrency, 10),
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            limits=limits,
            headers=self.headers,
            transport=self.transport,
        ) as client:
            if warmup_seconds > 0:
                await self._run_once(
                    client,
                    corpus,
                    batch_size=batch_size,
                    concurrency=concurrency,
                    duration_seconds=warmup_seconds,
                    repetition=-1,
                )

            runs: list[RunResult] = []
            for repetition in range(repetitions):
                if progress:
                    progress(
                        f"batch={batch_size} concurrency={concurrency} "
                        f"run={repetition + 1}/{repetitions}"
                    )
                runs.append(
                    await self._run_once(
                        client,
                        corpus,
                        batch_size=batch_size,
                        concurrency=concurrency,
                        duration_seconds=duration_seconds,
                        repetition=repetition,
                    )
                )
            return runs

    async def _run_once(
        self,
        client: httpx.AsyncClient,
        corpus: list[WorkloadItem],
        *,
        batch_size: int,
        concurrency: int,
        duration_seconds: float,
        repetition: int,
    ) -> RunResult:
        started = time.perf_counter()
        cpu_started = time.process_time()
        deadline = started + duration_seconds
        lock = asyncio.Lock()
        next_index = 0
        successful_requests = 0
        failed_requests = 0
        successful_texts = 0
        compute_tokens = 0
        latencies_ms: list[float] = []
        transport_latencies_ms: list[float] = []
        decode_latencies_ms: list[float] = []
        server_total_ms: list[float] = []
        server_queue_ms: list[float] = []
        server_tokenization_ms: list[float] = []
        server_inference_ms: list[float] = []
        statuses: Counter[str] = Counter()

        async def next_batch() -> list[str]:
            nonlocal next_index
            async with lock:
                batch = [
                    corpus[(next_index + offset) % len(corpus)].text
                    for offset in range(batch_size)
                ]
                next_index = (next_index + batch_size) % len(corpus)
                return batch

        async def worker() -> None:
            nonlocal successful_requests, failed_requests
            nonlocal successful_texts, compute_tokens
            while time.perf_counter() < deadline:
                inputs = await next_batch()
                request_started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{self.base_url}/embed", json={"inputs": inputs}
                    )
                    transport_finished = time.perf_counter()
                    if response.status_code != 200:
                        failed_requests += 1
                        statuses[str(response.status_code)] += 1
                        continue
                    decode_started = time.perf_counter()
                    payload = response.json()
                    if not _valid_embed_payload(payload, len(inputs)):
                        failed_requests += 1
                        statuses["invalid_response"] += 1
                        continue
                    request_finished = time.perf_counter()
                    successful_requests += 1
                    successful_texts += len(inputs)
                    latencies_ms.append((request_finished - request_started) * 1000)
                    transport_latencies_ms.append(
                        (transport_finished - request_started) * 1000
                    )
                    decode_latencies_ms.append(
                        (request_finished - decode_started) * 1000
                    )
                    _append_header(response, "x-total-time", server_total_ms)
                    _append_header(response, "x-queue-time", server_queue_ms)
                    _append_header(
                        response, "x-tokenization-time", server_tokenization_ms
                    )
                    _append_header(response, "x-inference-time", server_inference_ms)
                    tokens = _compute_tokens(response)
                    if tokens is not None:
                        compute_tokens += tokens
                except httpx.TimeoutException:
                    failed_requests += 1
                    statuses["timeout"] += 1
                except (httpx.HTTPError, ValueError):
                    failed_requests += 1
                    statuses["client_error"] += 1

        await asyncio.gather(*(worker() for _ in range(concurrency)))
        elapsed = time.perf_counter() - started
        client_cpu_seconds = time.process_time() - cpu_started
        return RunResult(
            batch_size=batch_size,
            concurrency=concurrency,
            repetition=repetition,
            duration_seconds=elapsed,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            successful_texts=successful_texts,
            compute_tokens=compute_tokens,
            latencies_ms=latencies_ms,
            transport_latencies_ms=transport_latencies_ms,
            decode_latencies_ms=decode_latencies_ms,
            server_total_ms=server_total_ms,
            server_queue_ms=server_queue_ms,
            server_tokenization_ms=server_tokenization_ms,
            server_inference_ms=server_inference_ms,
            client_cpu_seconds=client_cpu_seconds,
            status_counts=dict(statuses),
        )

    async def run_open_loop(
        self,
        corpus: list[WorkloadItem],
        *,
        batch_size: int,
        concurrency: int,
        arrival_rate_texts_per_second: float,
        duration_seconds: float,
        warmup_seconds: float,
        repetition: int,
    ) -> RunResult:
        limits = httpx.Limits(
            max_connections=max(concurrency * 2, 10),
            max_keepalive_connections=max(concurrency, 10),
        )
        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            limits=limits,
            headers=self.headers,
            transport=self.transport,
        ) as client:
            if warmup_seconds > 0:
                await self._run_open_loop_once(
                    client,
                    corpus,
                    batch_size=batch_size,
                    concurrency=concurrency,
                    arrival_rate_texts_per_second=arrival_rate_texts_per_second,
                    duration_seconds=warmup_seconds,
                    repetition=-1,
                )
            return await self._run_open_loop_once(
                client,
                corpus,
                batch_size=batch_size,
                concurrency=concurrency,
                arrival_rate_texts_per_second=arrival_rate_texts_per_second,
                duration_seconds=duration_seconds,
                repetition=repetition,
            )

    async def _run_open_loop_once(
        self,
        client: httpx.AsyncClient,
        corpus: list[WorkloadItem],
        *,
        batch_size: int,
        concurrency: int,
        arrival_rate_texts_per_second: float,
        duration_seconds: float,
        repetition: int,
    ) -> RunResult:
        started = time.perf_counter()
        cpu_started = time.process_time()
        request_interval = batch_size / arrival_rate_texts_per_second
        request_count = int(duration_seconds / request_interval)
        if request_count < 1:
            raise ValueError(
                "validation duration is too short to schedule one complete batch "
                "at the requested arrival rate"
            )
        queue: asyncio.Queue[tuple[int, float] | None] = asyncio.Queue(
            maxsize=max(concurrency * 4, 16)
        )
        successful_requests = 0
        failed_requests = 0
        successful_texts = 0
        compute_tokens = 0
        latencies_ms: list[float] = []
        transport_latencies_ms: list[float] = []
        decode_latencies_ms: list[float] = []
        schedule_lag_ms: list[float] = []
        server_total_ms: list[float] = []
        server_queue_ms: list[float] = []
        server_tokenization_ms: list[float] = []
        server_inference_ms: list[float] = []
        statuses: Counter[str] = Counter()

        async def worker() -> None:
            nonlocal successful_requests, failed_requests
            nonlocal successful_texts, compute_tokens
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                index, scheduled_at = item
                inputs = [
                    corpus[(index * batch_size + offset) % len(corpus)].text
                    for offset in range(batch_size)
                ]
                request_started = time.perf_counter()
                schedule_lag_ms.append(max(0.0, request_started - scheduled_at) * 1000)
                try:
                    response = await client.post(
                        f"{self.base_url}/embed", json={"inputs": inputs}
                    )
                    transport_finished = time.perf_counter()
                    if response.status_code != 200:
                        failed_requests += 1
                        statuses[str(response.status_code)] += 1
                        continue
                    decode_started = time.perf_counter()
                    payload = response.json()
                    if not _valid_embed_payload(payload, len(inputs)):
                        failed_requests += 1
                        statuses["invalid_response"] += 1
                        continue
                    request_finished = time.perf_counter()
                    successful_requests += 1
                    successful_texts += len(inputs)
                    latencies_ms.append((request_finished - scheduled_at) * 1000)
                    transport_latencies_ms.append(
                        (transport_finished - request_started) * 1000
                    )
                    decode_latencies_ms.append(
                        (request_finished - decode_started) * 1000
                    )
                    tokens = _compute_tokens(response)
                    if tokens is not None:
                        compute_tokens += tokens
                    _append_header(response, "x-total-time", server_total_ms)
                    _append_header(response, "x-queue-time", server_queue_ms)
                    _append_header(
                        response, "x-tokenization-time", server_tokenization_ms
                    )
                    _append_header(response, "x-inference-time", server_inference_ms)
                except httpx.TimeoutException:
                    failed_requests += 1
                    statuses["timeout"] += 1
                except (httpx.HTTPError, ValueError):
                    failed_requests += 1
                    statuses["client_error"] += 1
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        for index in range(request_count):
            scheduled_at = started + index * request_interval
            delay = scheduled_at - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                queue.put_nowait((index, scheduled_at))
            except asyncio.QueueFull:
                failed_requests += 1
                statuses["client_queue_full"] += 1
        await queue.join()
        for _ in workers:
            await queue.put(None)
        await asyncio.gather(*workers)
        elapsed = time.perf_counter() - started
        return RunResult(
            batch_size=batch_size,
            concurrency=concurrency,
            repetition=repetition,
            duration_seconds=elapsed,
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            successful_texts=successful_texts,
            compute_tokens=compute_tokens,
            latencies_ms=latencies_ms,
            transport_latencies_ms=transport_latencies_ms,
            decode_latencies_ms=decode_latencies_ms,
            client_cpu_seconds=time.process_time() - cpu_started,
            offered_texts=request_count * batch_size,
            scheduled_duration_seconds=duration_seconds,
            schedule_lag_ms=schedule_lag_ms,
            server_total_ms=server_total_ms,
            server_queue_ms=server_queue_ms,
            server_tokenization_ms=server_tokenization_ms,
            server_inference_ms=server_inference_ms,
            status_counts=dict(statuses),
        )


def _compute_tokens(response: httpx.Response) -> int | None:
    raw = response.headers.get("x-compute-tokens")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _valid_embed_payload(payload: Any, expected_count: int) -> bool:
    if not isinstance(payload, list) or len(payload) != expected_count:
        return False
    if not payload:
        return False
    dimension: int | None = None
    for embedding in payload:
        if not isinstance(embedding, list) or not embedding:
            return False
        if dimension is None:
            dimension = len(embedding)
        elif len(embedding) != dimension:
            return False
    return True


def _append_header(
    response: httpx.Response, name: str, destination: list[float]
) -> None:
    value = response.headers.get(name)
    if value is None:
        return
    try:
        destination.append(float(value))
    except ValueError:
        return
