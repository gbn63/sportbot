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
        r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=15)
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

def sport_emoji(league_str):
    s = league_str.lower()
    if "футбол" in s: return "⚽"
    if "хоккей" in s: return "🏒"
    if "баскет" in s: return "🏀"
    if "наст" in s: return "🏓"
    if "теннис" in s: return "🎾"
    if "волей" in s: return "🏐"
    if "кибер" in s or "cs2" in s or "dota" in s: return "🎮"
    return "🏆"
def get_pinnacle_feed():
    now_ts, total_found, balanced, raw_odds = NOW_TLT.timestamp(), 0, [], {}
    pin = ".".join(["guest", "api", "arcadia", "pinnacle", "com"])
    sports = [(29, "Футбол"), (19, "Хоккей"), (4, "Баскетбол"), (33, "Теннис"), (12, "Киберспорт"), (34, "Волейбол"), (32, "Наст. теннис")]
    ban_words = ["women", "u18", "u19", "u20", "u21", "youth", "friendly", "reserves", "жен", "юниор", "товар", "молод"]
    for sid, sname in sports:
        try:
            rm = requests.get(f"https://{pin}/0.1/sports/{sid}/matchups?brandId=0", headers=HEADERS, timeout=8)
            rp = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
            if rm.status_code != 200 or rp.status_code != 200:
                continue
            m_map, pair_map = {}, {}
            for m in rm.json():
                st_iso = (m.get("startTime") or "").replace("Z", "+00:00")
                parts = m.get("participants", [])
                lg = m.get("league", {}).get("name", "")
                if not st_iso or len(parts) < 2 or any(w in lg.lower() for w in ban_words):
                    continue
                st_dt = datetime.datetime.fromisoformat(st_iso).astimezone(NOW_TLT.tzinfo)
                if 5 <= (st_dt.timestamp() - now_ts) / 60.0 <= 960:
                    home = next((x.get("name") for x in parts if x.get("alignment") == "home"), next(iter(parts)).get("name", ""))
                    away = next((x.get("name") for x in parts if x.get("alignment") == "away"), parts[-1].get("name", ""))
                    m_map[m["id"]] = f"[{st_dt.strftime('%d.%m %H:%M')}] {sname} ({lg}): {home} — {away}"
                    pair_map[m["id"]] = f"{home} — {away}".lower()
            odds_map, good_map = {}, {}
            for mk in rp.json():
                mid = mk.get("matchupId")
                if mid not in m_map or mk.get("period") != 0:
                    continue
                mtype = mk.get("type", "")
                plist, dec_vals = [], []
                for pr in mk.get("prices", []):
                    dec = am_to_dec(pr.get("price", 0))
                    if dec > 1.01:
                        dec_vals.append(dec)
                        if 1.60 <= dec <= 2.45:
                            good_map[mid] = True
                        pt = f"({pr['points']})" if "points" in pr else ""
                        plist.append(f"{pr.get('designation', '')}{pt}={dec}")
                if plist:
                    odds_map.setdefault(mid, []).append(f"{mtype}:[{','.join(plist)}]")
                    if mtype == "moneyline" and dec_vals:
                        raw_odds[pair_map[mid]] = min(dec_vals)
            sp_lines = []
            for mid, title in m_map.items():
                if mid in odds_map:
                    total_found += 1
                    if mid in good_map:
                        sp_lines.append(f"{title} | {' ; '.join(odds_map[mid][:3])}")
            balanced.extend(sp_lines[:4])
        except Exception:
            pass
    print(f"Pinnacle (проф. спорт): найдено {total_found}, отобрано {len(balanced)}")
    return "\n".join(balanced[:24]), raw_odds
def get_all_sources():
    out = []
    pin_txt, raw_odds = get_pinnacle_feed()
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
    return "\n\n".join(out), raw_odds

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
                    cards = []
                    for c in comp.get("competitors", []):
                        rc = c.get("redCards", 0)
                        c_txt = f" (Красных: {rc})" if rc else ""
                        cards.append(f"{c.get('team', {}).get('displayName', '')} ({c.get('score', '0')}){c_txt}")
                    if cards:
                        out.append(f"{' : '.join(cards)} | Статус: {st_det} {clk}".strip())
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

