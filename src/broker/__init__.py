"""
Paquete de integración con el broker (IBKR vía ib_insync).

IMPORTANTE: ib_insync (a través de eventkit) busca un event loop de asyncio al
importarse. Streamlit corre el script en un hilo secundario que NO tiene event
loop, lo que rompe el import con:

    RuntimeError: There is no current event loop in thread 'ScriptRunner...'

Este __init__ se ejecuta antes que cualquier submódulo (session/orders/ibkr) y,
por ende, antes de cualquier import de ib_insync. Por eso garantizamos acá que el
hilo actual tenga un event loop.
"""
import asyncio

try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())
