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

def get_fonbet_by():
    now_ts, out = NOW_TLT.timestamp(), []
    fmap = {921: "П1", 922: "Х", 923: "П2", 924: "1Х", 925: "12", 926: "Х2", 930: "ТБ", 931: "ТМ"}
    for sub in ["line01", "line02", "line03"]:
        try:
            host = ".".join([sub, "fonbet", "by"])
            r = requests.get(f"https://{host}/events/list?lang=ru&scopeMarket=1600", headers=HEADERS, timeout=10)
            if r.status_code != 200:
                continue
            data = r.json()
            evs = {e["id"]: e for e in data.get("events", []) if e.get("level") == 1 and 5 <= (e.get("startTime", 0) - now_ts) / 60.0 <= 960}
            for cf in data.get("customFactors", []):
                eid = cf.get("e")
                if eid not in evs:
                    continue
                ev = evs.pop(eid)
                t1, t2 = ev.get("team1", ""), ev.get("team2", "")
                if not t1 or not t2:
                    continue
                olist = []
                for f in cf.get("factors", []):
                    fid = f.get("f")
                    if fid in fmap:
                        pt = f"({f['pt']})" if "pt" in f else ""
                        olist.append(f"{fmap.get(fid)}{pt}={f.get('v')}")
                if olist:
                    st_s = datetime.datetime.fromtimestamp(ev["startTime"], tz=NOW_TLT.tzinfo).strftime("%d.%m %H:%M")
                    out.append(f"[{st_s}] {t1} — {t2} | {', '.join(olist[:5])}")
            if out:
                print(f"Fonbet.by ({sub}): {len(out)} матчей с кэфами")
                return "\n".join(out[:20])
        except Exception:
            pass
    print("Fonbet.by: недоступен с IP США")
    return ""

