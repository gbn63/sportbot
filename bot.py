import os, json, time, datetime, requests, warnings
import numpy as np
from ddgs import DDGS

warnings.filterwarnings("ignore")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NOW_TLT = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=4)))

TG_HOST = "https://" + ".".join(["api", "telegram", "org"])
GEM_HOST = "https://" + ".".join(["generativelanguage", "googleapis", "com"])
MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0", "Accept": "application/json"}

def send_tg(text):
    try:
        r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200:
            print("TG HTTP error:", r.status_code, r.text[:100])
            return False
        return True
    except Exception as e:
        print("TG error:", e)
        return False

def web_search(q, n=5):
    try:
        with DDGS() as d:
            return "\n".join([f"- {r['title']}: {r['body']}" for r in d.text(q, max_results=n)])
    except Exception as e:
        return f"Search err: {e}"
def get_fonbet():
    now_ts = NOW_TLT.timestamp()
    for sub in ["line01", "line02", "line03"]:
        try:
            url = "https://" + sub + "://"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                print(f"Фонбет {sub} HTTP:", r.status_code)
                continue
            data = r.json()
            sports = {s["id"]: s.get("name", "") for s in data.get("sports", [])}
            fmap = {cf["e"]: {f["f"]: f["v"] for f in cf.get("factors", []) if "f" in f and "v" in f} for cf in data.get("customFactors", []) if "e" in cf}
            out = []
            for ev in data.get("events", []):
                if ev.get("place") != "line" or ev.get("level") != 1:
                    continue
                st_ts = ev.get("startTime", 0)
                if not (15 <= (st_ts - now_ts) / 60.0 <= 120):
                    continue
                t1, t2 = ev.get("team1", ""), ev.get("team2", "")
                f = fmap.get(ev["id"], {})
                odds = [f"{lbl}={f[fid]}" for fid, lbl in [(921, "П1"), (922, "Х"), (923, "П2"), (924, "1Х"), (925, "12"), (926, "Х2")] if fid in f]
                if t1 and t2 and odds:
                    st_str = datetime.datetime.fromtimestamp(st_ts, tz=NOW_TLT.tzinfo).strftime("%H:%M")
                    out.append(f"[{st_str}] {sports.get(ev.get('sportId'), '')} | {t1} — {t2} | {', '.join(odds)}")
            print(f"Фонбет ({sub}): {len(out)} матчей")
            return "\n".join(out[:45])
        except Exception as e:
            print(f"Фонбет {sub} err:", e)
    return "Фонбет недоступен с IP GitHub."

def get_polymarket():
    try:
        r = requests.get("https://polymarket.com", headers=HEADERS, timeout=12)
        if r.status_code != 200:
            print("Polymarket HTTP:", r.status_code)
            return ""
        out = []
        for ev in r.json():
            title = ev.get("title", "")
            for m in ev.get("markets", [])[:2]:
                q = m.get("question", title)
                outcomes = json.loads(m.get("outcomes", "[]")) if isinstance(m.get("outcomes"), str) else m.get("outcomes", [])
                prices = json.loads(m.get("outcomePrices", "[]")) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices", [])
                if q and len(outcomes) == len(prices) and prices:
                    probs = ", ".join([f"{o}: {round(float(p)*100, 1)}%" for o, p in zip(outcomes, prices)])
                    out.append(f"- {q} -> {probs}")
        print(f"Polymarket: {len(out)} рынков")
        return "\n".join(out[:25])
    except Exception as e:
        print("Polymarket err:", e)
        return ""

def get_sofascore():
    d_str, now_ts, out = NOW_TLT.strftime("%Y-%m-%d"), NOW_TLT.timestamp(), []
    sf_headers = {**HEADERS, "Referer": "https://sofascore.com", "Origin": "https://sofascore.com"}
    for sp in ["football", "ice-hockey", "basketball", "tennis"]:
        try:
            r = requests.get(f"https://sofascore.com{sp}/scheduled-events/{d_str}", headers=sf_headers, timeout=10)
            if r.status_code != 200:
                continue
            for ev in r.json().get("events", []):
                st_ts = ev.get("startTimestamp", 0)
                if 15 <= (st_ts - now_ts) / 60.0 <= 120:
                    st_str = datetime.datetime.fromtimestamp(st_ts, tz=NOW_TLT.tzinfo).strftime("%H:%M")
                    out.append(f"[{st_str}] {ev.get('tournament', {}).get('name', sp)}: {ev.get('homeTeam', {}).get('name', '')} — {ev.get('awayTeam', {}).get('name', '')}")
        except Exception:
            pass
    print(f"Sofascore: {len(out)} матчей")
    return "\n".join(out[:40])

