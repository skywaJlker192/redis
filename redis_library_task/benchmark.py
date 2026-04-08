"""
╔══════════════════════════════════════════════════════════════════════╗
║      BENCHMARK: Library API — No Cache vs Redis Cache                ║
║                                                                      ║
║   Два раунда тестирования:                                           ║
║   1) «Холодный старт» — 100 запросов (кеш пустой)                   ║
║   2) «Горячий кеш»    — 2000 запросов (кеш полностью прогрет)       ║
║                                                                      ║
║   + Отдельный тест задержки (latency) на одном и том же эндпоинте    ║
║     100 последовательных GET /books/1  (чистое время ответа)         ║
╚══════════════════════════════════════════════════════════════════════╝

Запуск:
    # Сначала запустите оба проекта:
    # cd task && docker compose up -d --build        (порт 8000)
    # cd solution && docker compose up -d --build    (порт 8001)

    pip install aiohttp
    python benchmark.py
"""

import asyncio
import time
import statistics
import random
import sys

try:
    import aiohttp
except ImportError:
    print("pip install aiohttp")
    sys.exit(1)


# ─── Config 

NO_CACHE   = "http://localhost:8000"
WITH_REDIS = "http://localhost:8001"

ENDPOINTS_CACHED = [
    ("/authors/",                  "GET /authors/"),
    ("/authors/1",                 "GET /authors/1"),
    ("/books/top-rated?limit=5",   "GET /top-rated"),
    ("/books/popular?limit=5",     "GET /popular"),
    ("/books/1",                   "GET /books/1"),
    ("/books/2",                   "GET /books/2"),
    ("/books/5",                   "GET /books/5"),
]

ENDPOINTS_UNCACHED = [
    ("/books/?offset=0&limit=10",  "GET /books/ page"),
    ("/books/count",               "GET /books/count"),
    ("/books/search?q=война",      "GET /books/search"),
    ("/borrowings/",               "GET /borrowings/"),
]

ALL_ENDPOINTS = ENDPOINTS_CACHED + ENDPOINTS_UNCACHED

CACHED_NAMES = {e[1] for e in ENDPOINTS_CACHED}


# ─── Helpers

async def single_get(session: aiohttp.ClientSession, url: str) -> float:
    """Один GET-запрос, возвращает время ответа в секундах."""
    start = time.perf_counter()
    async with session.get(url) as resp:
        await resp.read()
    return time.perf_counter() - start


async def sequential_latency_test(
    base_url: str, path: str, n: int
) -> list[float]:
    """n последовательных GET-запросов — без параллелизма, чистая задержка."""
    latencies = []
    async with aiohttp.ClientSession() as session:
        # один прогрев
        await single_get(session, f"{base_url}{path}")
        for _ in range(n):
            lat = await single_get(session, f"{base_url}{path}")
            latencies.append(lat)
    return latencies


async def parallel_load(
    base_url: str,
    concurrency: int,
    total: int,
) -> dict[str, list[float]]:
    """Параллельная нагрузка — weighted random по эндпоинтам."""
    results: dict[str, list[float]] = {}
    lock = asyncio.Lock()
    sem = asyncio.Semaphore(concurrency)
    paths   = [e[0] for e in ALL_ENDPOINTS]
    names   = [e[1] for e in ALL_ENDPOINTS]
    weights = [20, 12, 15, 15, 10, 8, 6,  8, 4, 3, 3]  # cached heavy

    async def do_request(session: aiohttp.ClientSession):
        async with sem:
            idx = random.choices(range(len(paths)), weights=weights, k=1)[0]
            name = names[idx]
            lat = await single_get(session, f"{base_url}{paths[idx]}")
            async with lock:
                results.setdefault(name, []).append(lat)

    connector = aiohttp.TCPConnector(limit=concurrency * 2)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [do_request(session) for _ in range(total)]
        await asyncio.gather(*tasks)

    return results


# ─── Pretty print 

def ms(val: float) -> str:
    return f"{val * 1000:.2f}"

def pct(sorted_list: list[float], p: float) -> float:
    idx = int(len(sorted_list) * p)
    return sorted_list[min(idx, len(sorted_list) - 1)]

def banner(text: str):
    w = 72
    print()
    print("━" * w)
    print(f"  {text}")
    print("━" * w)


