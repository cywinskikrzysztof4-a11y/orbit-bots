"""Warstwa powiadomień: zapis do SQLite + opcjonalne kanały (np. webhook) dodawane później."""
from . import db
_channels = []
def add_channel(fn): _channels.append(fn)
def notify(bot, title, body):
    i = db.execute("INSERT INTO alerts_log(bot,title,body) VALUES(?,?,?)", (bot, title, body))
    for ch in _channels:
        try: ch(bot, title, body)
        except Exception as e: print("channel error", e)
    return i
def recent(limit=50): return db.query("SELECT * FROM alerts_log ORDER BY id DESC LIMIT ?", (limit,))
def mark_all_read(): return db.execute("UPDATE alerts_log SET read=1 WHERE read=0")
def unread_count():
    r = db.query("SELECT COUNT(*) AS c FROM alerts_log WHERE read=0")
    return r[0]["c"] if r else 0
