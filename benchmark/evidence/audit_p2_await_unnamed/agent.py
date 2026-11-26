import asyncio

async def lookup(tools, k):
    return await asyncio.wait_for(tools.call(k), 5)

async def pay(http, url):
    return await http.post(url)          # a tool in all but name, no timeout: can hang forever
