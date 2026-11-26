import threading
lock = threading.Lock()
guard = threading.Lock()

def a():
    with lock:
        pass

def b(tools):
    guard.acquire()                       # never released on an exception
    tools.call(1)
    guard.release()
