import os, re, json, time, datetime, requests, warnings
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

def web_search(q, n=5):
    try:
        with DDGS() as d:
            return "\n".join([f"- {r['title']}: {r['body']}" for r in d.text(q, timelimit="d", max_results=n)])
    except Exception as e:
        return f"Search err: {e}"

def am_to_dec(p):
    try:
        p = float(p)
        return round(1.0 + p / 100.0, 2) if p > 0 else round(1.0 + 100.0 / abs(p), 2)
    except Exception:
        return 0.0
def get_pinnacle_feed():
    now_ts, total_found, balanced = NOW_TLT.timestamp(), 0, []
    pin = ".".join(["guest", "api", "arcadia", "pinnacle", "com"])
    sports = [(29, "Футбол"), (19, "Хоккей"), (4, "Баскетбол"), (33, "Теннис"), (12, "Киберспорт"), (34, "Волейбол"), (32, "Наст. теннис")]
    for sid, sname in sports:
        try:
            rm = requests.get(f"https://{pin}/0.1/sports/{sid}/matchups?brandId=0", headers=HEADERS, timeout=8)
            rp = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
            if rm.status_code != 200 or rp.status_code != 200:
                continue
            m_map = {}
            for m in rm.json():
                st_iso = (m.get("startTime") or "").replace("Z", "+00:00")
                parts = m.get("participants", [])
                if not st_iso or len(parts) < 2:
                    continue
                st_dt = datetime.datetime.fromisoformat(st_iso).astimezone(NOW_TLT.tzinfo)
                if 5 <= (st_dt.timestamp() - now_ts) / 60.0 <= 960:
                    home = next((x.get("name") for x in parts if x.get("alignment") == "home"), next(iter(parts)).get("name", ""))
                    away = next((x.get("name") for x in parts if x.get("alignment") == "away"), parts[-1].get("name", ""))
                    lg = m.get("league", {}).get("name", "")
                    m_map[m["id"]] = f"[{st_dt.strftime('%d.%m %H:%M')}] {sname} ({lg}): {home} — {away}"
            odds_map, good_map = {}, {}
            for mk in rp.json():
                mid = mk.get("matchupId")
                if mid not in m_map or mk.get("period") != 0:
                    continue
                mtype = mk.get("type", "")
                plist = []
                for pr in mk.get("prices", []):
                    dec = am_to_dec(pr.get("price", 0))
                    if dec > 1.01:
                        if 1.65 <= dec <= 3.70:
                            good_map[mid] = True
                        pt = f"({pr['points']})" if "points" in pr else ""
                        plist.append(f"{pr.get('designation', '')}{pt}={dec}")
                if plist:
                    odds_map.setdefault(mid, []).append(f"{mtype}:[{','.join(plist)}]")
            sp_lines = []
            for mid, title in m_map.items():
                if mid in odds_map:
                    total_found += 1
                    if mid in good_map:
                        sp_lines.append(f"{title} | {' ; '.join(odds_map[mid][:2])}")
            balanced.extend(sp_lines[:4])
        except Exception:
            pass
    print(f"Pinnacle (весь мир): найдено {total_found}, отобрано в анализ {len(balanced)}")
    return "\n".join(balanced[:24])
def get_all_sources():
    out = []
    pin_txt = get_pinnacle_feed()
    if pin_txt:
        out.append("=== ЛИНИЯ PINNACLE (MONEYLINE=1X2, TOTAL=ТОТАЛ, SPREAD=ФОРА) ===\n" + pin_txt)

    pm_list, pm_host = [], ".".join(["gamma-api", "polymarket", "com"])
    for tag in ["sports", "esports"]:
        try:
            r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug={tag}&limit=25", headers=HEADERS, timeout=10)
            if r.status_code == 200:
                for ev in r.json():
                    for m in ev.get("markets", [])[:2]:
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
        out.append("=== POLYMARKET (ОРИЕНТИР ВЕРОЯТНОСТЕЙ) ===\n" + "\n".join(pm_list[:15]))
    return "\n\n".join(out)

