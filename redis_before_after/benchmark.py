"""
╔══════════════════════════════════════════════════════════════════╗
║           BENCHMARK: No Cache vs Redis Cache                     ║
║   Нагрузочное тестирование двух одинаковых API                   ║
║   01_no_cache (port 8000)  vs  02_with_redis (port 8001)        ║
╚══════════════════════════════════════════════════════════════════╝

Запуск:
    python benchmark.py

Требования:
    pip install aiohttp
"""

import asyncio
import time
import statistics
import json
import sys
from dataclasses import dataclass, field

try:
    import aiohttp
except ImportError:
    print("Установите aiohttp:  pip install aiohttp")
    sys.exit(1)


# ─── Конфигурация ────────────────────────────────────────────────

NO_CACHE_URL = "http://localhost:8000"
WITH_REDIS_URL = "http://localhost:8001"

# Сценарии нагрузки — имитация реального трафика интернет-магазина
# Распределение: 60% просмотр товаров, 20% каталог, 15% популярное, 5% заказы
WARMUP_REQUESTS = 20          # «прогрев» перед замерами
CONCURRENT_USERS = 10         # параллельных «пользователей»
REQUESTS_PER_USER = 50        # запросов на пользователя
TOTAL_REQUESTS = CONCURRENT_USERS * REQUESTS_PER_USER  # 500

# Эндпоинты с весами (вероятность выбора)
ENDPOINTS = [
    # (path, weight, name)
    ("/categories/",            20, "GET /categories/"),
    ("/products/popular?limit=5", 15, "GET /products/popular"),
    ("/products/1",              12, "GET /products/1"),
    ("/products/2",              10, "GET /products/2"),
    ("/products/3",              8,  "GET /products/3"),
    ("/products/5",              6,  "GET /products/5"),
    ("/products/10",             5,  "GET /products/10"),
    ("/products/15",             4,  "GET /products/15"),
    ("/products/?skip=0&limit=10", 8, "GET /products/ (page1)"),
    ("/products/?skip=10&limit=10", 5, "GET /products/ (page2)"),
    ("/products/count",          4,  "GET /products/count"),
    ("/orders/",                 3,  "GET /orders/"),
]

import random

def pick_endpoint() -> tuple[str, str]:
    """Выбирает эндпоинт по весам (weighted random)."""
    paths = [e[0] for e in ENDPOINTS]
    weights = [e[1] for e in ENDPOINTS]
    names = [e[2] for e in ENDPOINTS]
    idx = random.choices(range(len(paths)), weights=weights, k=1)[0]
    return paths[idx], names[idx]


# ─── Результаты ─────────────────────────────────────────────────

@dataclass
class EndpointStats:
    name: str
    latencies: list[float] = field(default_factory=list)
    errors: int = 0

    @property
    def count(self) -> int:
        return len(self.latencies)

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.latencies) * 1000 if self.latencies else 0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.latencies) * 1000 if self.latencies else 0

    @property
    def p95_ms(self) -> float:
        if len(self.latencies) < 2:
            return self.avg_ms
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[idx] * 1000

    @property
    def p99_ms(self) -> float:
        if len(self.latencies) < 2:
            return self.avg_ms
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.99)
        return sorted_lat[idx] * 1000

    @property
    def min_ms(self) -> float:
        return min(self.latencies) * 1000 if self.latencies else 0

    @property
    def max_ms(self) -> float:
        return max(self.latencies) * 1000 if self.latencies else 0


@dataclass
class BenchmarkResult:
    server_name: str
    base_url: str
    total_requests: int = 0
    total_errors: int = 0
    total_time: float = 0.0
    all_latencies: list[float] = field(default_factory=list)
    by_endpoint: dict[str, EndpointStats] = field(default_factory=dict)

    def add(self, name: str, latency: float, error: bool = False):
        self.total_requests += 1
        if error:
            self.total_errors += 1
        else:
            self.all_latencies.append(latency)
        if name not in self.by_endpoint:
            self.by_endpoint[name] = EndpointStats(name=name)
        if error:
            self.by_endpoint[name].errors += 1
        else:
            self.by_endpoint[name].latencies.append(latency)

    @property
    def rps(self) -> float:
        return self.total_requests / self.total_time if self.total_time > 0 else 0

    @property
    def avg_ms(self) -> float:
        return statistics.mean(self.all_latencies) * 1000 if self.all_latencies else 0

    @property
    def median_ms(self) -> float:
        return statistics.median(self.all_latencies) * 1000 if self.all_latencies else 0

    @property
    def p95_ms(self) -> float:
        if len(self.all_latencies) < 2:
            return self.avg_ms
        s = sorted(self.all_latencies)
        return s[int(len(s) * 0.95)] * 1000

    @property
    def p99_ms(self) -> float:
        if len(self.all_latencies) < 2:
            return self.avg_ms
        s = sorted(self.all_latencies)
        return s[int(len(s) * 0.99)] * 1000


# ─── Нагрузочный тест ───────────────────────────────────────────

