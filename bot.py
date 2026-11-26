import os, json, datetime, requests, warnings
import numpy as np
from duckduckgo_search import DDGS

warnings.filterwarnings("ignore")

BOT_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
NOW_TLT = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=4)))

TG_HOST = "https://" + ".".join(["api", "telegram", "org"])
GEM_HOST = "https://" + ".".join(["generativelanguage", "googleapis", "com"])
ACTIVE_MODELS = ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]

def send_tg(text):
    try:
        r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200:
            print("TG HTTP error:", r.status_code, r.text[:120])
    except Exception as e:
        print("TG error:", e)

def web_search(query, n=6):
    try:
        with DDGS() as ddgs:
            return "\n".join([f"- {r['title']}: {r['body']}" for r in ddgs.text(query, max_results=n)])
    except Exception as e:
        return f"Search error: {e}"

def ask_ai(prompt):
    for m in ACTIVE_MODELS:
        try:
            url = f"{GEM_HOST}/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}
            r = requests.post(url, json=payload, timeout=60)
            if r.status_code == 200:
                cand = next(iter(r.json()["candidates"]))
                part = next(iter(cand["content"]["parts"]))
                txt = part["text"]
                print(f"ИИ ({m}) ответил: {len(txt)} симв.")
                return txt
            print(f"Model {m} HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            print(f"Model {m} error:", e)
    return ""

def calc_stats(prob, odds, bank):
    rng = np.random.default_rng()
    ev = round(float(np.mean(np.where(rng.random(100_000) < prob, odds - 1.0, -1.0))) * 100, 2)
    b = odds - 1.0
    f = ((prob * b - (1.0 - prob)) / b) if b > 0 else 0.0
    qk = max(0.0, min(0.05, f * 0.25))
    return ev, round(qk * 100, 2), round(bank * qk, 0)

def check_results(history, rules):
    upd = False
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        start_dt = datetime.datetime.fromisoformat(bet["start_iso"])
        if (NOW_TLT - start_dt).total_seconds() / 3600.0 < 2.8:
            continue
        info = web_search(f"{bet['match']} результат счет итог матча {start_dt.strftime('%d.%m.%Y')}")
        raw = ask_ai(f"Проверь итог. Матч: {bet['match']}. Ставка: {bet['pick']} ({bet['odds']}). Данные:\n{info}\nВерни СТРОГО JSON: {{\"status\": \"WIN\" или \"LOSE\" или \"PENDING\", \"score\": \"счет\", \"lesson\": \"если LOSE — 1 короткое правило для rules.txt, иначе пусто\"}}")
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res["status"] in ("WIN", "LOSE"):
                bet["status"], bet["score"] = res["status"], res.get("score", "")
                profit = round(bet["stake_rub"] * (bet["odds"] - 1.0), 0) if res["status"] == "WIN" else -bet["stake_rub"]
                history["bank"] = round(history["bank"] + profit, 0)
                if res["status"] == "LOSE" and res.get("lesson"):
                    rules += f"\n- Авто-патч ({NOW_TLT.strftime('%d.%m')}): {res['lesson']}"
                done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                wr = round(len([b for b in done if b["status"] == "WIN"]) / len(done) * 100, 1) if done else 0
                icon = "✅ ЗАХОД" if res["status"] == "WIN" else "❌ ПРОИГРЫШ"
                extra = f"\n🧠 <i>Самообучение: {res['lesson']}</i>" if res["status"] == "LOSE" and res.get("lesson") else ""
                send_tg(f"{icon} | <b>{bet['match']}</b>\nСчёт: {bet['score']} | Ставка: {bet['pick']} ({bet['odds']})\nИтог: {profit:+.0f} ₽ | Банк: <b>{history['bank']:.0f} ₽</b> (Проход: {wr}%){extra}")
                upd = True
        except Exception:
            pass
    return history, rules, upd

def check_live(history):
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        mins = (NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0
        if 10 <= mins <= 135:
            info = web_search(f"{bet['match']} live счет статистика сейчас")
            adv = ask_ai(f"Матч {bet['match']} в лайве (~{int(mins)} мин). Ставка: {bet['pick']} за {bet['odds']}. Данные:\n{info}\nЕсли всё по плану — верни OK. Если против плана — совет в 3 строки: ДЕРЖАТЬ, ПРОДАТЬ или ПЕРЕКРЫТЬСЯ.").strip()
            if adv and "OK" not in adv[:10].upper():
                send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{adv}")

def find_matches(history, rules):
    taken = {b["match"] for b in history["bets"]}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    s1 = web_search(f"расписание матчей сегодня {d_str} футбол хоккей КХЛ НХЛ баскетбол прогнозы коэффициенты")
    s2 = web_search(f"Dota 2 CS2 матчи сегодня {d_str} прогнозы коэффициенты sentrybot hltv")
    s3 = web_search(f"progsport forebet прогнозы на сегодня {d_str} коэффициенты")
    prompt = f"Время Тольятти (UTC+4): {d_str} {t_str}. Правила:\n{rules}\nДанные:\n{s1}\n{s2}\n{s3}\nНайди 1-2 лучших матча через 15-120 мин от {t_str}, которых НЕТ в {list(taken)}. Перевес +EV >= 7%. Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка\", \"odds\": 2.15, \"prob\": 0.54, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}] или []."
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
        try:
            hh, mm = map(int, c["start_time"].split(":"))
            st = NOW_TLT.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if st < NOW_TLT - datetime.timedelta(minutes=30):
                st += datetime.timedelta(days=1)
        except Exception:
            st = NOW_TLT + datetime.timedelta(minutes=45)
        history["bets"].append({"match": c["match"], "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": rub, "status": "PENDING", "score": ""})
        send_tg(f"🎯 <b>СИГНАЛ ({c.get('type', 'Валуй')}) | {c.get('league', '')}</b>\n⚽ <b>{c['match']}</b>\n⏰ Старт (Тольятти): <b>{st.strftime('%H:%M')}</b>\n📌 Ставка: <b>{c['pick']}</b> | Кэф: <b>{odds:.2f}</b>\n📊 Вероятность: {prob*100:.1f}% | +EV (100k MC): <b>+{ev}%</b>\n💰 Сумма (1/4 Келли): <b>{rub:.0f} ₽</b> ({pct}% банка)\n\n💡 <i>Суть:</i> {c.get('reason', '')}\n⚡ <i>Лайв-план:</i> {c.get('live_plan', '')}\n⚠️ <i>Риск:</i> {c.get('risk', '')}")
        upd = True
    return history, upd

def main():
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f:
        rules = f.read()
    history, rules, u1 = check_results(history, rules)
    check_live(history)
    history, u2 = find_matches(history, rules)
    if u1 or u2:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
