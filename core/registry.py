"""Rejestr botów. Każdy bot to klasa z interfejsem BotBase."""
class BotBase:
    id = "base"; name = "Bot"; description = ""; avatar = ""   # avatar: klucz animacji SVG w UI
    def init(self, app): ...          # rejestruje trasy API (Blueprint) itp.
    def jobs(self): return []         # lista (nazwa, interwał_s, funkcja) dla schedulera
    def status(self): return {}       # stan / klucze / źródła
BOTS = {}
def register(bot): BOTS[bot.id] = bot; return bot
