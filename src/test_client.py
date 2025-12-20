import asyncio
import argparse

BUFFER = 65536

async def start(reader:asyncio.StreamReader, writer:asyncio.StreamWriter):
    index = 1
    while True:
        payload = f"msg-{index}\n".encode("utf-8")
        writer.write(payload)
        await writer.drain()
        index += 1
        data = await reader.read(BUFFER)
        if not data:
            writer.close()
            await writer.wait_closed()
            break
        
        print(data.decode(errors="replace"), end="")
        await asyncio.sleep(2)

    

async def main(host='127.0.0.1', port=8887):
    reader, writer = await asyncio.open_connection(host=host, port=port)
    if reader and reader != None:
        task = asyncio.create_task(start(reader, writer))
        if task:
            print('task created')
            await asyncio.gather(task)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('-H', '--host', required=True)
        parser.add_argument('-P', '--port', required=True)
        args = parser.parse_args()
        asyncio.run(main(args.host, int(args.port)))
    except KeyboardInterrupt:
        pass