def print_latency_comparison(
    label: str,
    nc_lats: list[float],
    wr_lats: list[float],
):
    nc_s = sorted(nc_lats)
    wr_s = sorted(wr_lats)

    def row(metric: str, nc_val: float, wr_val: float):
        ratio = nc_val / wr_val if wr_val > 0 else 0
        faster = "🟢 Redis" if ratio > 1.05 else ("🔴 No cache" if ratio < 0.95 else "≈ равно")
        print(f"  │ {metric:<16} │ {ms(nc_val):>10} ms │ {ms(wr_val):>10} ms │ ×{ratio:>5.2f} │ {faster:<14}│")

    print(f"\n  {label}")
    print(f"  ┌──────────────────┬──────────────┬──────────────┬───────┬───────────────┐")
    print(f"  │ Метрика          │   No Cache   │  With Redis  │ Ratio │ Быстрее       │")
    print(f"  ├──────────────────┼──────────────┼──────────────┼───────┼───────────────┤")
    row("Avg",    statistics.mean(nc_lats),   statistics.mean(wr_lats))
    row("Median", statistics.median(nc_lats), statistics.median(wr_lats))
    row("P95",    pct(nc_s, 0.95),            pct(wr_s, 0.95))
    row("P99",    pct(nc_s, 0.99),            pct(wr_s, 0.99))
    row("Min",    min(nc_lats),               min(wr_lats))
    row("Max",    max(nc_lats),               max(wr_lats))
    print(f"  └──────────────────┴──────────────┴──────────────┴───────┴───────────────┘")


def print_parallel_comparison(
    label: str,
    nc_data: dict[str, list[float]],
    wr_data: dict[str, list[float]],
    nc_time: float,
    wr_time: float,
    total: int,
):
    nc_rps = total / nc_time
    wr_rps = total / wr_time
    rps_gain = (wr_rps - nc_rps) / nc_rps * 100

    nc_all = [l for lats in nc_data.values() for l in lats]
    wr_all = [l for lats in wr_data.values() for l in lats]

    print(f"\n  {label}")
    print(f"  ┌──────────────────────────────┬──────────────┬──────────────┬────────────┐")
    print(f"  │ Метрика                      │   No Cache   │  With Redis  │  Разница   │")
    print(f"  ├──────────────────────────────┼──────────────┼──────────────┼────────────┤")
    print(f"  │ Throughput (RPS)             │ {nc_rps:>9.0f}r/s │ {wr_rps:>9.0f}r/s │ {rps_gain:>+7.1f}%   │")
    print(f"  │ Total time                   │ {nc_time:>9.2f}  s │ {wr_time:>9.2f}  s │            │")

    nc_avg = statistics.mean(nc_all) * 1000
    wr_avg = statistics.mean(wr_all) * 1000
    speedup = nc_avg / wr_avg if wr_avg else 0
    print(f"  │ Avg latency                  │ {nc_avg:>9.2f} ms │ {wr_avg:>9.2f} ms │ ×{speedup:>6.2f}   │")

    nc_med = statistics.median(nc_all) * 1000
    wr_med = statistics.median(wr_all) * 1000
    speedup_m = nc_med / wr_med if wr_med else 0
    print(f"  │ Median latency               │ {nc_med:>9.2f} ms │ {wr_med:>9.2f} ms │ ×{speedup_m:>6.2f}   │")

    nc_s = sorted(nc_all)
    wr_s = sorted(wr_all)
    nc_p95 = pct(nc_s, 0.95) * 1000
    wr_p95 = pct(wr_s, 0.95) * 1000
    print(f"  │ P95 latency                  │ {nc_p95:>9.2f} ms │ {wr_p95:>9.2f} ms │            │")
    print(f"  └──────────────────────────────┴──────────────┴──────────────┴────────────┘")

    # По эндпоинтам
    print(f"\n  По эндпоинтам:")
    print(f"  {'Endpoint':<24} {'No Cache':>10} {'Redis':>10} {'Speedup':>9} {'Кеш?':>5}")
    print(f"  {'─' * 62}")

    all_names = sorted(set(list(nc_data.keys()) + list(wr_data.keys())))
    cached_speedups = []
    uncached_speedups = []

    for name in all_names:
        nc_ep = nc_data.get(name, [])
        wr_ep = wr_data.get(name, [])
        if not nc_ep or not wr_ep:
            continue
        nc_m = statistics.mean(nc_ep) * 1000
        wr_m = statistics.mean(wr_ep) * 1000
        sp = nc_m / wr_m if wr_m > 0 else 0
        is_cached = "✅" if name in CACHED_NAMES else "❌"
        print(f"  {name:<24} {nc_m:>8.2f}ms {wr_m:>8.2f}ms   ×{sp:>5.2f}  {is_cached}")
        if name in CACHED_NAMES:
            cached_speedups.append(sp)
        else:
            uncached_speedups.append(sp)

    if cached_speedups:
        print(f"\n  Средний speedup кешированных:    ×{statistics.mean(cached_speedups):.2f}")
    if uncached_speedups:
        print(f"  Средний speedup некешированных:   ×{statistics.mean(uncached_speedups):.2f}")


