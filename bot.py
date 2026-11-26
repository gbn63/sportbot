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
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0.0.0", "Accept": "application/json"}

def send_tg(text):
    try:
        r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code != 200:
            print("TG HTTP:", r.status_code, r.text[:100])
            return False
        return True
    except Exception as e:
        print("TG err:", e)
        return False

def web_search(q, n=8):
    try:
        with DDGS() as d:
            return "\n".join([f"- {r['title']}: {r['body']}" for r in d.text(q, timelimit="d", max_results=n)])
    except Exception as e:
        return f"Search err: {e}"

def get_1x_feed():
    now_ts, out = NOW_TLT.timestamp(), []
    mirrors = [".".join(["1xbet", "com"]), ".".join(["melbet", "com"]), ".".join(["betwinner", "com"])]
    for dom in mirrors:
        try:
            url = f"https://{dom}/LineFeed/Get1x2_VZip?count=120&lng=ru&mode=4&getEmpty=true"
            r = requests.get(url, headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
            for ev in r.json().get("Value", []):
                st_ts = ev.get("S", 0)
                if not (15 <= (st_ts - now_ts) / 60.0 <= 960):
                    continue
                t1, t2 = ev.get("O1", ""), ev.get("O2", "")
                if not t1 or not t2:
                    continue
                odds = [f"{e.get('T')}={e.get('C')}" for e in ev.get("E", []) if e.get("T") in (1, 2, 3, 4, 5, 6)]
                if odds:
                    st_str = datetime.datetime.fromtimestamp(st_ts, tz=NOW_TLT.tzinfo).strftime("%d.%m %H:%M")
                    out.append(f"[{st_str}] {ev.get('SN', '')} ({ev.get('L', '')}): {t1} — {t2} | {', '.join(odds)}")
            if out:
                print(f"Зеркало БК ({dom}): {len(out)} матчей")
                return "\n".join(out[:50])
        except Exception:
            pass
    print("Прямые зеркала 1x/Melbet недоступны с IP США.")
    return ""
def get_all_sources():
    now_ts, out = NOW_TLT.timestamp(), []
    bk_direct = get_1x_feed()
    if bk_direct:
        out.append("=== ПРЯМАЯ ЛИНИЯ БК (1=П1, 2=Х, 3=П2, 4=1Х, 5=12, 6=Х2) ===\n" + bk_direct)

    ps_key = os.environ.get("PANDASCORE_KEY", "").strip()
    if ps_key:
        try:
            ps_host = ".".join(["api", "pandascore", "co"])
            r = requests.get(f"https://{ps_host}/matches/upcoming?sort=begin_at&page[size]=35", headers={"Authorization": f"Bearer {ps_key}", "Accept": "application/json"}, timeout=12)
            if r.status_code == 200:
                ps_list = []
                for m in r.json():
                    b_iso = (m.get("begin_at") or "").replace("Z", "+00:00")
                    if not b_iso:
                        continue
                    st_dt = datetime.datetime.fromisoformat(b_iso).astimezone(NOW_TLT.tzinfo)
                    if 15 <= (st_dt.timestamp() - now_ts) / 60.0 <= 960:
                        ps_list.append(f"[{st_dt.strftime('%d.%m %H:%M')}] {m.get('videogame', {}).get('name', '')} ({m.get('league', {}).get('name', '')}): {m.get('name', '')}")
                print(f"PandaScore: {len(ps_list)} матчей")
                if ps_list:
                    out.append("=== PANDASCORE (КИБЕРСПОРТ) ===\n" + "\n".join(ps_list[:30]))
        except Exception as e:
            print("PandaScore err:", e)

    pm_list, pm_host = [], ".".join(["gamma-api", "polymarket", "com"])
    for tag in ["sports", "esports"]:
        try:
            r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug={tag}&limit=60", headers=HEADERS, timeout=12)
            if r.status_code == 200:
                for ev in r.json():
                    for m in ev.get("markets", [])[:3]:
                        q = m.get("question", ev.get("title", ""))
                        oc = json.loads(m.get("outcomes", "[]")) if isinstance(m.get("outcomes"), str) else m.get("outcomes", [])
                        pr = json.loads(m.get("outcomePrices", "[]")) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices", [])
                        if q and len(oc) == len(pr) and pr:
                            line = f"- [{tag}] {q} -> " + ", ".join([f"{o}: {round(float(p)*100, 1)}%" for o, p in zip(oc, pr)])
                            if line not in pm_list:
                                pm_list.append(line)
        except Exception:
            pass
    print(f"Polymarket: {len(pm_list)} рынков")
    if pm_list:
        out.append("=== POLYMARKET (ВЕРОЯТНОСТИ РЫНКА) ===\n" + "\n".join(pm_list[:40]))

    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key and ((NOW_TLT.hour * 60 + NOW_TLT.minute) % 90 < 5 or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"):
        try:
            oa_host = ".".join(["api", "the-odds-api", "com"])
            url = f"https://{oa_host}/v4/sports/upcoming/odds/?apiKey={odds_key}&regions=eu&markets=h2h,totals,spreads&oddsFormat=decimal"
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
                        mkt_strs = []
                        for m in next(iter(bms)).get("markets", []):
                            o_str = ", ".join([f"{o['name']}({o.get('point', '')})={o['price']}".replace("()", "") for o in m.get("outcomes", [])])
                            mkt_strs.append(f"{m.get('key', '')}: [{o_str}]")
                        bk_list.append(f"[{st_dt.strftime('%d.%m %H:%M')}] {ev.get('sport_title', '')}: {ev.get('home_team', '')} — {ev.get('away_team', '')} | {' ; '.join(mkt_strs)}")
                print(f"Odds API (1Х2+Тоталы+Форы): {len(bk_list)} матчей (остаток: {r.headers.get('x-requests-remaining', '?')})")
                if bk_list:
                    out.append("=== ODDS API (1Х2, ТОТАЛЫ, ФОРЫ) ===\n" + "\n".join(bk_list[:40]))
        except Exception as e:
            print("Odds API err:", e)

    try:
        sdb_host = ".".join(["www", "thesportsdb", "com"])
        r = requests.get(f"https://{sdb_host}/api/v1/json/3/eventsday.php?d={NOW_TLT.strftime('%Y-%m-%d')}", headers=HEADERS, timeout=10)
        if r.status_code == 200 and r.json().get("events"):
            sdb = [f"[{e.get('strTime', '')[:5]}] {e.get('strSport', '')} ({e.get('strLeague', '')}): {e.get('strEvent', '')}" for e in r.json()["events"][:25]]
            out.append("=== THESPORTSDB (МИРОВОЙ СПОРТ) ===\n" + "\n".join(sdb))
    except Exception:
        pass

    try:
        od_host = ".".join(["api", "opendota", "com"])
        r = requests.get(f"https://{od_host}/api/proMatches", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            dota = [f"{m.get('radiant_name')} vs {m.get('dire_name')} ({m.get('league_name', '')})" for m in r.json()[:8] if m.get("radiant_name")]
            if dota:
                out.append("=== DOTA 2 (OPENDOTA) ===\n" + "; ".join(dota))
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
                    r = requests.post(f"{g_url}/chat/completions", headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}, timeout=25)
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

def get_espn_live():
    espn, out = ".".join(["site", "api", "espn", "com"]), []
    for p in ["soccer/all/scoreboard", "hockey/nhl/scoreboard", "basketball/nba/scoreboard"]:
        try:
            r = requests.get(f"https://{espn}/apis/site/v2/sports/{p}", headers=HEADERS, timeout=8)
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    st = ev.get("status", {}).get("type", {}).get("shortDetail", "")
                    comp = next(iter(ev.get("competitions", [])), {})
                    sc = " : ".join([f"{c.get('team', {}).get('displayName', '')} ({c.get('score', '0')})" for c in comp.get("competitors", [])])
                    if sc:
                        out.append(f"{sc} [{st}]")
        except Exception:
            pass
    return "\n".join(out)

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
    active = [b for b in history["bets"] if b["status"] == "PENDING" and 5 <= (NOW_TLT - datetime.datetime.fromisoformat(b["start_iso"])).total_seconds() / 60.0 <= 135]
    if not active:
        return False
    espn_sc = get_espn_live()
    for bet in active:
        mins = int((NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0)
        info = web_search(f"{bet['match']} live счет минута статистика score")
        adv = ask_ai(
            f"Матч {bet['match']} в лайве (~{mins} мин). Ставка: {bet['pick']} ({bet['odds']}).\n"
            f"Табло ESPN:\n{espn_sc}\nПоиск:\n{info}\n\n"
            f"Если реального счёта нет или игра идёт по плану — верни СТРОГО слово OK.\n"
            f"Если есть счёт и игра идёт против ставки — верни СТРОГО в 3 строки:\n"
            f"Счёт: [счёт и минута]\nДействие: [ДЕРЖАТЬ / ПРОДАТЬ / ПЕРЕКРЫТЬСЯ]\nПричина: [почему нужно так сделать]"
        ).strip()
        if adv and "OK" not in adv[:15].upper() and send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{adv}"):
            sent = True
    return sent

def parse_start_dt(t_str):
    parts = str(t_str).strip().split(":")
    if len(parts) == 2 and parts[-1].isdigit():
        h_s = next(iter(parts))
        if h_s.isdigit():
            st = NOW_TLT.replace(hour=int(h_s) % 24, minute=int(parts[-1]) % 60, second=0, microsecond=0)
            if st < NOW_TLT - datetime.timedelta(minutes=30):
                st += datetime.timedelta(days=1)
            return st
    return NOW_TLT + datetime.timedelta(minutes=60)

def find_matches(history, rules):
    taken = {b["match"] for b in history["bets"]}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    tom_str = (NOW_TLT + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    mkt = get_all_sources()
    s1 = web_search(f"прогнозы обе забьют индивидуальный тотал ТБ ТМ {d_str} {tom_str} футбол хоккей КХЛ НХЛ")
    s2 = web_search(f"прогнозы коэффициенты баскетбол волейбол теннис гандбол снукер {d_str} {tom_str}")
    s3 = web_search(f"CS2 Dota 2 LoL Valorant прогнозы коэффициенты тотал карт {d_str} {tom_str}")
    prompt = (
        f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\n"
        f"ПОИСК (ОЗ / ИТБ / ТОТАЛЫ):\n{s1}\n\nПОИСК (БАСКЕТ / ТЕННИС / СМОЛМАРКЕТЫ):\n{s2}\n\nПОИСК (КИБЕРСПОРТ):\n{s3}\n\n"
        f"Проанализируй ВЕСЬ спорт и киберспорт мира (футбол, хоккей, баскетбол, теннис, волейбол, гандбол, снукер, футзал, CS2, Dota 2, LoL, Valorant и др.) "
        f"с началом в ближайшие 16 часов от {t_str}, которых НЕТ в {list(taken)}.\n"
        f"Используй ВСЮ роспись: П1/Х/П2, Форы, Общие тоталы (ТБ/ТМ), Индивидуальные тоталы (ИТБ/ИТМ), Обе забьют (ОЗ Да/Нет), тоталы карт/сетов.\n"
        f"Выдай ВСЕ топовые матчи с перевесом +EV >= 5.0% (обратки 1.80-3.50 и валуи по статистике/xG/форме). "
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Рынок и ставка (напр. ОЗ - Нет, ИТБ1 (1.5), ТМ (2.5), П2)\", \"odds\": 2.15, \"prob\": 0.53, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}] или []."
    )
    raw = ask_ai(prompt)
    try:
        cands = json.loads(raw[raw.find("["):raw.rfind("]")+1])
    except Exception:
        return history, False
    upd = False
    for c in cands:
        try:
            m_name = str(c.get("match", "")).strip()
            if not m_name or m_name in taken:
                continue
            odds, prob = float(c["odds"]), float(c["prob"])
            ev, pct, rub = calc_stats(prob, odds, history["bank"])
            if ev < 5.0 or rub <= 0:
                continue
            min_odds = round(1.05 / prob, 2) if prob > 0 else odds
            st = parse_start_dt(c.get("start_time", ""))
            history["bets"].append({"match": m_name, "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": rub, "status": "PENDING", "score": ""})
            send_tg(f"🎯 <b>СИГНАЛ ({c.get('type', 'Валуй')}) | {c.get('league', '')}</b>\n🏆 <b>{m_name}</b>\n⏰ Старт (ТЛТ): <b>{st.strftime('%H:%M')}</b>\n📌 Ставка: <b>{c['pick']}</b> | Ориентир кэфа: <b>{odds:.2f}</b> (мин. в Фонбете: <b>{min_odds:.2f}</b>)\n📊 Вероятность: {prob*100:.1f}% | +EV (100k MC): <b>+{ev}%</b>\n💰 Сумма (1/4 Келли): <b>{rub:.0f} ₽</b> ({pct}% банка)\n\n💡 <i>Суть:</i> {c.get('reason', '')}\n⚡ <i>Лайв-план:</i> {c.get('live_plan', '')}\n⚠️ <i>Риск:</i> {c.get('risk', '')}")
            taken.add(m_name)
            upd = True
        except Exception:
            continue
    return history, upd

def main():
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f:
        rules = f.read()
    history, rules, u1 = check_results(history, rules)
    live_sent = check_live(history)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    u2 = False
    if is_manual or NOW_TLT.minute < 5:
        history, u2 = find_matches(history, rules)
    if u1 or u2:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2 or live_sent):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%H:%M')} ТЛТ)</b>\nВсе мировые источники опрошены. Новых матчей с +EV ≥ 5% не найдено.")
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Лайв: {live_sent}, Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
