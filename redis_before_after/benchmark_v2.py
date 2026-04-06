"""
╔══════════════════════════════════════════════════════════════════════╗
║         BENCHMARK v2: No Cache vs Redis Cache                        ║
║                                                                      ║
║   Два раунда тестирования:                                           ║
║   1) «Холодный старт» — 100 запросов (кеш пустой)                   ║
║   2) «Горячий кеш»    — 2000 запросов (кеш полностью прогрет)       ║
║                                                                      ║
║   + Отдельный тест задержки (latency) на одном и том же эндпоинте    ║
║     100 последовательных GET /products/1  (чистое время ответа)      ║
╚══════════════════════════════════════════════════════════════════════╝

Запуск:
    python benchmark_v2.py
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


# ─── Config ──────────────────────────────────────────────────────

NO_CACHE   = "http://localhost:8000"
WITH_REDIS = "http://localhost:8001"

ENDPOINTS_CACHED = [
    ("/categories/",               "GET /categories/"),
    ("/products/popular?limit=5",  "GET /popular"),
    ("/products/1",                "GET /products/1"),
    ("/products/2",                "GET /products/2"),
    ("/products/3",                "GET /products/3"),
    ("/products/5",                "GET /products/5"),
]

ENDPOINTS_UNCACHED = [
    ("/products/?skip=0&limit=10",  "GET /products/ page"),
    ("/products/count",             "GET /products/count"),
    ("/orders/",                    "GET /orders/"),
]

ALL_ENDPOINTS = ENDPOINTS_CACHED + ENDPOINTS_UNCACHED

CACHED_NAMES = {e[1] for e in ENDPOINTS_CACHED}


# ─── Helpers ─────────────────────────────────────────────────────

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
    weights = [20, 15, 12, 10, 8, 6,  8, 4, 3]  # cached heavy

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


# ─── Pretty print ────────────────────────────────────────────────

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
        nc_v = statistics.mean(nc_ep) * 1000 if nc_ep else 0
        wr_v = statistics.mean(wr_ep) * 1000 if wr_ep else 0
        is_cached = name in CACHED_NAMES
        if nc_v > 0 and wr_v > 0:
            sp = nc_v / wr_v
            sp_str = f"×{sp:.2f}"
            (cached_speedups if is_cached else uncached_speedups).append(sp)
        else:
            sp_str = "—"
        print(f"  {name:<24} {nc_v:>8.2f}ms {wr_v:>8.2f}ms {sp_str:>9} {'✅' if is_cached else '❌':>5}")

    if cached_speedups:
        print(f"\n  🔴 Кешируемые эндпоинты:   avg speedup ×{statistics.mean(cached_speedups):.2f}")
    if uncached_speedups:
        print(f"  ⚪ Некешируемые эндпоинты: avg speedup ×{statistics.mean(uncached_speedups):.2f}")


# ─── Main ────────────────────────────────────────────────────────

async def main():
    banner("🔬 BENCHMARK v2: No Cache vs Redis Cache")
    print("  01_no_cache  → http://localhost:8000")
    print("  02_with_redis → http://localhost:8001")

    # Health check
    async with aiohttp.ClientSession() as s:
        for url in [NO_CACHE, WITH_REDIS]:
            async with s.get(f"{url}/health") as r:
                d = await r.json()
                print(f"  ✅ {url} → {d}")

    # ── ТЕСТ 1: Чистая задержка (sequential) ─────────────────────
    banner("📏 ТЕСТ 1 — Чистая задержка (sequential, 1 user)")
    print("  100 последовательных GET на каждый эндпоинт, без параллелизма.")
    print("  Это показывает ЧИСТОЕ время ответа сервера.\n")

    N_SEQ = 100
    test_paths = [
        ("/categories/",              "GET /categories/ [cached]"),
        ("/products/popular?limit=5", "GET /popular [cached]"),
        ("/products/1",               "GET /products/1 [cached]"),
        ("/products/?skip=0&limit=10","GET /products/ page [NO cache]"),
    ]

    for path, label in test_paths:
        nc_lats = await sequential_latency_test(NO_CACHE, path, N_SEQ)
        wr_lats = await sequential_latency_test(WITH_REDIS, path, N_SEQ)
        print_latency_comparison(f"  {label}  ({N_SEQ} запросов)", nc_lats, wr_lats)

    # ── ТЕСТ 2: Параллельная нагрузка — холодный старт ───────────
    banner("🧊 ТЕСТ 2 — Холодный старт (50 users × 10 req = 500)")
    print("  Кеш 02_with_redis очищается перед тестом.\n")

    # Очистить кеш Redis
    async with aiohttp.ClientSession() as s:
        # Сделаем PATCH чтобы инвалидировать, потом один запрос на categories
        # Проще — просто перезапустим кеш через Docker exec
        pass

    import subprocess
    subprocess.run(
        ["docker", "exec", "shop_redis", "redis-cli", "FLUSHDB"],
        capture_output=True, text=True
    )
    print("  ✅ Redis кеш очищен (FLUSHDB)\n")

    COLD_USERS = 50
    COLD_REQ = 500

    start = time.perf_counter()
    nc_cold = await parallel_load(NO_CACHE, COLD_USERS, COLD_REQ)
    nc_cold_time = time.perf_counter() - start

    # Снова очистим кеш (он заполнился от прогрева)
    subprocess.run(
        ["docker", "exec", "shop_redis", "redis-cli", "FLUSHDB"],
        capture_output=True, text=True
    )

    start = time.perf_counter()
    wr_cold = await parallel_load(WITH_REDIS, COLD_USERS, COLD_REQ)
    wr_cold_time = time.perf_counter() - start

    print_parallel_comparison(
        "Холодный старт (кеш пустой, первые обращения):",
        nc_cold, wr_cold, nc_cold_time, wr_cold_time, COLD_REQ,
    )

    # ── ТЕСТ 3: Параллельная нагрузка — горячий кеш ──────────────
    banner("🔥 ТЕСТ 3 — Горячий кеш (50 users × 2000 req)")
    print("  Кеш уже прогрет. Основная нагрузка.\n")

    # Прогрев кеша
    async with aiohttp.ClientSession() as s:
        for path, _ in ALL_ENDPOINTS:
            await single_get(s, f"{WITH_REDIS}{path}")
    print("  ✅ Кеш прогрет\n")

    HOT_USERS = 50
    HOT_REQ = 2000

    start = time.perf_counter()
    nc_hot = await parallel_load(NO_CACHE, HOT_USERS, HOT_REQ)
    nc_hot_time = time.perf_counter() - start

    start = time.perf_counter()
    wr_hot = await parallel_load(WITH_REDIS, HOT_USERS, HOT_REQ)
    wr_hot_time = time.perf_counter() - start

    print_parallel_comparison(
        "Горячий кеш (основной рабочий режим):",
        nc_hot, wr_hot, nc_hot_time, wr_hot_time, HOT_REQ,
    )

    # ── ТЕСТ 4: Стресс-тест — 100 users × 5000 req ──────────────
    banner("💥 ТЕСТ 4 — Стресс-тест (100 users × 5000 req)")
    print("  Максимальная параллельная нагрузка.\n")

    STRESS_USERS = 100
    STRESS_REQ = 5000

    start = time.perf_counter()
    nc_stress = await parallel_load(NO_CACHE, STRESS_USERS, STRESS_REQ)
    nc_stress_time = time.perf_counter() - start

    start = time.perf_counter()
    wr_stress = await parallel_load(WITH_REDIS, STRESS_USERS, STRESS_REQ)
    wr_stress_time = time.perf_counter() - start

    print_parallel_comparison(
        "Стресс-тест (пиковая нагрузка):",
        nc_stress, wr_stress, nc_stress_time, wr_stress_time, STRESS_REQ,
    )

    # ── ИТОГ ─────────────────────────────────────────────────────
    banner("🏁 ИТОГОВЫЙ ОТЧЁТ")

    nc_all_hot = [l for lats in nc_hot.values() for l in lats]
    wr_all_hot = [l for lats in wr_hot.values() for l in lats]
    nc_all_stress = [l for lats in nc_stress.values() for l in lats]
    wr_all_stress = [l for lats in wr_stress.values() for l in lats]

    avg_hot_nc = statistics.mean(nc_all_hot) * 1000
    avg_hot_wr = statistics.mean(wr_all_hot) * 1000
    avg_stress_nc = statistics.mean(nc_all_stress) * 1000
    avg_stress_wr = statistics.mean(wr_all_stress) * 1000

    hot_rps_nc = HOT_REQ / nc_hot_time
    hot_rps_wr = HOT_REQ / wr_hot_time
    stress_rps_nc = STRESS_REQ / nc_stress_time
    stress_rps_wr = STRESS_REQ / wr_stress_time

    print(f"""
  ┌─────────────────────┬─────────────────────┬─────────────────────┬────────────┐
  │ Режим               │   No Cache (8000)   │  With Redis (8001)  │  Speedup   │
  ├─────────────────────┼─────────────────────┼─────────────────────┼────────────┤
  │ Hot cache Avg       │ {avg_hot_nc:>14.2f} ms  │ {avg_hot_wr:>14.2f} ms  │ ×{avg_hot_nc/avg_hot_wr if avg_hot_wr else 0:>6.2f}   │
  │ Hot cache RPS       │ {hot_rps_nc:>14.0f} r/s │ {hot_rps_wr:>14.0f} r/s │ {(hot_rps_wr-hot_rps_nc)/hot_rps_nc*100 if hot_rps_nc else 0:>+7.1f}%  │
  │ Stress Avg          │ {avg_stress_nc:>14.2f} ms  │ {avg_stress_wr:>14.2f} ms  │ ×{avg_stress_nc/avg_stress_wr if avg_stress_wr else 0:>6.2f}   │
  │ Stress RPS          │ {stress_rps_nc:>14.0f} r/s │ {stress_rps_wr:>14.0f} r/s │ {(stress_rps_wr-stress_rps_nc)/stress_rps_nc*100 if stress_rps_nc else 0:>+7.1f}%  │
  └─────────────────────┴─────────────────────┴─────────────────────┴────────────┘

  📌 ВАЖНО:
  • На 24 товарах PostgreSQL отвечает быстро — Redis не даёт огромного прироста.
  • Реальная сила Redis проявляется когда:
    — в БД миллионы строк и запросы с JOIN идут 50-500 мс
    — сотни/тысячи одновременных пользователей
    — запросы к внешним API (геолокация, курсы валют)
    — тяжёлые вычисления (рекомендации, агрегаты)
  • Даже на малых данных Redis:
    — снимает нагрузку с PostgreSQL (меньше соединений к БД)
    — гарантирует стабильное время ответа (кеш = O(1))
    — защищает от cache stampede при всплесках трафика
""")


if __name__ == "__main__":
    asyncio.run(main())
