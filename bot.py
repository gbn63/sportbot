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

def web_search(q, n=8):
    try:
        with DDGS() as d:
            return "\n".join([f"- {r['title']}: {r['body']}" for r in d.text(q, timelimit="d", max_results=n)])
    except Exception as e:
        return f"Search err: {e}"


def get_market_data():
    now_ts, out = NOW_TLT.timestamp(), []
    try:
        pm_host = ".".join(["gamma-api", "polymarket", "com"])
        r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug=sports&limit=80", headers=HEADERS, timeout=12)
        if r.status_code != 200 or not r.json():
            r = requests.get(f"https://{pm_host}/events?active=true&closed=false&limit=100&order=volume24hr&ascending=false", headers=HEADERS, timeout=12)
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
            out.append("=== POLYMARKET (ВЕРОЯТНОСТИ РЫНКА) ===\n" + "\n".join(pm_list[:35]))
    except Exception as e:
        print("Polymarket err:", e)

    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key:
        try:
            oa_host = ".".join(["api", "the-odds-api", "com"])
            url = f"https://{oa_host}/v4/sports/upcoming/odds/?apiKey={odds_key}&regions=eu&markets=h2h&oddsFormat=decimal"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                bk_list = []
                for ev in r.json():
                    dt_iso = ev.get("commence_time", "").replace("Z", "+00:00")
                    if not dt_iso:
                        continue
                    st_dt = datetime.datetime.fromisoformat(dt_iso).astimezone(NOW_TLT.tzinfo)
                    if 15 <= (st_dt.timestamp() - now_ts) / 60.0 <= 960:
                        bms = ev.get("bookmakers", [])
                        if not bms:
                            continue
                        mkts = next(iter(bms)).get("markets", [])
                        if not mkts:
                            continue
                        outcomes = next(iter(mkts)).get("outcomes", [])
                        o_str = ", ".join([f"{o['name']}={o['price']}" for o in outcomes])
                        bk_list.append(f"[{st_dt.strftime('%d.%m %H:%M')}] {ev.get('sport_title', '')}: {ev.get('home_team', '')} — {ev.get('away_team', '')} | Кэфы: {o_str}")
                print(f"Линия БК (Odds API): {len(bk_list)} матчей с кэфами (остаток запросов: {r.headers.get('x-requests-remaining', '?')})")
                if bk_list:
                    out.append("=== ЖИВАЯ ЛИНИЯ БУКМЕКЕРОВ (СТАРТ ЧЕРЕЗ 15-960 МИН) ===\n" + "\n".join(bk_list[:45]))
            else:
                print("Odds API HTTP:", r.status_code)
        except Exception as e:
            print("Odds API err:", e)

    try:
        od_host = ".".join(["api", "opendota", "com"])
        r = requests.get(f"https://{od_host}/api/proMatches", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            dota = [f"{m.get('radiant_name')} vs {m.get('dire_name')} ({m.get('league_name', '')})" for m in r.json()[:8] if m.get("radiant_name")]
            if dota:
                out.append("=== DOTA 2 (ПРО-СЕРИИ) ===\n" + "; ".join(dota))
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
                avail = [x["id"] for x in mr.json().get("data", []) if not any(w in x["id"] for w in ["whisper", "guard", "tts", "orpheus", "allam", "qwen", "20b"])]
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
            info = web_search(f"{bet['match']} live счет статистика сейчас score")
            adv = ask_ai(f"Матч {bet['match']} в лайве (~{int(mins)} мин). Ставка: {bet['pick']} ({bet['odds']}). Данные:\n{info}\nЕсли данных о текущем счёте нет или всё идёт по плану — верни СТРОГО слово OK. Только если есть реальный счёт и он против плана — дай совет в 3 строки: ДЕРЖАТЬ, ПРОДАТЬ или ПЕРЕКРЫТЬСЯ.").strip()
            if adv and "OK" not in adv[:15].upper() and send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{adv}"):
                sent = True
    return sent


def find_matches(history, rules):
    taken = {b["match"] for b in history["bets"]}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    tom_str = (NOW_TLT + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    mkt = get_market_data()
    s1 = web_search(f"прогнозы коэффициенты футбол сегодня завтра {d_str} {tom_str} Лига Европы АПЛ Серия А")
    s2 = web_search(f"прогнозы коэффициенты хоккей КХЛ НХЛ {d_str} {tom_str}")
    s3 = web_search(f"Dota 2 CS2 матчи расписание коэффициенты {d_str} {tom_str} hltv")
    prompt = (
        f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\n"
        f"ПОИСК ФУТБОЛ:\n{s1}\n\nПОИСК ХОККЕЙ:\n{s2}\n\nПОИСК КИБЕРСПОРТ:\n{s3}\n\n"
        f"Найди ВСЕ хорошие матчи с началом в ближайшие 12 часов от {t_str} (футбол, КХЛ, НХЛ, баскетбол, теннис, Dota 2, CS2), "
        f"которых НЕТ в {list(taken)}. Отбирай все матчи с перевесом +EV >= 5.0% (особенно обратки на кэфах 1.80-3.50 и валуи). "
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка\", \"odds\": 2.15, \"prob\": 0.53, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}] или []."
    )
    raw = ask_ai(prompt)
    try:
        cands = json.loads(raw[raw.find("["):raw.rfind("]")+1])
    except Exception:
        return history, False
    upd = False
    for c in cands:
        if c["match"] in taken:
            continue
        odds, prob = float(c["odds"]), float(c["prob"])
        ev, pct, rub = calc_stats(prob, odds, history["bank"])
        if ev < 5.0 or rub <= 0:
            continue
        min_odds = round(1.05 / prob, 2) if prob > 0 else odds
        parts = str(c.get("start_time", "")).split(":")
        st = NOW_TLT.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0) if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit() else NOW_TLT + datetime.timedelta(minutes=60)
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
        send_tg(f"🤖 <b>Система 5.0 на связи ({NOW_TLT.strftime('%H:%M')} ТЛТ)</b>\nСвязь с каналом и ИИ работает штатно. Подходящих матчей с +EV ≥ 5% в ближайшие 12 часов не найдено.")
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