def ask_ai(prompt):
    for m in MODELS:
        try:
            r = requests.post(f"{GEM_HOST}/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}, timeout=60)
            if r.status_code == 200:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                print(f"ИИ ({m}) ответил: {len(txt)} симв.")
                return txt
            print(f"Model {m} HTTP {r.status_code}")
            if r.status_code == 503:
                time.sleep(5)
        except Exception as e:
            print(f"Model {m} err:", e)
    return ""

def calc_stats(prob, odds, bank):
    ev = round(float(np.mean(np.where(np.random.default_rng().random(100_000) < prob, odds - 1.0, -1.0))) * 100, 2)
    b = odds - 1.0
    qk = max(0.0, min(0.05, ((prob * b - (1.0 - prob)) / b) * 0.25)) if b > 0 else 0.0
    return ev, round(qk * 100, 2), round(bank * qk, 0)

def check_results(history, rules):
    upd = False
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        st = datetime.datetime.fromisoformat(bet["start_iso"])
        if (NOW_TLT - st).total_seconds() / 3600.0 < 2.8:
            continue
        info = web_search(f"{bet['match']} результат счет {st.strftime('%d.%m.%Y')}")
        raw = ask_ai(f"Проверь итог. Матч: {bet['match']}. Ставка: {bet['pick']} ({bet['odds']}). Данные:\n{info}\nВерни JSON: {{\"status\": \"WIN\"|\"LOSE\"|\"PENDING\", \"score\": \"счет\", \"lesson\": \"если LOSE — 1 правило для rules.txt, иначе пусто\"}}")
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res["status"] in ("WIN", "LOSE"):
                bet["status"], bet["score"] = res["status"], res.get("score", "")
                prof = round(bet["stake_rub"] * (bet["odds"] - 1.0), 0) if res["status"] == "WIN" else -bet["stake_rub"]
                history["bank"] = round(history["bank"] + prof, 0)
                if res["status"] == "LOSE" and res.get("lesson"):
                    rules += f"\n- Авто-патч ({NOW_TLT.strftime('%d.%m')}): {res['lesson']}"
                done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                wr = round(len([b for b in done if b["status"] == "WIN"]) / len(done) * 100, 1) if done else 0
                extra = f"\n🧠 <i>Самообучение: {res['lesson']}</i>" if res["status"] == "LOSE" and res.get("lesson") else ""
                send_tg(f"{'✅ ЗАХОД' if res['status']=='WIN' else '❌ ПРОИГРЫШ'} | <b>{bet['match']}</b>\nСчёт: {bet['score']} | Ставка: {bet['pick']} ({bet['odds']})\nИтог: {prof:+.0f} ₽ | Банк: <b>{history['bank']:.0f} ₽</b> (Проход: {wr}%){extra}")
                upd = True
        except Exception:
            pass
    return history, rules, upd

def check_live(history):
    sent = False
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        mins = (NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0
        if 10 <= mins <= 135:
            info = web_search(f"{bet['match']} live счет статистика сейчас")
            adv = ask_ai(f"Матч {bet['match']} в лайве (~{int(mins)} мин). Ставка: {bet['pick']} ({bet['odds']}). Данные:\n{info}\nЕсли по плану — верни OK. Если против — совет в 3 строки: ДЕРЖАТЬ, ПРОДАТЬ или ПЕРЕКРЫТЬСЯ.").strip()
            if adv and "OK" not in adv[:10].upper() and send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{adv}"):
                sent = True
    return sent

def find_matches(history, rules):
    taken = {b["match"] for b in history["bets"]}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    fb, pm, sf = get_fonbet(), get_polymarket(), get_sofascore()
    s1 = web_search(f"прогнозы коэффициенты матчи сегодня {d_str} футбол хоккей Dota 2 CS2 hltv")
    prompt = f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\nФОНБЕТ (через 15-120 мин):\n{fb}\n\nPOLYMARKET (вероятности рынка):\n{pm}\n\nSOFASCORE:\n{sf}\n\nПОИСК:\n{s1}\n\nНайди 1-2 лучших матча через 15-120 мин от {t_str}, которых НЕТ в {list(taken)}. Ищи перевес +EV >= 7% (сравнивая Фонбет с Polymarket/рынком и обратки 1.80-3.50). Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка\", \"odds\": 2.15, \"prob\": 0.54, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}] или []."
    raw = ask_ai(prompt)
    try:
        cands = json.loads(raw[raw.find("["):raw.rfind("]")+1])
    except Exception:
        return history, False
    upd = False
    for c in cands[:2]:
        if c["match"] in taken:
            continue
        odds, prob = float(c["odds"]), float(c["prob"])
        ev, pct, rub = calc_stats(prob, odds, history["bank"])
        if ev < 7.0 or rub <= 0:
            continue
        parts = str(c.get("start_time", "")).split(":")
        st = NOW_TLT.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0) if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() else NOW_TLT + datetime.timedelta(minutes=45)
        if st < NOW_TLT - datetime.timedelta(minutes=30):
            st += datetime.timedelta(days=1)
        history["bets"].append({"match": c["match"], "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": rub, "status": "PENDING", "score": ""})
        send_tg(f"🎯 <b>СИГНАЛ ({c.get('type', 'Валуй')}) | {c.get('league', '')}</b>\n⚽ <b>{c['match']}</b>\n⏰ Старт (ТЛТ): <b>{st.strftime('%H:%M')}</b>\n📌 Ставка: <b>{c['pick']}</b> | Кэф: <b>{odds:.2f}</b>\n📊 Вероятность: {prob*100:.1f}% | +EV (100k MC): <b>+{ev}%</b>\n💰 Сумма (1/4 Келли): <b>{rub:.0f} ₽</b> ({pct}% банка)\n\n💡 <i>Суть:</i> {c.get('reason', '')}\n⚡ <i>Лайв-план:</i> {c.get('live_plan', '')}\n⚠️ <i>Риск:</i> {c.get('risk', '')}")
        upd = True
    return history, upd

def main():
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f:
        rules = f.read()
    history, rules, u1 = check_results(history, rules)
    live_sent = check_live(history)
    history, u2 = find_matches(history, rules)
    if u1 or u2:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and not (u1 or u2 or live_sent):
        send_tg(f"🤖 <b>Система 5.0 на связи ({NOW_TLT.strftime('%H:%M')} ТЛТ)</b>\nСвязь с каналом и ИИ работает штатно. Подходящих матчей с +EV ≥ 7% в ближайшие 2 часа не найдено.")
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