# ─── Main ────────────────────────────────────────────────────────

async def main():
    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   📚 BENCHMARK: Library — No Cache vs Redis Cache            ║")
    print("╚══════════════════════════════════════════════════════════════╝")

    # Проверяем доступность
    for name, url in [("No Cache", NO_CACHE), ("With Redis", WITH_REDIS)]:
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{url}/health") as r:
                    data = await r.json()
                    print(f"  ✅ {name:12} → {url}  {data}")
        except Exception as e:
            print(f"  {name:12} -> {url}  ОШИБКА: {e}")
            print(f"\n  Запустите оба проекта:")
            print(f"    cd task     && docker compose up -d --build")
            print(f"    cd solution && docker compose up -d --build")
            return

    # Тест 1: Latency — чистая задержка (1 пользователь)

    banner("Тест 1: Latency — 100 последовательных GET /books/1")

    nc_lats = await sequential_latency_test(NO_CACHE, "/books/1", 100)
    wr_lats = await sequential_latency_test(WITH_REDIS, "/books/1", 100)
    print_latency_comparison("Карточка книги (GET /books/1)", nc_lats, wr_lats)

    banner("Тест 1b: Latency — 100 последовательных GET /authors/")

    nc_lats2 = await sequential_latency_test(NO_CACHE, "/authors/", 100)
    wr_lats2 = await sequential_latency_test(WITH_REDIS, "/authors/", 100)
    print_latency_comparison("Список авторов (GET /authors/)", nc_lats2, wr_lats2)

    banner("Тест 1c: Latency — 100 последовательных GET /books/top-rated")

    nc_lats3 = await sequential_latency_test(NO_CACHE, "/books/top-rated?limit=10", 100)
    wr_lats3 = await sequential_latency_test(WITH_REDIS, "/books/top-rated?limit=10", 100)
    print_latency_comparison("Топ по рейтингу (GET /books/top-rated)", nc_lats3, wr_lats3)

    # Тест 2: Нагрузка — 50 параллельных пользователей

    concurrency = 50
    total = 2000

    banner(f"Тест 2: Нагрузка — {concurrency} пользователей, {total} запросов")

    t0 = time.perf_counter()
    nc_data = await parallel_load(NO_CACHE, concurrency, total)
    nc_time = time.perf_counter() - t0

    t0 = time.perf_counter()
    wr_data = await parallel_load(WITH_REDIS, concurrency, total)
    wr_time = time.perf_counter() - t0

    print_parallel_comparison(
        f"Параллельная нагрузка ({concurrency} users, {total} requests)",
        nc_data, wr_data, nc_time, wr_time, total,
    )

    # Тест 3: Тяжёлая нагрузка — 100 параллельных пользователей

    concurrency2 = 100
    total2 = 5000

    banner(f"Тест 3: Тяжёлая нагрузка — {concurrency2} пользователей, {total2} запросов")

    t0 = time.perf_counter()
    nc_data2 = await parallel_load(NO_CACHE, concurrency2, total2)
    nc_time2 = time.perf_counter() - t0

    t0 = time.perf_counter()
    wr_data2 = await parallel_load(WITH_REDIS, concurrency2, total2)
    wr_time2 = time.perf_counter() - t0

    print_parallel_comparison(
        f"Тяжёлая нагрузка ({concurrency2} users, {total2} requests)",
        nc_data2, wr_data2, nc_time2, wr_time2, total2,
    )

    print()
    print("═" * 72)
    print("  Бенчмарк завершён!")
    print("═" * 72)
    print()


if __name__ == "__main__":
    asyncio.run(main())
