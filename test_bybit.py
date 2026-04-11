import asyncio
import traceback
import aiohttp
import ccxt.async_support as ccxt


async def main():
    # Принудительно используем системный DNS (getaddrinfo) вместо aiodns/c-ares
    connector = aiohttp.TCPConnector(
        resolver=aiohttp.ThreadedResolver(),
        ssl=True,
    )
    session = aiohttp.ClientSession(connector=connector, trust_env=True)

    exchange = ccxt.bybit({
        'enableRateLimit': True,
        'timeout': 30000,
        'session': session,
        'options': {
            'defaultType': 'linear',
            'fetchMarkets': ['linear'],
        },
    })
    try:
        print("=== load_markets ===")
        markets = await exchange.load_markets()
        print(f"OK: loaded {len(markets)} markets")
        print(f"ETH/USDT:USDT present: {'ETH/USDT:USDT' in markets}")

        print("\n=== fetch_ohlcv ETH/USDT:USDT 15m ===")
        bars = await exchange.fetch_ohlcv('ETH/USDT:USDT', timeframe='15m', limit=5)
        print(f"OK: {len(bars)} candles")
        for b in bars:
            print(b)

        print("\n=== fetch_funding_rate ETH/USDT:USDT ===")
        fr = await exchange.fetch_funding_rate('ETH/USDT:USDT')
        print(f"OK: fundingRate = {fr.get('fundingRate')}")
    except Exception as e:
        print(f"\nFAIL: [{type(e).__name__}] {e}")
        traceback.print_exc()
    finally:
        await exchange.close()
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
