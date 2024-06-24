import asyncio
import json
import logging
import socket
from contextlib import asynccontextmanager
from functools import wraps
from tkinter import TclError, messagebox

import aiofiles
import configargparse
from anyio import create_task_group
from async_timeout import timeout

import gui
from constants import *


def import_config():
    parser = configargparse.ArgParser(default_config_files=['.env', ])
    parser.add('--host', '--HOST', help='server address')
    parser.add('--reading_port', '--READING_PORT', help='reading server port')
    parser.add('--writing_port', '--WRITING_PORT', help='writing server port')
    parser.add('--logfile', '--LOGFILE', help='log filepath')
    parser.add('--token', '--TOKEN', help='user token')
    parser.add('--nickname')

    args, _ = parser.parse_known_args()
    print(args)
    return vars(args)


def retry(handler):
    @wraps(handler)
    async def _wrapper(*args, **kwargs):
        retry = 0
        while True:
            try:
                await handler(*args, **kwargs)
                break
            except (ConnectionError, socket.gaierror):
                logging.error(f'Connection error. Sleeping {retry}sec(s)')
                await asyncio.sleep(retry)
                retry = (retry + 1) * 2
            except (ValueError, KeyError):
                logging.error('Неизвестный токен')
    return _wrapper


async def write_message_to_file(file_path, content):
    async with aiofiles.open(file_path, mode='a', ) as f:
        await f.write(content)


async def read_messages_from_file(file_path, queues):
    async with aiofiles.open(file_path, mode='rb') as f:
        async for line in f:
            queues['messages_queue'].put_nowait(line.decode('cp1251').strip())


@retry
async def handle_connection(config, queues):
    async with connection_manager(config, queues) as write_connection:
        queues['status_updates_queue'].put_nowait(
            gui.SendingConnectionStateChanged.ESTABLISHED
        )
        try:
            nickname = await authorise(write_connection, config['token'])
            config['nickname'] = nickname
            event = gui.NicknameReceived(nickname)
            queues['status_updates_queue'].put_nowait(event)
            queues['watchdog_queue'].put_nowait('Authorization done')
        except (KeyError, ValueError):
            logging.error("Unknown or wrong token. Check it and try again.")
            messagebox.showinfo(
                "Token error",
                "Unknown or wrong token. Check it and try again."
            )
            return

        host = config['host']
        port = config['reading_port']
        read_connection = await asyncio.open_connection(host, port)
        queues['status_updates_queue'].put_nowait(
            gui.ReadConnectionStateChanged.ESTABLISHED
        )

        async with create_task_group() as task_group:
            task_group.start_soon(send_messages, write_connection, queues)
            task_group.start_soon(read_messages,
                                  read_connection, queues, config['logfile'])
            task_group.start_soon(ping_server, write_connection, queues)
            task_group.start_soon(watch_for_connection, queues)


async def ping_server(write_connection, queues):
    while True:
        message = ''

        reader, writer = write_connection

        received_msg = await reader.readline()
        decoded_msg = received_msg.decode().strip()
        logging.debug(decoded_msg)

        if decoded_msg != WELCOME_PROMPT and decoded_msg != ACCEPT_PROMPT:
            raise socket.gaierror

        # logging.debug(f'Send message from {nickname}:"{message}"')
        writer.write(f'{message}\n\n'.encode())
        await writer.drain()
        queues['watchdog_queue'].put_nowait('Ping message sent')
        await asyncio.sleep(CONNECTION_TIMEOUT)


async def watch_for_connection(queues):
    while True:
        try:
            async with timeout(CONNECTION_TIMEOUT*2) as cm:
                message = await queues['watchdog_queue'].get()
            queues['status_updates_queue'].put_nowait(
                gui.ReadConnectionStateChanged.ESTABLISHED
            )
        except asyncio.TimeoutError:
            if cm.expired:
                message = f'{CONNECTION_TIMEOUT*2}s Timeout is elapsed'
            queues['status_updates_queue'].put_nowait(
                gui.ReadConnectionStateChanged.CLOSED
            )
        logging.info(message)


async def read_messages(read_connection, queues, file_path):
    reader, _ = read_connection
    while True:
        received_msg = await reader.readline()
        decoded_msg = received_msg.decode()
        queues['messages_queue'].put_nowait(decoded_msg.strip())
        await write_message_to_file(file_path, decoded_msg)
        queues['watchdog_queue'].put_nowait('New message in chat')


async def send_messages(write_connection, queues):
    while True:
        message = await queues['sending_queue'].get()

        reader, writer = write_connection

        received_msg = await reader.readline()
        decoded_msg = received_msg.decode().strip()
        logging.debug(decoded_msg)

        if decoded_msg != WELCOME_PROMPT and decoded_msg != ACCEPT_PROMPT:
            raise socket.gaierror

        # logging.debug(f'Send message from {nickname}:"{message}"')
        writer.write(f'{message}\n\n'.encode())
        await writer.drain()
        queues['watchdog_queue'].put_nowait('Message sent')


async def authorise(connection, token):
    reader, writer = connection
    received_msg = await reader.readline()
    decoded_msg = received_msg.decode().strip()
    logging.debug(decoded_msg)

    if decoded_msg != HELLO_PROMPT:
        raise RuntimeError

    writer.write(f'{token}\n'.encode())
    await writer.drain()
    answer = await reader.readline()
    decoded_answer = answer.decode().strip()
    logging.debug(decoded_answer)
    if decoded_answer == 'null':
        raise ValueError
    nickname = json.loads(decoded_answer).get('nickname')
    return nickname


@asynccontextmanager
async def connection_manager(config, queues):
    host = config['host']
    port = config['writing_port']
    reader, writer = await asyncio.open_connection(host, port)
    try:
        yield reader, writer
    finally:
        writer.close()
        await writer.wait_closed()
        status_updates_queue = queues['status_updates_queue']
        status_updates_queue.put_nowait(
            gui.SendingConnectionStateChanged.CLOSED
        )


async def main():
    config = import_config()

    logging.basicConfig(
        format='%(levelname)s:%(filename)s:[%(asctime)s] %(message)s',
        level=logging.DEBUG,
    )
    filepath = config.get('logfile', f'{__name__}.log')
    config['logfile'] = filepath

    messages_queue = asyncio.Queue()
    sending_queue = asyncio.Queue()
    status_updates_queue = asyncio.Queue()
    watchdog_queue = asyncio.Queue()

    queues = {'messages_queue': messages_queue, 'sending_queue': sending_queue,
              'status_updates_queue': status_updates_queue,
              'watchdog_queue': watchdog_queue, }

    await read_messages_from_file(config['logfile'], queues)

    async with create_task_group() as task_group:
        task_group.start_soon(gui.draw, messages_queue, sending_queue,
                              status_updates_queue)
        task_group.start_soon(handle_connection, config, queues)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except* (TclError, KeyboardInterrupt):
        pass
