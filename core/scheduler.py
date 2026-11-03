"""Prosty scheduler w wątku: zadania co N sekund, log w jobs_log."""
import threading, time, traceback
from . import db
class Scheduler:
    def __init__(self):
        self.jobs = []
        self._stop = threading.Event()
        self._thread = None
    def add(self, bot, name, every_s, fn):
        self.jobs.append(dict(bot=bot, name=name, every=every_s, fn=fn, next=time.time() + 30))
    def run_now(self, bot, name):
        for j in self.jobs:
            if j["bot"] == bot and j["name"] == name:
                return self._run(j)
    def _run(self, j):
        try:
            info = j["fn"]()
            st = "ok"
        except Exception:
            info = traceback.format_exc()[-800:]
            st = "error"
        db.execute("INSERT INTO jobs_log(bot,job,status,info) VALUES(?,?,?,?)", (j["bot"], j["name"], st, str(info)[:2000]))
        j["next"] = time.time() + j["every"]
        return st, info
    def loop(self):
        while not self._stop.is_set():
            for j in self.jobs:
                if time.time() >= j["next"]:
                    self._run(j)
            self._stop.wait(15)
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self.loop, daemon=True, name="SchedulerLoop")
            self._thread.start()
    def stop(self):
        self._stop.set()
