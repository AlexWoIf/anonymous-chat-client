import aiofiles
import asyncio
import logging
import socket
import time

import configargparse

import gui


def import_config():
    parser = configargparse.ArgParser(default_config_files=['.env', ])
    parser.add('--host', '--HOST', help='server address')
    parser.add('--reading_port', '--READING_PORT', help='server port')
    parser.add('--logfile', '--LOGFILE', help='log filepath')
    args, _ = parser.parse_known_args()
    print(args)
    return vars(args)


async def write_to_file(file_path, content):
    async with aiofiles.open(file_path, mode='a', ) as f:
        await f.write(content.strip())


async def read_file(filepath, messages_queue):
    async with aiofiles.open(filepath, mode='rb') as f:
        async for line in f:
            messages_queue.put_nowait(line.decode('cp1251').strip())


async def read_message(config):
    host, port, _ = config.values()
    reader, _ = await asyncio.open_connection(host, port)
    received_msg = await reader.readline()
    decoded_msg = received_msg.decode()
    # logging.debug(decoded_msg)
    return decoded_msg


async def print_message(messages_queue, config, ):
    while True:
        message = await read_message(config)
        messages_queue.put_nowait(message.strip())
        filepath = config.get('logfile', f'{__name__}.log')
        await write_to_file(filepath, message)


async def main():
    messages_queue = asyncio.Queue()
    sending_queue = asyncio.Queue()
    status_updates_queue = asyncio.Queue()

    config = import_config()

    await read_file(config['logfile'], messages_queue)

    await asyncio.gather(
        gui.draw(messages_queue, sending_queue, status_updates_queue),
        print_message(messages_queue, config))


if __name__ == '__main__':
    asyncio.run(main())