async def warmup(session: aiohttp.ClientSession, base_url: str):
    """Прогрев — чтобы соединения были установлены, кеш заполнен."""
    for _ in range(WARMUP_REQUESTS):
        path, _ = pick_endpoint()
        try:
            async with session.get(f"{base_url}{path}") as resp:
                await resp.read()
        except Exception:
            pass


async def worker(
    session: aiohttp.ClientSession,
    base_url: str,
    result: BenchmarkResult,
    num_requests: int,
):
    """Один виртуальный пользователь — делает num_requests запросов."""
    for _ in range(num_requests):
        path, name = pick_endpoint()
        url = f"{base_url}{path}"
        start = time.perf_counter()
        try:
            async with session.get(url) as resp:
                await resp.read()
                elapsed = time.perf_counter() - start
                if resp.status < 400:
                    result.add(name, elapsed)
                else:
                    result.add(name, elapsed, error=True)
        except Exception:
            elapsed = time.perf_counter() - start
            result.add(name, elapsed, error=True)


async def run_benchmark(server_name: str, base_url: str) -> BenchmarkResult:
    """Запуск полного теста для одного сервера."""
    result = BenchmarkResult(server_name=server_name, base_url=base_url)

    connector = aiohttp.TCPConnector(limit=CONCURRENT_USERS * 2, force_close=False)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        # Прогрев
        print(f"  ⏳ Прогрев ({WARMUP_REQUESTS} запросов)…")
        await warmup(session, base_url)

        # Основной тест
        print(f"  🚀 Нагрузка: {CONCURRENT_USERS} пользователей × {REQUESTS_PER_USER} запросов = {TOTAL_REQUESTS}")
        start_time = time.perf_counter()

        tasks = [
            worker(session, base_url, result, REQUESTS_PER_USER)
            for _ in range(CONCURRENT_USERS)
        ]
        await asyncio.gather(*tasks)

        result.total_time = time.perf_counter() - start_time

    return result


# ─── Вывод результатов ───────────────────────────────────────────

def print_header(text: str):
    width = 70
    print()
    print("═" * width)
    print(f"  {text}")
    print("═" * width)


def print_result(res: BenchmarkResult):
    print(f"\n  📊 Общая статистика: {res.server_name}")
    print(f"  {'─' * 50}")
    print(f"  Всего запросов:   {res.total_requests}")
    print(f"  Ошибок:           {res.total_errors}")
    print(f"  Общее время:      {res.total_time:.2f} сек")
    print(f"  Throughput (RPS): {res.rps:.1f} req/sec")
    print(f"  Avg latency:      {res.avg_ms:.2f} ms")
    print(f"  Median latency:   {res.median_ms:.2f} ms")
    print(f"  P95 latency:      {res.p95_ms:.2f} ms")
    print(f"  P99 latency:      {res.p99_ms:.2f} ms")

    # По эндпоинтам
    print(f"\n  📋 Детализация по эндпоинтам:")
    print(f"  {'Endpoint':<28} {'Count':>5} {'Avg ms':>8} {'Med ms':>8} {'P95 ms':>8} {'Max ms':>8}")
    print(f"  {'─' * 74}")

    for name in sorted(res.by_endpoint.keys()):
        ep = res.by_endpoint[name]
        if ep.count == 0:
            continue
        print(f"  {ep.name:<28} {ep.count:>5} {ep.avg_ms:>8.2f} {ep.median_ms:>8.2f} {ep.p95_ms:>8.2f} {ep.max_ms:>8.2f}")


