import threading
import select
import time


class Multiplexer(object):
    """
   一个用于管理后台处理的多路复用器类，它监听多个后台处理的读取事件，并在事件发生时调用相应的处理函数。

   方法:
   - __init__: 初始化多路复用器，设置后台处理的索引、读取索引和停止标志，并启动监听线程。
   - add_backend: 向多路复用器中添加一个后台处理，并根据是否已停止来决定是否重新启动监听线程。
   - remove_and_close: 从多路复用器中移除并关闭一个后台处理，如果所有后台处理都已移除，则停止监听。
   - stop: 设置停止标志，用于停止监听线程。
   - listen: 监听后台处理的读取事件，并在事件发生时调用相应的处理函数。
   """

    def __init__(self):
        """
        初始化多路复用器，设置后台处理的索引、读取索引和停止标志，并启动监听线程。
        """
        self.backend_index = {}
        self.read_index = {}
        self.stop_flag = False

        self.thread = threading.Thread(target=self.listen)
        self.thread.start()

    def add_backend(self, backend):
        """
       向多路复用器中添加一个后台处理，并根据是否已停止来决定是否重新启动监听线程。

       参数:
       - backend: 要添加的后台处理对象。
       """
        self.backend_index[backend.id] = backend
        self.read_index[backend.get_read_wait()] = backend
        print(f"Backend {backend.id} added")

        if self.stop_flag:
            self.stop_flag = False
            self.thread = threading.Thread(target=self.listen)
            self.thread.start()

    def remove_and_close(self, backend):
        """
       从多路复用器中移除并关闭一个后台处理，如果所有后台处理都已移除，则停止监听。

       参数:
       - backend: 要移除并关闭的后台处理对象。
       """
        if backend.id in self.backend_index:
            print(f"Backend {backend.id} removed and closed")
            self.read_index.pop(self.backend_index.pop(backend.id).get_read_wait())

        if len(self.backend_index) <= 0:
            self.stop()

    def stop(self):
        """
        设置停止标志，用于停止监听线程。
        """
        self.stop_flag = True

    def listen(self):
        """
        监听后台处理的读取事件，并在事件发生时调用相应的处理函数。
        """
        while not self.stop_flag:
            read_wait_list = [a.get_read_wait() for a in self.backend_index.values()]
            if read_wait_list:
                try:
                    read_ready_list, write_ready_list, error_ready_list = select.select(read_wait_list, [], [], 0.1)
                except Exception as e:
                    print(f"Select error: {e}")
                    read_ready_list = []

                for read_item in read_ready_list:
                    backend = self.read_index.get(read_item)
                    if backend:
                        backend.read()
            else:
                time.sleep(1)


mux = Multiplexer()
