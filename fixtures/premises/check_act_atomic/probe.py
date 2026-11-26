"""python probe.py DIR: can two worker processes spend past the limit together?

Two processes run spend.py in DIR and each spends 60 of a limit of 100, so at most one may be let
through. The first is stopped before its k-th line of the code in DIR, the second then runs to its
end, and the first goes on, for every k there is. So every place where the first can be overtaken is
tried, and no answer depends on timing. The premise holds when no run lets both through.

What the processes share: a file of their own a run (SPEND_COUNT_FILE), and a server on this machine
(SPEND_REDIS_PORT) that speaks the part of Redis's protocol an INCRBY needs, with a module named redis
as its client. The server runs one command at a time: that is the assumption the established fixture
names, made true here rather than shown of Redis.
Written for KAMANU task T5.
"""
import json
import os
import socketserver
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

CLIENT = '''
import socket


class Redis:
    def __init__(self, host="localhost", port=6379):
        self.address = (host, port)

    def incrby(self, name, amount=1):
        words = [b"INCRBY", str(name).encode(), str(amount).encode()]
        frame = b"*%d\\r\\n" % len(words) + b"".join(b"$%d\\r\\n%s\\r\\n" % (len(w), w) for w in words)
        with socket.create_connection(self.address, timeout=30) as link:
            link.sendall(frame)
            answer = link.makefile("rb").readline()
        assert answer.startswith(b":"), answer
        return int(answer[1:])

    incr = incrby

    def decrby(self, name, amount=1):
        return self.incrby(name, -amount)

    decr = decrby
'''


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        count = int(self.rfile.readline()[1:])
        words = []
        for _ in range(count):
            size = int(self.rfile.readline()[1:])
            words.append(self.rfile.read(size + 2)[:-2])
        _, key, amount = words
        counts = self.server.counts
        counts[key] = counts.get(key, 0) + int(amount)
        self.wfile.write(b":%d\r\n" % counts[key])


def worker(directory, stop_at):
    """Spend once. Stop before the stop_at-th line of the code in directory until a line comes on stdin."""
    sys.path.insert(0, directory)
    seen = [0]
    here = os.path.normcase(os.path.realpath(directory))

    def trace(frame, event, arg):
        if os.path.dirname(os.path.normcase(os.path.realpath(frame.f_code.co_filename))) != here:
            return None
        if event == "line":
            seen[0] += 1
            if seen[0] == stop_at:
                print("stopped", flush=True)
                sys.stdin.readline()
        return trace

    import spend
    sys.settrace(trace)
    admitted = spend.spend("order", 60)
    sys.settrace(None)
    print(json.dumps({"admitted": bool(admitted)}), flush=True)


def both_admitted(directory, work, port, k):
    """(whether both were let through, whether the first had a k-th line)."""
    env = dict(os.environ, SPEND_COUNT_FILE=str(work / f"count-{k}"), SPEND_REDIS_PORT=str(port),
               PYTHONPATH=str(work / "client"), PYTHONDONTWRITEBYTECODE="1")

    def start(stop_at):
        return subprocess.Popen([sys.executable, __file__, "--worker", directory, str(stop_at)], env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    first = start(k)
    said = first.stdout.readline().strip()
    stopped = said == "stopped"
    second = start(0)
    answer, _ = second.communicate(timeout=60)
    if stopped:
        said, _ = first.communicate("go\n", timeout=60)
    else:
        first.communicate(timeout=60)
    assert first.returncode == 0 and second.returncode == 0, "a worker failed"
    return json.loads(said)["admitted"] and json.loads(answer)["admitted"], stopped


def main(directory):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "client").mkdir()
        (work / "client" / "redis.py").write_text(CLIENT, encoding="utf-8")
        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:     # one request at a time
            threading.Thread(target=server.serve_forever, daemon=True).start()
            holds, k, more = True, 1, True
            while more:
                server.counts = {}
                both, more = both_admitted(directory, work, server.server_address[1], k)
                holds = holds and not both
                k += 1
            server.shutdown()
    print(json.dumps({"holds": holds}))


if __name__ == "__main__":
    if sys.argv[1] == "--worker":
        worker(sys.argv[2], int(sys.argv[3]))
    else:
        main(sys.argv[1])
