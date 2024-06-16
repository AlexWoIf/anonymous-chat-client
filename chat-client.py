import asyncio
import gui
import time


async def ping(messages_queue, delay=1, ):
    while True:
        messages_queue.put_nowait(f'Ping {int(time.time())}')
        await asyncio.sleep(delay)


async def main():
    messages_queue = asyncio.Queue()
    sending_queue = asyncio.Queue()
    status_updates_queue = asyncio.Queue()

    await asyncio.gather(
        gui.draw(messages_queue, sending_queue, status_updates_queue),
        ping(messages_queue))


if __name__ == '__main__':
    asyncio.run(main())