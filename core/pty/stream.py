from pyte.streams import ByteStream


class QTerminalStream(ByteStream):

    def __init__(self, *args, **kwargs):
        super(QTerminalStream, self).__init__(*args, **kwargs)