def get_betcity_by():
    now_ts, out = NOW_TLT.timestamp(), []
    try:
        host = ".".join(["ad", "betcity", "by"])
        r = requests.get(f"https://{host}/d/off/events?rev=8&ver=463&csn=ooca9s", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            sports = r.json().get("reply", {}).get("sports", {})
            for sp in sports.values():
                sname = sp.get("name_sp", "")
                for ch in sp.get("chmps", {}).values():
                    lg = ch.get("name_ch", "")
                    for ev in ch.get("evts", {}).values():
                        st_ts = ev.get("date_ev", 0)
                        if not (5 <= (st_ts - now_ts) / 60.0 <= 960):
                            continue
                        t1, t2 = ev.get("name_ht", ""), ev.get("name_at", "")
                        main_m = ev.get("main", {})
                        olist = []
                        for grp in main_m.values():
                            for k, val in grp.get("data", {}).items():
                                for mk_name, mk_obj in val.get("blocks", {}).items():
                                    for o_k, o_v in mk_obj.items():
                                        if isinstance(o_v, dict) and "kf" in o_v:
                                            olist.append(f"{o_k}={o_v['kf']}")
                        if t1 and t2 and olist:
                            st_s = datetime.datetime.fromtimestamp(st_ts, tz=NOW_TLT.tzinfo).strftime("%d.%m %H:%M")
                            out.append(f"[{st_s}] {sname} ({lg}): {t1} — {t2} | {', '.join(olist[:5])}")
            if out:
                print(f"Betcity.by: {len(out)} матчей с кэфами")
                return "\n".join(out[:20])
    except Exception:
        pass
    print("Betcity.by: недоступен с IP США")
    return ""
def get_pinnacle_feed():
    now_ts, total_found, balanced = NOW_TLT.timestamp(), 0, []
    pin = ".".join(["guest", "api", "arcadia", "pinnacle", "com"])
    sports = [(29, "Футбол"), (19, "Хоккей"), (4, "Баскетбол"), (33, "Теннис"), (12, "Киберспорт"), (34, "Волейбол"), (32, "Наст.теннис")]
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
    return "\n".join(balanced[:22])

def get_all_sources():
    out = []
    fb_txt = get_fonbet_by()
    if fb_txt:
        out.append("=== ЛИНИЯ FONBET.BY ===\n" + fb_txt)
    bc_txt = get_betcity_by()
    if bc_txt:
        out.append("=== ЛИНИЯ BETCITY.BY ===\n" + bc_txt)
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
                r = requests.post(g_url, headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}, timeout=25)
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
            r = requests.post(f"{GEM_HOST}/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.3}}, timeout=25)
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
        raw = ask_ai(f"Проверь итог. Матч: {bet['match']}. Ставка: {bet['pick']} ({bet['odds']}). Данные:\n{info}\nВерни JSON: {{\"status\": \"WIN\"|\"LOSE\"|\"PENDING\", \"score\": \"счет\", \"lesson\": \"если LOSE — 1 короткий вывод живым языком для rules.txt, иначе пусто\"}}")
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res["status"] in ("WIN", "LOSE"):
                bet["status"], bet["score"] = res["status"], res.get("score", "")
                prof = round(bet["stake_rub"] * (bet["odds"] - 1.0), 0) if res["status"] == "WIN" else -bet["stake_rub"]
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
    active = [b for b in history["bets"] if b["status"] == "PENDING" and 5 <= (NOW_TLT - datetime.datetime.fromisoformat(b["start_iso"])).total_seconds() / 60.0 <= 135]
    if not active:
        return False
    espn_sc = get_espn_live()
    for bet in active:
        mins = int((NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0)
        info = web_search(f"{bet['match']} live счет минута статистика score")
        adv = ask_ai(
            f"Ты опытный спортивный аналитик. Матч {bet['match']} идёт в лайве (~{mins} мин). Ставка: {bet['pick']} за {bet['odds']}.\n"
            f"Табло ESPN:\n{espn_sc}\nПоиск:\n{info}\n\n"
            f"Если точного счёта нет или всё идёт по плану — верни СТРОГО слово OK.\n"
            f"Если есть реальный счёт и события идут против ставки — ответь живым, понятным человеческим языком в 3 строки:\n"
            f"Счёт: [текущий счёт без указания минуты]\nДействие: [ДЕРЖАТЬ / ПРОДАТЬ / ПЕРЕКРЫТЬСЯ]\nПричина: [1-2 живых предложения по ходу матча, без канцелярита]"
        ).strip()
        if adv and "OK" not in adv[:15].upper():
            first_line = next(iter(adv.splitlines()), "")
            if bet.get("last_live") != first_line and send_tg(f"⚡ <b>ЛАЙВ: {bet['match']}</b>\n{adv}"):
                bet["last_live"] = first_line
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
    s2 = web_search(f"CS2 Dota 2 баскетбол теннис волейбол прогнозы коэффициенты {d_str} {tom_str}")
    prompt = (
        f"Ты опытный профессиональный аналитик ставок. Пиши живым, чётким и понятным русским языком, без канцелярита и воды.\n"
        f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\n"
        f"НОВОСТИ И ПРОГНОЗЫ:\n{s1}\n{s2}\n\n"
        f"Найди 2–5 лучших ставок (валуи или «обратки» на кэфах 1.70–3.60) с перевесом +EV >= 2.0% на ближайшие 16 часов от {t_str} (исключи взятые: {list(taken)}).\n"
        f"СТРОГИЕ ПРАВИЛА ОФОРМЛЕНИЯ:\n"
        f"1. Бери ТОЛЬКО реальные рынки и кэфы из данных выше — не выдумывай угловые/карточки, если их нет в линии.\n"
        f"2. В поле pick пиши строго по-русски стандартным сленгом БК (БЕЗ английских слов over/under/home/away): например «П1», «П2», «Ф2 (+1.5)», «ТБ (2.5)», «ТМ (5.5)», «Обе забьют — Нет», «ИТБ1 (1.5)».\n"
        f"3. Поля reason, live_plan и risk пиши живым человеческим языком (1–2 коротких предложения, конкретно по форме, составам и движению кэфов).\n"
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"Команда 1 — Команда 2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Ставка\", \"odds\": 1.95, \"prob\": 0.54, \"reason\": \"Живое объяснение\", \"live_plan\": \"Что делать в лайве\", \"risk\": \"Главный риск\"}}]."
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
            ev, pct, rub = calc_stats(prob, odds, history["bank"])
            print(f"Кандидат ИИ: {m_name} | {c.get('pick')} @ {odds} | prob={prob} -> +EV={ev}%")
            if ev < 2.0 or rub <= 0:
                continue
            min_odds = round(1.02 / prob, 2) if prob > 0 else odds
            st = parse_start_dt(c.get("start_time", ""))
            history["bets"].append({"match": m_name, "league": c.get("league", ""), "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": rub, "status": "PENDING", "score": ""})
            send_tg(f"🎯 <b>{c.get('type', 'Валуй').upper()} | {c.get('league', '')}</b>\n🏆 <b>{m_name}</b>\n⏰ Начало: <b>{st.strftime('%H:%M')} ТЛТ</b>\n📌 Ставка: <b>{c['pick']}</b> за <b>{odds:.2f}</b> (в Фонбете брать от <b>{min_odds:.2f}</b>)\n📊 Шанс захода: <b>{prob*100:.1f}%</b> | Перевес: <b>+{ev}% EV</b>\n💰 Сумма: <b>{rub:.0f} ₽</b> ({pct}% от банка)\n\n💬 <b>Почему берём:</b> {c.get('reason', '')}\n⚡ <b>План на лайв:</b> {c.get('live_plan', '')}\n⚠️ <b>Риск:</b> {c.get('risk', '')}")
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
    if is_manual or (NOW_TLT.minute % 30 < 5):
        history, u2 = find_matches(history, rules)
    if u1 or u2 or live_sent or rep_sent:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2 or live_sent):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%H:%M')} ТЛТ)</b>\nВсе безлимитные источники опрошены. Новых матчей с перевесом от +2.0% EV пока нет.")
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Лайв: {live_sent}, Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
