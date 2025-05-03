import uuid

from core.pty.screen import QTerminalScreen
from core.pty.stream import QTerminalStream


class BaseBackend(object):
    def __init__(self):
        self.screen = QTerminalScreen(200, 400, history=9999, ratio=.3)
        self.stream = QTerminalStream(self.screen)
        self.stream.attach(self.screen)
        self.id = str(uuid.uuid4())

    def write_to_screen(self, data):
        self.stream.feed(data)

    def read(self):
        pass

    def connect(self):
        pass

    def get_read_wait(self):
        pass

    def cursor(self):
        return self.screen.cursor

    def close(self):
        pass


class PtyBackend(BaseBackend):
    pass
