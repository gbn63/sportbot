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
def get_market_data():
    now_ts, out = NOW_TLT.timestamp(), []
    try:
        pm_host = ".".join(["gamma-api", "polymarket", "com"])
        r = requests.get(f"https://{pm_host}/events?active=true&closed=false&limit=50&order=volume24hr&ascending=false", headers=HEADERS, timeout=12)
        if r.status_code == 200:
            pm_list = []
            for ev in r.json():
                for m in ev.get("markets", [])[:2]:
                    q = m.get("question", ev.get("title", ""))
                    oc = json.loads(m.get("outcomes", "[]")) if isinstance(m.get("outcomes"), str) else m.get("outcomes", [])
                    pr = json.loads(m.get("outcomePrices", "[]")) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices", [])
                    if q and len(oc) == len(pr) and pr:
                        pm_list.append(f"- {q} -> " + ", ".join([f"{o}: {round(float(p)*100, 1)}%" for o, p in zip(oc, pr)]))
            print(f"Polymarket: {len(pm_list)} рынков")
            out.append("=== POLYMARKET (РЕАЛЬНЫЕ ВЕРОЯТНОСТИ РЫНКА) ===\n" + "\n".join(pm_list[:25]))
    except Exception as e:
        print("Polymarket err:", e)

    espn = ".".join(["site", "api", "espn", "com"])
    leagues = [
        ("Еврофутбол (Топ/Еврокубки)", "soccer/all/scoreboard"),
        ("АПЛ", "soccer/eng.1/scoreboard"),
        ("Ла Лига", "soccer/esp.1/scoreboard"),
        ("Серия А", "soccer/ita.1/scoreboard"),
        ("Бундеслига", "soccer/ger.1/scoreboard"),
        ("Лига Чемпионов", "soccer/uefa.champions/scoreboard"),
        ("Хоккей НХЛ", "hockey/nhl/scoreboard"),
        ("Баскетбол НБА", "basketball/nba/scoreboard")
    ]
    espn_list = []
    for title, path in leagues:
        try:
            r = requests.get(f"https://{espn}/apis/site/v2/sports/{path}", headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            for ev in r.json().get("events", []):
                dt_iso = ev.get("date", "").replace("Z", "+00:00")
                if not dt_iso:
                    continue
                st_dt = datetime.datetime.fromisoformat(dt_iso).astimezone(NOW_TLT.tzinfo)
                if 15 <= (st_dt.timestamp() - now_ts) / 60.0 <= 240:
                    comp = next(iter(ev.get("competitions", [])), {})
                    odds_txt = f" | Линия: {comp['odds'].get('details', '')}" if comp.get("odds") else ""
                    line = f"[{st_dt.strftime('%H:%M')}] {title}: {ev.get('name', '')}{odds_txt}"
                    if line not in espn_list:
                        espn_list.append(line)
        except Exception:
            pass
    print(f"ESPN (Европа + США): {len(espn_list)} матчей")
    if espn_list:
        out.append("=== ESPN (СТАРТ ЧЕРЕЗ 15-240 МИН) ===\n" + "\n".join(espn_list[:35]))

    try:
        od_host = ".".join(["api", "opendota", "com"])
        r = requests.get(f"https://{od_host}/api/proMatches", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            dota = [f"{m.get('radiant_name')} vs {m.get('dire_name')} ({m.get('league_name', '')})" for m in r.json()[:8] if m.get("radiant_name")]
            if dota:
                out.append("=== DOTA 2 (АКТУАЛЬНЫЕ ПРО-СЕРИИ) ===\n" + "; ".join(dota))
    except Exception:
        pass

    return "\n\n".join(out)

def ask_ai(prompt):
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        try:
            g_url = "https://" + ".".join(["api", "groq", "com"]) + "/openai/v1"
            hdr = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
            mr = requests.get(f"{g_url}/models", headers=hdr, timeout=10)
            if mr.status_code == 200:
                avail = [x["id"] for x in mr.json().get("data", []) if not any(w in x["id"] for w in ["whisper", "guard", "tts", "orpheus"])]
                for gm in avail[:3]:
                    r = requests.post(f"{g_url}/chat/completions", headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}, timeout=20)
                    if r.status_code == 200:
                        choice = next(iter(r.json()["choices"]))
                        txt = choice["message"]["content"]
                        print(f"ИИ (Groq {gm}) ответил: {len(txt)} симв.")
                        return txt
        except Exception as e:
            print("Groq err:", e)

    for m in ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3.5-flash-lite"]:
        try:
            r = requests.post(f"{GEM_HOST}/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}}, timeout=15)
            if r.status_code == 200:
                cand = next(iter(r.json()["candidates"]))
                part = next(iter(cand["content"]["parts"]))
                txt = part["text"]
                print(f"ИИ ({m}) ответил: {len(txt)} симв.")
                return txt
        except Exception:
            pass
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
    mkt = get_market_data()
    s1 = web_search(f"расписание прогнозы коэффициенты сегодня {d_str} КХЛ футбол Лига Европы Dota 2 CS2 hltv")
    prompt = f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\nПОИСК (КХЛ/Европа/Киберспорт):\n{s1}\n\nНайди 1-2 лучших матча через 15-240 мин от {t_str}, которых НЕТ в {list(taken)}. Ищи перевес +EV >= 7% с поправкой на маржу Фонбета (особенно обратки на кэфах 1.80-3.50 и валуи по Polymarket/ESPN). Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка\", \"odds\": 2.15, \"prob\": 0.54, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}] или []."
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
        min_odds = round(1.05 / prob, 2) if prob > 0 else odds
        parts = str(c.get("start_time", "")).split(":")
        st = NOW_TLT.replace(hour=int(parts), minute=int(parts), second=0, microsecond=0) if len(parts) == 2 and parts.isdigit() and parts.isdigit() else NOW_TLT + datetime.timedelta(minutes=45)
        if st < NOW_TLT - datetime.timedelta(minutes=30):
            st += datetime.timedelta(days=1)
        history["bets"].append({"match": c["match"], "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": rub, "status": "PENDING", "score": ""})
        send_tg(f"🎯 <b>СИГНАЛ ({c.get('type', 'Валуй')}) | {c.get('league', '')}</b>\n⚽ <b>{c['match']}</b>\n⏰ Старт (ТЛТ): <b>{st.strftime('%H:%M')}</b>\n📌 Ставка: <b>{c['pick']}</b> | Ориентир кэфа: <b>{odds:.2f}</b> (мин. в Фонбете: <b>{min_odds:.2f}</b>)\n📊 Вероятность: {prob*100:.1f}% | +EV (100k MC): <b>+{ev}%</b>\n💰 Сумма (1/4 Келли): <b>{rub:.0f} ₽</b> ({pct}% банка)\n\n💡 <i>Суть:</i> {c.get('reason', '')}\n⚡ <i>Лайв-план:</i> {c.get('live_plan', '')}\n⚠️ <i>Риск:</i> {c.get('risk', '')}")
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
