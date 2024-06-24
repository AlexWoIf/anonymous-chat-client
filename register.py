import asyncio
import json
import logging
from contextlib import asynccontextmanager
from tkinter import *

import configargparse

from constants import *


class Block:
    def __init__(self, master):
        self.label = Label(master, text='Введите желаемый nickname')
        self.entry_field = Entry(master, width=20)
        self.button = Button(master, text="Ok")
        self.button['command'] = self.wrapper
        self.token = Label(master)
        self.label.pack()
        self.entry_field.pack()
        self.button.pack()
        self.token.pack()
        self.config = self.import_config()

    def wrapper(self):
        asyncio.run(self.register_user())

    @asynccontextmanager
    async def connection_manager(self, host, port):
        reader, writer = await asyncio.open_connection(host, port)
        try:
            yield reader, writer
        finally:
            writer.close()
            await writer.wait_closed()

    async def register_user(self):
        host = self.config['host']
        port = self.config['writing_port']
        nickname = self.entry_field.get()
        async with self.connection_manager(host, port) as (reader, writer):
            received_msg = await reader.readline()
            decoded_msg = received_msg.decode().strip()
            logging.debug(decoded_msg)

            if decoded_msg != HELLO_PROMPT:
                raise RuntimeError

            writer.write('\n'.encode())
            await writer.drain()

            received_msg = await reader.readline()
            decoded_msg = received_msg.decode().strip()
            logging.debug(decoded_msg)

            if decoded_msg != REGISTER_PROMPT:
                raise RuntimeError

            writer.write(f'{nickname}\n'.encode())
            await writer.drain()

            received_msg = await reader.readline()
            decoded_msg = received_msg.decode().strip()
            logging.debug(decoded_msg)
            token = json.loads(decoded_msg).get('account_hash')
            self.config['token'] = token
            self.config['nickname'] = nickname
            self.token['text'] = token
            self.export_config()

    def import_config(self):
        parser = configargparse.ArgParser(default_config_files=['.env', ])
        parser.add('--host', '--HOST', help='server address')
        parser.add('--reading_port', '--READING_PORT', help='reading server port')
        parser.add('--writing_port', '--WRITING_PORT', help='server port')
        parser.add('--logfile', '--LOGFILE', help='log filepath')
        parser.add('--token', '--TOKEN', help='user token')
        parser.add('--nickname')

        args, _ = parser.parse_known_args()

        return vars(args)

    def export_config(self):
        filepath = '.env'
        with open(filepath, 'w') as envfile:
            for key, value in self.config.items():
                envfile.write(f'{key}={value}\n')


if __name__ == '__main__':
    logging.basicConfig(
        format='%(levelname)s:%(filename)s:[%(asctime)s] %(message)s',
        level=logging.INFO,
    )
    root = Tk()
    root.title('Регистрация в чате')
    root.geometry('280x90+300+200')
    first_block = Block(root)
    root.mainloop()
