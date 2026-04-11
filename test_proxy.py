import asyncio
import traceback
import aiohttp
from aiohttp_socks import ProxyConnector
import ccxt.async_support as ccxt

# SOCKS5 прокси. rdns=True — DNS-резолв делает сам прокси на своей стороне,
# поэтому aiodns/c-ares нам тут не мешают.
PROXY_URL = 'socks5://nXhVPQ:GS2eLR@168.80.73.142:8000'


def make_session():
    connector = ProxyConnector.from_url(PROXY_URL, rdns=True)
    return aiohttp.ClientSession(connector=connector)


async def test_plain():
    """Проверяем, что ipinfo видит наш exit-IP через SOCKS5."""
    async with make_session() as session:
        try:
            async with session.get(
                'https://ipinfo.io/json',
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                data = await resp.json()
                print(f"OK: ip={data.get('ip')}  country={data.get('country')}  "
                      f"city={data.get('city')}  org={data.get('org')}")
        except Exception as e:
            print(f"FAIL plain: [{type(e).__name__}] {e}")
            traceback.print_exc()


async def test_bybit():
    """Проверяем ccxt Bybit через тот же SOCKS5."""
    session = make_session()
    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'timeout': 30000,
        'session': session,  # ccxt возьмёт уже настроенный коннектор
        'options': {
            'defaultType': 'linear',
            'fetchMarkets': ['linear'],
        },
    })
    try:
        print("\n--- load_markets via SOCKS5 ---")
        markets = await exchange.load_markets()
        print(f"OK: loaded {len(markets)} markets")
        print(f"ETH/USDT:USDT present: {'ETH/USDT:USDT' in markets}")

        print("\n--- fetch_ohlcv ETH/USDT:USDT 15m ---")
        bars = await exchange.fetch_ohlcv('ETH/USDT:USDT', timeframe='15m', limit=3)
        for b in bars:
            print(b)

        print("\n--- fetch_funding_rate ETH/USDT:USDT ---")
        fr = await exchange.fetch_funding_rate('ETH/USDT:USDT')
        print(f"fundingRate = {fr.get('fundingRate')}")
    except Exception as e:
        print(f"\nFAIL Bybit: [{type(e).__name__}] {e}")
        traceback.print_exc()
    finally:
        await exchange.close()
        await session.close()


async def main():
    print("=== 1. Plain SOCKS5 check (ipinfo.io) ===")
    await test_plain()
    print("\n=== 2. Bybit via SOCKS5 ===")
    await test_bybit()


if __name__ == "__main__":
    asyncio.run(main())