def print_comparison(no_cache: BenchmarkResult, with_redis: BenchmarkResult):
    print_header("⚡ СРАВНЕНИЕ: No Cache vs Redis Cache")

    # Общее сравнение
    speedup_avg = no_cache.avg_ms / with_redis.avg_ms if with_redis.avg_ms > 0 else 0
    speedup_p95 = no_cache.p95_ms / with_redis.p95_ms if with_redis.p95_ms > 0 else 0
    rps_gain = ((with_redis.rps - no_cache.rps) / no_cache.rps * 100) if no_cache.rps > 0 else 0

    print(f"""
  ┌──────────────────────┬──────────────────┬──────────────────┬────────────┐
  │     Метрика          │   No Cache       │   With Redis     │  Разница   │
  ├──────────────────────┼──────────────────┼──────────────────┼────────────┤
  │ Throughput (RPS)     │ {no_cache.rps:>11.1f} r/s │ {with_redis.rps:>11.1f} r/s │ {rps_gain:>+8.1f}%  │
  │ Avg latency          │ {no_cache.avg_ms:>11.2f} ms  │ {with_redis.avg_ms:>11.2f} ms  │ ×{speedup_avg:>7.2f}  │
  │ Median latency       │ {no_cache.median_ms:>11.2f} ms  │ {with_redis.median_ms:>11.2f} ms  │            │
  │ P95 latency          │ {no_cache.p95_ms:>11.2f} ms  │ {with_redis.p95_ms:>11.2f} ms  │ ×{speedup_p95:>7.2f}  │
  │ P99 latency          │ {no_cache.p99_ms:>11.2f} ms  │ {with_redis.p99_ms:>11.2f} ms  │            │
  │ Ошибки               │ {no_cache.total_errors:>11d}     │ {with_redis.total_errors:>11d}     │            │
  └──────────────────────┴──────────────────┴──────────────────┴────────────┘""")

    # Сравнение по каждому кешируемому эндпоинту
    print(f"\n  📊 Детализация по эндпоинтам (Avg ms):")
    print(f"  {'Endpoint':<28} {'No Cache':>10} {'Redis':>10} {'Speedup':>10} {'Кеш?':>6}")
    print(f"  {'─' * 68}")

    cached_endpoints = {
        "GET /categories/", "GET /products/popular",
        "GET /products/1", "GET /products/2", "GET /products/3",
        "GET /products/5", "GET /products/10", "GET /products/15",
    }

    all_names = sorted(set(list(no_cache.by_endpoint.keys()) + list(with_redis.by_endpoint.keys())))

    for name in all_names:
        nc = no_cache.by_endpoint.get(name)
        wr = with_redis.by_endpoint.get(name)
        nc_avg = nc.avg_ms if nc and nc.count > 0 else 0
        wr_avg = wr.avg_ms if wr and wr.count > 0 else 0

        if nc_avg > 0 and wr_avg > 0:
            speedup = nc_avg / wr_avg
            speedup_str = f"×{speedup:.2f}"
        else:
            speedup_str = "—"

        is_cached = "✅" if name in cached_endpoints else "❌"
        print(f"  {name:<28} {nc_avg:>8.2f}ms {wr_avg:>8.2f}ms {speedup_str:>10} {is_cached:>6}")

    # Итоговая оценка
    print()
    print("  ═" * 35)

    # Считаем средний speedup только для кешируемых
    cached_speedups = []
    uncached_speedups = []
    for name in all_names:
        nc = no_cache.by_endpoint.get(name)
        wr = with_redis.by_endpoint.get(name)
        if nc and wr and nc.count > 0 and wr.count > 0 and wr.avg_ms > 0:
            s = nc.avg_ms / wr.avg_ms
            if name in cached_endpoints:
                cached_speedups.append(s)
            else:
                uncached_speedups.append(s)

    if cached_speedups:
        avg_cached = statistics.mean(cached_speedups)
        print(f"\n  🔴 Кешируемые эндпоинты:   в среднем ×{avg_cached:.2f} быстрее с Redis")
    if uncached_speedups:
        avg_uncached = statistics.mean(uncached_speedups)
        print(f"  ⚪ Некешируемые эндпоинты: в среднем ×{avg_uncached:.2f} (≈ одинаково)")

    print(f"\n  📈 Общий прирост RPS: {rps_gain:+.1f}%")

    if speedup_avg >= 2:
        print(f"\n  🏆 ВЫВОД: Redis даёт ×{speedup_avg:.1f} ускорение по средней задержке!")
    elif speedup_avg >= 1.3:
        print(f"\n  ✅ ВЫВОД: Redis даёт заметное ускорение ×{speedup_avg:.1f}")
    else:
        print(f"\n  ℹ️  ВЫВОД: На малых данных разница невелика ({speedup_avg:.2f}×),")
        print(f"      но на больших объёмах и высоких нагрузках Redis значительно выигрывает.")

    print()


# ─── main ────────────────────────────────────────────────────────

async def main():
    print_header("🔬 BENCHMARK: No Cache vs Redis Cache")
    print(f"  Параметры: {CONCURRENT_USERS} users × {REQUESTS_PER_USER} req = {TOTAL_REQUESTS} total")
    print(f"  Прогрев:   {WARMUP_REQUESTS} запросов")
    print()

    # Проверяем доступность серверов
    async with aiohttp.ClientSession() as session:
        for name, url in [("01_no_cache", NO_CACHE_URL), ("02_with_redis", WITH_REDIS_URL)]:
            try:
                async with session.get(f"{url}/health") as resp:
                    data = await resp.json()
                    print(f"  ✅ {name} ({url}) — {data}")
            except Exception as e:
                print(f"  ❌ {name} ({url}) — НЕДОСТУПЕН: {e}")
                print("\n  Убедитесь что оба Docker Compose запущены!")
                sys.exit(1)

    # Тест 1: No Cache
    print_header("🧪 Тест 1: No Cache (port 8000)")
    no_cache_result = await run_benchmark("01_no_cache (без кеша)", NO_CACHE_URL)
    print_result(no_cache_result)

    # Пауза между тестами
    print("\n  ⏸  Пауза 2 сек перед следующим тестом…")
    await asyncio.sleep(2)

    # Тест 2: With Redis
    print_header("🧪 Тест 2: With Redis (port 8001)")
    with_redis_result = await run_benchmark("02_with_redis (с Redis)", WITH_REDIS_URL)
    print_result(with_redis_result)

    # Сравнение
    print_comparison(no_cache_result, with_redis_result)


if __name__ == "__main__":
    asyncio.run(main())