def check_prematch_alerts(history, raw_odds):
    sent = False
    if not raw_odds:
        return False
    for bet in history["bets"]:
        if bet["status"] != "PENDING" or bet.get("steam_sent"):
            continue
        st = datetime.datetime.fromisoformat(bet["start_iso"])
        mins_left = (st - NOW_TLT).total_seconds() / 60.0
        if mins_left > 15:
            orig_name = bet.get("orig_match", "").lower()
            cur_min = raw_odds.get(orig_name, 0)
            if cur_min and bet["odds"] - cur_min >= 0.14:
                ico = sport_emoji(bet.get("league", ""))
                msg = (
                    f"🔥 <b>ПРОГРУЗ ЛИНИИ</b>\n"
                    f"{ico} <b>{bet['match']}</b>\n"
                    f"📉 Кэф в Pinnacle просел: <b>{bet['odds']} → {cur_min}</b>\n"
                    f"✅ Наш исход: <b>{bet['pick']}</b>"
                )
                if send_tg(msg):
                    bet["steam_sent"] = True
                    sent = True
    return sent
def check_results(history, rules):
    upd = False
    live_board = get_all_live_scores()
    for bet in history["bets"]:
        if bet["status"] != "PENDING":
            continue
        st = datetime.datetime.fromisoformat(bet["start_iso"])
        if (NOW_TLT - st).total_seconds() / 3600.0 < 2.1:
            continue
        info = web_search(f"{bet['match']} финальный счет результат FT Final {st.strftime('%d.%m.%Y')}")
        raw = ask_ai(
            f"Проверь, ЗАВЕРШЁН ли матч окончательно. Матч: {bet['match']}. Ставка: {bet['pick']} ({bet['odds']}).\n"
            f"Мировое табло:\n{live_board}\nПоиск:\n{info}\n\n"
            f"СТРОГОЕ ПРАВИЛО: Если матч ещё идёт в лайве или нет точного подтверждения окончания (Final / FT / Завершён) — верни status: PENDING!\n"
            f"Верни JSON строго на русском: {{\"status\": \"WIN\"|\"LOSE\"|\"PENDING\", \"score\": \"Х : У\", \"lesson\": \"если LOSE — 1 короткий вывод на русском для rules.txt, иначе пусто\"}}"
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
                ico = sport_emoji(bet.get("league", ""))
                head = "✅ <b>СТАВКА ЗАШЛА</b>" if res["status"] == "WIN" else "❌ <b>СТАВКА НЕ ЗАШЛА</b>"
                extra = f"\n🧠 <i>Вывод:</i> {res['lesson']}" if res["status"] == "LOSE" and res.get("lesson") else ""
                send_tg(
                    f"{head}\n"
                    f"{ico} <b>{bet['match']}</b>\n\n"
                    f"📊 Итоговый счёт: <b>{bet['score']}</b>\n"
                    f"🎯 Исход: <b>{bet['pick']} за {bet['odds']}</b>\n"
                    f"💰 Итог: <b>{prof:+.0f} ₽</b> • Банк: <b>{history['bank']:.0f} ₽</b> <i>(проход {wr}%)</i>"
                    f"{extra}"
                )
                upd = True
        except Exception:
            pass
    return history, rules, upd

def check_live(history):
    sent = False
    active = [b for b in history["bets"] if b["status"] == "PENDING" and 5 <= (NOW_TLT - datetime.datetime.fromisoformat(b["start_iso"])).total_seconds() / 60.0 <= 108]
    if not active:
        return False
    live_board = get_all_live_scores()
    for bet in active:
        mins = int((NOW_TLT - datetime.datetime.fromisoformat(bet["start_iso"])).total_seconds() / 60.0)
        info = web_search(f"{bet['match']} live счет гол удаление красная карточка score")
        adv = ask_ai(
            f"Ты спортивный информатор. Матч {bet['match']} начался ~{mins} мин назад. Наша ставка: {bet['pick']} за {bet['odds']} (помни: (0) — это фора ноль, а не 0 голов!).\n"
            f"Мировое табло (HT = перерыв, Final/FT = конец):\n{live_board}\nПоиск:\n{info}\n\n"
            f"ПРАВИЛА:\n"
            f"1. Если точного счёта нет, матч уже закончен (Final/FT/Завершён), идёт 90+ минута (добавленное время) или счёт 0:0 без удалений — верни СТРОГО слово OK.\n"
            f"2. Сообщай ТОЛЬКО пока матч реально идёт в основное время (1-й или 2-й тайм до 89-й минуты) и изменился счёт или дали красную карточку/удаление.\n"
            f"3. НЕ давай никаких советов (никаких слов «Держать», «Продать», «Перекрыться»!). Пиши СТРОГО на русском языке. Минуту/тайм бери только из табло (если нет — не пиши).\n"
            f"Верни СТРОГО JSON: {{\"score\": \"Х : У\", \"time_info\": \"например: 2-й тайм, 68' или Перерыв (если неизвестно — пусто)\", \"status_text\": \"короткий статус ставки и событий на русском (напр. пока проходит, но команда в меньшинстве)\"}}"
        ).strip()
        if adv and "OK" not in adv[:15].upper():
            try:
                data = json.loads(adv[adv.find("{"):adv.rfind("}")+1])
                sc = str(data.get("score", "")).strip()
                st_txt = str(data.get("status_text", "")).strip()
                t_inf = str(data.get("time_info", "")).strip()
                full_check = f"{t_inf} {st_txt}".lower()
                if not sc or not st_txt or any(w in full_check for w in ["90+", "90'", "ft", "final", "заверш", "окончен", "выиграла", "проиграла", "итог"]):
                    continue
                sig = ":".join(re.findall(r"\d+", sc)) + ("_RED" if "КРАСН" in st_txt.upper() or "УДАЛЕН" in st_txt.upper() or "МЕНЬШИНСТВ" in st_txt.upper() else "")
                if sig and bet.get("last_sig") == sig:
                    continue
                lg = bet.get("league", "")
                sp_name = next(iter(lg.split("•"))).strip() if "•" in lg else (lg or "Спорт")
                ico = sport_emoji(lg)
                t_str = f" <i>({t_inf})</i>" if t_inf else ""
                msg = (
                    f"⏱ <b>МОНИТОРИНГ МАТЧА • {sp_name}</b>\n"
                    f"🆚 <b>{bet['match']}</b>\n\n"
                    f"📊 Счёт сейчас: <b>{sc}</b>{t_str}\n"
                    f"{ico} Ставка: <b>{bet['pick']} за {bet['odds']}</b> — <b>{st_txt}</b>"
                )
                if send_tg(msg):
                    if sig:
                        bet["last_sig"] = sig
                    sent = True
            except Exception:
                pass
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

def find_matches(history, rules, mkt_txt):
    taken = {b["match"] for b in history["bets"]}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    tom_str = (NOW_TLT + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    s1 = web_search(f"прогнозы обе забьют индивидуальный тотал ТБ ТМ {d_str} {tom_str} футбол хоккей КХЛ НХЛ")
    s2 = web_search(f"CS2 Dota 2 баскетбол теннис волейбол прогнозы тотал фора {d_str} {tom_str}")
    prompt = (
        f"Ты опытный квантовый аналитик ставок. Пиши СТРОГО на русском языке.\n"
        f"Текущее время: {d_str} {t_str}. Правила:\n{rules}\n\n{mkt_txt}\n\n"
        f"НОВОСТИ И ПРОГНОЗЫ:\n{s1}\n{s2}\n\n"
        f"Найди 2–5 лучших ставок по гибкой математической модели на ближайшие 16 часов от {t_str} (исключи взятые: {list(taken)}):\n"
        f"• Для кэфов 1.60–2.05: реальный шанс захода строго от 54% и выше.\n"
        f"• Для кэфов 2.06–2.45: реальный шанс захода от 48% и выше (сильные обратки и ничьи с перевесом от +5%).\n"
        f"СТРОГИЕ ПРАВИЛА:\n"
        f"1. ЗАПРЕЩЕНО брать женские, товарищеские и молодёжные/юниорские (U18/U20/U21) матчи. Только взрослый профессиональный спорт!\n"
        f"2. Обязательно ищи в линии Pinnacle и прогнозах Тоталы (ТБ/ТМ), Форы (Ф1/Ф2), Индивидуальные тоталы (ИТБ/ИТМ), Обе забьют (Да/Нет), а не только П1/П2.\n"
        f"3. Оценивай вероятность консервативно (учитывай маржу Pinnacle ~2% как эталон честной линии).\n"
        f"4. ПЕРЕВЕДИ НА РУССКИЙ ВСЁ: команды, вид спорта и лигу, ставку (без английских слов). В поле orig_match укажи точное название матча из линии Pinnacle на английском.\n"
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"Команда 1 — Команда 2\", \"orig_match\": \"Team 1 — Team 2\", \"league\": \"Вид спорта • Лига\", \"start_time\": \"ДД.ММ ЧЧ:ММ\", \"type\": \"Валуй или Обратка\", \"pick\": \"Ставка на русском\", \"odds\": 1.88, \"prob\": 0.58}}]."
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
            odds, raw_prob = float(c["odds"]), float(c["prob"])
            if not (1.58 <= odds <= 2.45):
                continue
            mkt_prob = 1.0 / odds
            prob = round(raw_prob * 0.75 + mkt_prob * 0.25, 3)
            ev = calc_ev(prob, odds)
            ok_low = (odds <= 2.05 and prob >= 0.54 and ev >= 2.0)
            ok_high = (odds > 2.05 and prob >= 0.48 and ev >= 5.0)
            if not (ok_low or ok_high):
                print(f"Отсеян гибким фильтром: {m_name} @ {odds} (сглаж. шанс {prob*100:.1f}%, перевес {ev}%)")
                continue
            print(f"Принят моделью: {m_name} | {c.get('pick')} @ {odds} | шанс={prob*100:.1f}% -> перевес={ev}%")
            fair_odds = round(1.0 / prob, 2)
            min_odds = round(1.03 / prob, 2)
            rel = "Высокая (3/3)" if (ev >= 6.0 and prob >= 0.55) else "Хорошая (2/3)"
            st = parse_start_dt(c.get("start_time", ""))
            lg_str = c.get("league", "")
            ico = sport_emoji(lg_str)
            history["bets"].append({"match": m_name, "orig_match": c.get("orig_match", ""), "league": lg_str, "start_iso": st.isoformat(), "type": c.get("type", "Валуй"), "pick": c["pick"], "odds": odds, "prob": prob, "ev": ev, "stake_rub": 500, "status": "PENDING", "score": ""})
            send_tg(
                f"{ico} <b>{lg_str}</b>\n"
                f"🆚 <b>{m_name}</b>\n"
                f"⏰ {st.strftime('%d.%m.%Y • %H:%M')}\n\n"
                f"✅ Исход: <b>{c['pick']}</b>\n"
                f"📈 Кэф в линии: <b>{odds:.2f}</b> <i>(честный: {fair_odds:.2f} | в Фонбете от {min_odds:.2f})</i>\n"
                f"🔥 Перевес над линией: <b>+{ev:.1f}%</b> • Шанс захода: <b>{prob*100:.0f}%</b>\n"
                f"⭐️ Надёжность: <b>{rel}</b>"
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
    u2, pre_sent = False, False
    if is_manual or (NOW_TLT.minute % 15 < 5):
        mkt_txt, raw_odds = get_all_sources()
        pre_sent = check_prematch_alerts(history, raw_odds)
        history, u2 = find_matches(history, rules, mkt_txt)
    if u1 or u2 or live_sent or rep_sent or pre_sent:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2 or live_sent or pre_sent):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%d.%m.%Y %H:%M')})</b>\nВсе источники опрошены. Новых матчей с высоким шансом и перевесом пока нет.")
    print(f"Готово ({NOW_TLT.strftime('%d.%m.%Y %H:%M')}). Лайв: {live_sent}, Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
