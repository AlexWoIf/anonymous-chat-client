import asyncio
import json
import logging
import socket
import time
from async_timeout import timeout
from contextlib import asynccontextmanager
from tkinter import messagebox

import aiofiles
import configargparse

import gui

HELLO_PROMPT = 'Hello %username%! Enter your personal hash or leave it empty to create new account.'
WELCOME_PROMPT = 'Welcome to chat! Post your message below. End it with an empty line.'
REGISTER_PROMPT = 'Enter preferred nickname below:'
CONNECTION_TIMEOUT = 1


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


@asynccontextmanager
async def connection_manager(config):
    host = config['host']
    port = config['writing_port']
    reader, writer = await asyncio.open_connection(host, port)
    try:
        yield reader, writer
    finally:
        writer.close()
        await writer.wait_closed()
        status_updates_queue = config['status_updates_queue']
        status_updates_queue.put_nowait(
            gui.SendingConnectionStateChanged.CLOSED
        )


async def authorise(reader, writer, token):
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


async def get_registered_username(config):
    token = config['token']
    status_updates_queue = config['status_updates_queue']
    watchdog_queue = config['watchdog_queue']

    async with connection_manager(config) as (reader, writer):
        status_updates_queue.put_nowait(
            gui.SendingConnectionStateChanged.ESTABLISHED
        )
        watchdog_queue.put_nowait('Authorization done')
        return await authorise(reader, writer, token)


async def submit_message(message, config):
    token = config['token']

    async with connection_manager(config) as (reader, writer):
        status_updates_queue = config['status_updates_queue']
        status_updates_queue.put_nowait(
            gui.SendingConnectionStateChanged.ESTABLISHED
        )
        nickname = await authorise(reader, writer, token)
        received_msg = await reader.readline()
        decoded_msg = received_msg.decode().strip()
        logging.debug(decoded_msg)

        if decoded_msg != WELCOME_PROMPT:
            raise RuntimeError

        logging.debug(f'Send message from {nickname}:"{message}"')
        writer.write(f'{message}\n\n'.encode())
        await writer.drain()


async def write_message_to_file(file_path, content):
    async with aiofiles.open(file_path, mode='a', ) as f:
        await f.write(content)


async def read_messages_from_file(filepath, messages_queue):
    async with aiofiles.open(filepath, mode='rb') as f:
        async for line in f:
            messages_queue.put_nowait(line.decode('cp1251').strip())


async def read_message_from_chat(config):
    host = config['host']
    port = config['reading_port']
    reader, _ = await asyncio.open_connection(host, port)
    status_updates_queue = config['status_updates_queue']
    status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.ESTABLISHED)
    received_msg = await reader.readline()
    decoded_msg = received_msg.decode()
    # logging.debug(decoded_msg)
    return decoded_msg


async def print_message(config):
    messages_queue = config['messages_queue']
    watchdog_queue = config['watchdog_queue']
    status_updates_queue = config['status_updates_queue']

    status_updates_queue.put_nowait(gui.ReadConnectionStateChanged.INITIATED)
    while True:
        message = await read_message_from_chat(config)
        messages_queue.put_nowait(message.strip())
        filepath = config['logfile']
        await write_message_to_file(filepath, message)
        watchdog_queue.put_nowait('New message in chat')


async def read_message_from_gui(config):
    sending_queue = config['sending_queue']

    while True:
        message = await sending_queue.get()
        await submit_message(f'{message}\n', config)


async def watch_for_connection(watchdog_queue):
    while True:
        try:
            async with timeout(CONNECTION_TIMEOUT) as cm:
                message = await watchdog_queue.get()
        except asyncio.TimeoutError:
            if cm.expired:
                message = f'{CONNECTION_TIMEOUT}s Timeout is elapsed'
        logging.info(message)


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
    config['messages_queue'] = messages_queue
    config['sending_queue'] = sending_queue
    config['status_updates_queue'] = status_updates_queue
    config['watchdog_queue'] = watchdog_queue
    await read_messages_from_file(filepath, messages_queue)

    if config.get('token') is not None:
        try:
            nickname = await get_registered_username(config)
            event = gui.NicknameReceived(nickname)
            status_updates_queue.put_nowait(event)
        except ValueError:
            logging.error("Unknown or wrong token. Check it and try again.")
            messagebox.showinfo(
                "Token error",
                "Unknown or wrong token. Check it and try again."
            )
            return

    await asyncio.gather(
        gui.draw(messages_queue, sending_queue, status_updates_queue),
        print_message(config),
        read_message_from_gui(config),
        watch_for_connection(watchdog_queue)
    )


if __name__ == '__main__':
    asyncio.run(main())