def ask_ai(prompt):
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        g_url = "https://" + ".".join(["api", "groq", "com"]) + "/openai/v1/chat/completions"
        hdr = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
        for gm in ["openai/gpt-oss-120b", "qwen/qwen3.8-27b", "openai/gpt-oss-20b"]:
            try:
                r = requests.post(g_url, headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": prompt}], "temperature": 0.25}, timeout=25)
                if r.status_code == 200:
                    choice = next(iter(r.json()["choices"]))
                    txt = choice["message"]["content"]
                    if len(txt) > 5:
                        print(f"ИИ (Groq {gm}) ответил: {len(txt)} симв.")
                        return txt
                else:
                    print(f"Groq {gm} HTTP {r.status_code}")
            except Exception as e:
                print(f"Groq {gm} err:", e)

    for m in ["gemini-3.8-flash", "gemini-3.6-flash"]:
        try:
            r = requests.post(f"{GEM_HOST}/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.25}}, timeout=25)
            if r.status_code == 200:
                cand = next(iter(r.json()["candidates"]))
                part = next(iter(cand["content"]["parts"]))
                txt = part["text"]
                if len(txt) > 5:
                    print(f"ИИ ({m}) ответил: {len(txt)} симв.")
                    return txt
        except Exception:
            pass
    return ""
def calc_ev(prob, odds):
    return round(float(np.mean(np.where(np.random.default_rng().random(100_000) < prob, odds - 1.0, -1.0))) * 100, 2)

def get_all_live_scores():
    espn, out = ".".join(["site", "api", "espn", "com"]), []
    paths = ["soccer/all/scoreboard", "football/nfl/scoreboard", "hockey/nhl/scoreboard", "basketball/nba/scoreboard", "tennis/atp/scoreboard", "tennis/wta/scoreboard"]
    for p in paths:
        try:
            r = requests.get(f"https://{espn}/apis/site/v2/sports/{p}", headers=HEADERS, timeout=8)
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    st_obj = ev.get("status", {})
                    st_det = st_obj.get("type", {}).get("shortDetail", "")
                    clk = st_obj.get("displayClock", "")
                    comp = next(iter(ev.get("competitions", [])), {})
                    sc = " : ".join([f"{c.get('team', {}).get('displayName', '')} ({c.get('score', '0')})" for c in comp.get("competitors", [])])
                    if sc:
                        out.append(f"{sc} | Статус: {st_det} {clk}".strip())
        except Exception:
            pass
    try:
        sdb = ".".join(["www", "thesportsdb", "com"])
        r = requests.get(f"https://{sdb}/api/v1/json/3/eventsday.php?d={NOW_TLT.strftime('%Y-%m-%d')}", headers=HEADERS, timeout=8)
        if r.status_code == 200 and r.json().get("events"):
            for e in r.json()["events"][:40]:
                if e.get("intHomeScore") is not None:
                    out.append(f"{e.get('strHomeTeam')} ({e.get('intHomeScore')}) : {e.get('strAwayTeam')} ({e.get('intAwayScore')}) | Статус: {e.get('strStatus', '')}")
    except Exception:
        pass
    return "\n".join(out)
def check_results(history, rules):
    upd = False
    live_board = get_all_live_scores()
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        st = datetime.datetime.fromisoformat(bet["start_iso"])
        if (NOW_TLT - st).total_seconds() / 3600.0 < 3.6:
            continue
        info = web_search(f"{bet['match']} финальный счет результат FT Final {st.strftime('%d.%m.%Y')}")
        raw = ask_ai(
            f"Проверь, ЗАВЕРШЁН ли матч окончательно. Матч: {bet['match']}. Ставка: {bet['pick']} ({bet['odds']}).\n"
            f"Мировое табло:\n{live_board}\nПоиск:\n{info}\n\n"
            f"СТРОГОЕ ПРАВИЛО: Если матч ещё идёт в лайве или нет точного подтверждения окончания (Final / FT / Завершён) — верни status: PENDING!\n"
            f"Верни JSON строго на русском: {{\"status\": \"WIN\"|\"LOSE\"|\"PENDING\", \"score\": \"Команда 1 Х : У Команда 2\", \"lesson\": \"если LOSE — 1 короткий вывод на русском для rules.txt, иначе пусто\"}}"
        )
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res["status"] in ("WIN", "LOSE"):
                bet["status"], bet["score"] = res["status"], res.get("score", "")
                stake = bet.get("stake_rub", 500)
                prof = round(stake * (bet["odds"] - 1.0), 0) if res["status"] == "WIN" else -stake
                history["bank"] = round(history["bank"] + prof, 0)
                if res["status"] == "LOSE" and res.get("lesson"):
                    rules += f"\n- Вывод ({NOW_TLT.strftime('%d.%m')}): {res['lesson']}"
                done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                wr = round(len([b for b in done if b["status"] == "WIN"]) / len(done) * 100, 1) if done else 0
                extra = f"\n🧠 <i>Вывод в базу:</i> {res['lesson']}" if res["status"] == "LOSE" and res.get("lesson") else ""
                send_tg(f"{'✅ ЗАХОД' if res['status']=='WIN' else '❌ МИНУС'} | <b>{bet['match']}</b>\nСчёт: <b>{bet['score']}</b> | Ставка: {bet['pick']} ({bet['odds']})\nИтог: <b>{prof:+.0f} ₽</b> | Банк: <b>{history['bank']:.0f} ₽</b> (Проход: {wr}%){extra}")
                upd = True
        except Exception:
            pass
    return history, rules, upd

def check_live(history):
    sent = False
    active = [b for b in history["bets"] if b["status"] == "PENDING" and not b.get("closed_live") and 5 <= (NOW_TLT - datetime.datetime.fromisoformat(b["start_iso"])).total_seconds() / 60.0 <= 160]
    if not active:
        return False
    live_board = get_all_live_scores()
    for bet in active:
        mins = int((NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0)
        info = web_search(f"{bet['match']} live счет статистика score")
        adv = ask_ai(
            f"Ты опытный спортивный аналитик. Матч {bet['match']} начался ~{mins} мин назад (учитывай перерыв 15 мин!). Ставка: {bet['pick']} за {bet['odds']}.\n"
            f"Мировое табло (HT = перерыв, Final/FT = конец):\n{live_board}\nПоиск:\n{info}\n\n"
            f"ПРАВИЛА:\n"
            f"1. Если точного счёта нет, матч уже закончен (Final/FT) или всё идёт по плану — верни СТРОГО слово OK.\n"
            f"2. Пиши СТРОГО на русском языке. Не выдумывай минуту матча из времени старта — бери минуту/тайм/перерыв только из табло или не пиши минуту вообще.\n"
            f"3. Если события идут против ставки — ответь в 3 строки:\n"
            f"Счёт: [Команда 1 Х : У Команда 2]\nДействие: [ДЕРЖАТЬ / ПРОДАТЬ / ПЕРЕКРЫТЬСЯ]\nПричина: [1-2 живых предложения на русском по ходу игры]"
        ).strip()
        if adv and "OK" not in adv[:15].upper():
            first_line = next(iter(adv.splitlines()), "")
            nums = ":".join(re.findall(r"\d+", first_line))
            if nums and bet.get("last_nums") == nums:
                continue
            if send_tg(f"⚡ <b>ЛАЙВ: {bet['match']}</b>\n{adv}"):
                if nums:
                    bet["last_nums"] = nums
                if "ПРОДАТЬ" in adv.upper():
                    bet["closed_live"] = True
                sent = True
    return sent
def parse_start_dt(dt_str):
    txt = str(dt_str).strip()
    t_part = txt.split()[-1] if " " in txt else txt
    parts = t_part.split(":")
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
    s2 = web_search(f"CS2 Dota 2 баскетбол теннис волейбол прогнозы коэффициенты {d_str} {tom_str}")
    prompt = (
        f"Ты опытный профессиональный аналитик ставок. Пиши СТРОГО на русском языке.\n"
        f"Текущее время: {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\n"
        f"НОВОСТИ И ПРОГНОЗЫ:\n{s1}\n{s2}\n\n"
        f"Найди 2–5 лучших ставок (валуи или «обратки» на кэфах 1.70–3.60) с математическим перевесом от 2.0% на ближайшие 16 часов от {t_str} (исключи взятые: {list(taken)}).\n"
        f"СТРОГИЕ ПРАВИЛА ОФОРМЛЕНИЯ:\n"
        f"1. Бери ТОЛЬКО реальные рынки и кэфы из данных выше — не выдумывай угловые/карточки, если их нет в линии.\n"
        f"2. ПЕРЕВЕДИ НА РУССКИЙ ВСЁ: названия команд/игроков (напр. «Кипр — Люксембург»), название вида спорта и лиги (напр. «Футбол | Товарищеские матчи (женщины)», «Киберспорт CS2 | ESL»), и саму ставку (напр. «П1», «П2», «Ф2 (+1.5)», «ТБ (2.5)», «Обе забьют — Нет», «ИТБ1 (1.5)»). Никаких английских слов!\n"
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"Команда 1 — Команда 2\", \"league\": \"Вид спорта | Лига на русском\", \"start_time\": \"ДД.ММ ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка на русском\", \"odds\": 1.95, \"prob\": 0.54}}]."
    )
    raw = ask_ai(prompt)
    try:
        cands = json.loads(raw[raw.find("["):raw.rfind("]")+1])
    except Exception as e:
        print("JSON parse err:", e, raw[:120])
        return history, False
    upd = False
    for c in cands:
        try:
            m_name = str(c.get("match", "")).strip()
            if not m_name or m_name in taken:
                continue
            odds, prob = float(c["odds"]), float(c["prob"])
            ev = calc_ev(prob, odds)
            print(f"Кандидат ИИ: {m_name} | {c.get('pick')} @ {odds} | prob={prob} -> перевес={ev}%")
            if ev < 2.0:
                continue
            min_odds = round(1.02 / prob, 2) if prob > 0 else odds
            edge_odds = round(odds - min_odds, 2)
            st = parse_start_dt(c.get("start_time", ""))
            stake = 500
            history["bets"].append({"match": m_name, "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": stake, "status": "PENDING", "score": ""})
            send_tg(
                f"🎯 <b>{c.get('type', 'Валуй').upper()} | {c.get('league', '')}</b>\n"
                f"🏆 <b>{m_name}</b>\n"
                f"⏰ Начало: <b>{st.strftime('%d.%m.%Y %H:%M')}</b>\n"
                f"📌 Ставка: <b>{c['pick']}</b> за <b>{odds:.2f}</b>\n"
                f"📊 Перевес в кэфе Фонбета: <b>+{edge_odds:.2f}</b> (брать от <b>{min_odds:.2f}</b>) | Шанс: <b>{prob*100:.1f}%</b>\n"
                f"💰 Сумма: <b>{stake} ₽</b>"
            )
            taken.add(m_name)
            upd = True
        except Exception:
            continue
    return history, upd

def send_daily_report(history):
    today_str = NOW_TLT.strftime("%Y-%m-%d")
    if NOW_TLT.hour == 9 and NOW_TLT.minute < 5 and history.get("last_report") != today_str:
        done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
        wins = len([b for b in done if b["status"] == "WIN"])
        pend = len([b for b in history["bets"] if b["status"] == "PENDING"])
        wr = round(wins / len(done) * 100, 1) if done else 0
        diff = history["bank"] - 10000
        send_tg(f"☀️ <b>УТРЕННЯЯ СВОДКА ({NOW_TLT.strftime('%d.%m.%Y')})</b>\n💰 Текущий банк: <b>{history['bank']:.0f} ₽</b> ({diff:+.0f} ₽)\n📈 Проход: <b>{wr}%</b> ({wins} из {len(done)} завершённых)\n⏳ Активных ставок в игре: <b>{pend}</b>")
        history["last_report"] = today_str
        return True
    return False

def main():
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f:
        rules = f.read()
    history, rules, u1 = check_results(history, rules)
    live_sent = check_live(history)
    rep_sent = send_daily_report(history)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    u2 = False
    if is_manual or (NOW_TLT.minute % 15 < 5):
        history, u2 = find_matches(history, rules)
    if u1 or u2 or live_sent or rep_sent:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2 or live_sent):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%d.%m.%Y %H:%M')})</b>\nВсе источники опрошены. Новых матчей с перевесом пока нет.")
    print(f"Готово ({NOW_TLT.strftime('%d.%m.%Y %H:%M')}). Лайв: {live_sent}, Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
