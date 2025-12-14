import asyncio
import aiohttp
import json

BUFFER = 65536

async def message(index:int = 1):
    async with aiohttp.ClientSession() as session:
        endpoint = f"https://jsonplaceholder.typicode.com/todos/{index}"
        async with session.get(endpoint) as resp:
            json_data = await resp.json()
            return json_data


async def start(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    index = 1
    while True:
        json_message = await message(index=index)
        encoded_message = json.dumps(json_message).encode('utf-8')
        writer.write(encoded_message)
        await writer.drain()
        index += 1
        data = await reader.read(BUFFER)
        if not data:
            writer.close()
            await writer.wait_closed()
            break
        
        print(data.decode())
        await asyncio.sleep(2)

    

async def main():
    reader, writer = await asyncio.open_connection('127.0.0.1', 8887)
    if reader and reader != None:
        task = asyncio.create_task(start(reader, writer))
        if task:
            print('task created')
            await asyncio.gather(task)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass