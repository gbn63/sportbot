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

def update_pinned_stats(history):
    done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
    wins = len([b for b in done if b["status"] == "WIN"])
    losses = len([b for b in done if b["status"] == "LOSE"])
    pend = len([b for b in history["bets"] if b["status"] == "PENDING"])
    wr = round(wins / len(done) * 100, 1) if done else 0.0
    diff = history["bank"] - 10000
    total_staked = sum(b.get("stake_rub", 500) for b in done)
    roi = round((diff / total_staked) * 100, 1) if total_staked > 0 else 0.0
    avg_odds = round(sum(float(b.get("odds", 0)) for b in done) / len(done), 2) if done else 0.0

    streak_str = "—"
    if done:
        last_st = done[-1]["status"]
        cnt = 0
        for b in reversed(done):
            if b["status"] == last_st:
                cnt += 1
            else:
                break
        streak_str = f"{cnt}{'✅' if last_st == 'WIN' else '❌'} подряд"

    sp_stats = {}
    for b in done:
        lg = b.get("league", "")
        sp = next(iter(lg.split("•"))).strip() if "•" in lg else (lg or "Спорт")
        if sp not in sp_stats:
            sp_stats[sp] = {"w": 0, "t": 0}
        sp_stats[sp]["t"] += 1
        if b["status"] == "WIN":
            sp_stats[sp]["w"] += 1
    top_sp = "сбор данных"
    if sp_stats:
        best_sp, best_data = max(sp_stats.items(), key=lambda x: (x[1]["w"] / x[1]["t"], x[1]["t"]))
        top_sp = f"{best_sp} ({round(best_data['w'] / best_data['t'] * 100)}%)"

    bank_fmt = f"{int(history['bank']):,}".replace(",", " ")
    text = (
        f"📊 <b>ОТЧЁТ КАНАЛА</b>\n\n"
        f"<b>Финансы:</b>\n"
        f"💰 Банк: <b>{bank_fmt} ₽</b> <i>({diff:+.0f} ₽)</i> • ROI: <b>{roi:+.1f}%</b>\n\n"
        f"<b>Дистанция:</b>\n"
        f"🎯 Винрейт: <b>{wr}%</b> <i>({wins}✅ / {losses}❌)</i> • Ср. кэф: <b>{avg_odds:.2f}</b>\n"
        f"🔥 Серия: <b>{streak_str}</b> • Топ: <b>{top_sp}</b>\n\n"
        f"⏳ В игре: <b>{pend}</b> • 🕒 <i>{NOW_TLT.strftime('%d.%m.%Y • %H:%M')}</i>"
    )
    msg_id = history.get("pin_msg_id")
    if msg_id:
        r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/editMessageText", json={"chat_id": CHAT_ID, "message_id": msg_id, "text": text, "parse_mode": "HTML"}, timeout=15)
        if r.status_code == 200 or "message is not modified" in r.text:
            return False
    r = requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/sendMessage", json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    if r.status_code == 200:
        new_id = r.json().get("result", {}).get("message_id")
        if new_id:
            history["pin_msg_id"] = new_id
            requests.post(f"{TG_HOST}/bot{BOT_TOKEN}/pinChatMessage", json={"chat_id": CHAT_ID, "message_id": new_id, "disable_notification": True}, timeout=15)
            return True
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
    if any(k in s for k in ("футбол", "soccer", "division", "liga", "лига")): return "⚽"
    if "хоккей" in s: return "🏒"
    if "баскет" in s: return "🏀"
    if "бейсбол" in s: return "⚾"
    if "волей" in s: return "🏐"
    if "гандбол" in s: return "🤾"
    if any(k in s for k in ("кибер", "counter", "cs2", "dota", "league of legends", "lol")): return "🎮"
    return "🏆"
def format_pin_pick(sid, period, mtype, des, points):
    if sid == 19:
        if period == 0:
            suf = " (с ОТ)"
        elif period == 1:
            suf = " (осн. время)"
        else:
            return ""
    elif sid in (4, 3):
        if period != 0:
            return ""
        suf = " (с ОТ)"
    else:
        if period != 0:
            return ""
        suf = ""

    if mtype == "moneyline":
        if sid == 19 and period == 0:
            return {"home": "Победа К1 (с ОТ)", "away": "Победа К2 (с ОТ)"}.get(des, "")
        if sid in (4, 3):
            return {"home": "Победа К1 (с ОТ)", "away": "Победа К2 (с ОТ)"}.get(des, "")
        base = {"home": "П1", "away": "П2", "draw": "Ничья (Х)"}.get(des, "")
        return f"{base}{suf}" if base else ""
    if mtype == "spread" and points is not None:
        pv = float(points)
        if round(pv * 4) % 2 != 0:
            return ""
        side = "Ф1" if des == "home" else "Ф2" if des == "away" else ""
        return f"{side} ({pv:+g}){suf}" if side else ""
    if mtype == "total" and points is not None:
        pv = float(points)
        if round(pv * 4) % 2 != 0:
            return ""
        side = "ТБ" if des == "over" else "ТМ" if des == "under" else ""
        return f"{side} ({pv:g}){suf}" if side else ""
    return ""

def get_pinnacle_feed(include_prematch=True):
    now_ts, pre_found, live_found, pre_bal, live_bal, exact_map = NOW_TLT.timestamp(), 0, 0, [], [], {}
    pin = ".".join(["guest", "api", "arcadia", "pinnacle", "com"])
    sports = [(29, "Футбол"), (19, "Хоккей"), (4, "Баскетбол"), (3, "Бейсбол"), (34, "Волейбол"), (18, "Гандбол"), (12, "Киберспорт")]
    ban_words = [
        "u18", "u19", "youth", "friendly", "reserves", "юниор", "товар",
        "bangladesh", "cambodia", "myanmar", "laos", "nepal", "bhutan", "mongolia",
        "nicaragua", "salvador", "guatemala", "honduras", "belize", "panama", "bolivia",
        "ethiopia", "kenya", "uganda", "tanzania", "rwanda", "burundi", "zambia", "malawi",
        "ascenso", "tercera", "regional", "amateur", "oberliga", "regionalliga"
    ]
    esports_ok = ["counter-strike", "cs2", "cs:", "dota", "league of legends", "lol"]
    live_sports_ok = {29, 19, 12}

    for sid, sname in sports:
        try:
            rm = requests.get(f"https://{pin}/0.1/sports/{sid}/matchups?brandId=0", headers=HEADERS, timeout=8)
            if rm.status_code != 200:
                continue
            mk_list = []
            rp_pre = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
            if rp_pre.status_code == 200:
                mk_list.extend(rp_pre.json())
            if sid in live_sports_ok:
                rp_live = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/live/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
                if rp_live.status_code == 200:
                    mk_list.extend(rp_live.json())

            m_map, raw_pair, is_live_map = {}, {}, {}
            for m in rm.json():
                st_iso = (m.get("startTime") or "").replace("Z", "+00:00")
                parts = m.get("participants", [])
                lg = m.get("league", {}).get("name", "")
                lg_low = lg.lower()
                if not st_iso or len(parts) < 2 or any(w in lg_low for w in ban_words):
                    continue
                if sid == 12 and not any(k in lg_low for k in esports_ok):
                    continue
                st_dt = datetime.datetime.fromisoformat(st_iso).astimezone(NOW_TLT.tzinfo)
                diff_min = (st_dt.timestamp() - now_ts) / 60.0
                live_flag = bool(m.get("isLive") or m.get("liveMode") == "live" or (-115 <= diff_min < 0))
                home = next((x.get("name") for x in parts if x.get("alignment") == "home"), next(iter(parts)).get("name", ""))
                away = next((x.get("name") for x in parts if x.get("alignment") == "away"), parts[-1].get("name", ""))

                if live_flag and sid in live_sports_ok and -115 <= diff_min <= 2:
                    st_state = m.get("state", {})
                    sc_txt = f" | Счёт: {st_state.get('homeScore', '?')}:{st_state.get('awayScore', '?')}" if "homeScore" in st_state else ""
                    m_map[m["id"]] = f"[LIVE] [ID:{m['id']}] [Старт {st_dt.strftime('%H:%M')}] {sname} ({lg}): К1={home} — К2={away}{sc_txt}"
                    raw_pair[m["id"]] = (f"{home} — {away}", st_dt.isoformat())
                    is_live_map[m["id"]] = True
                elif include_prematch and not live_flag and 10 <= diff_min <= 240:
                    m_map[m["id"]] = f"[PRE] [ID:{m['id']}] [{st_dt.strftime('%d.%m %H:%M')}] {sname} ({lg}): К1={home} — К2={away}"
                    raw_pair[m["id"]] = (f"{home} — {away}", st_dt.isoformat())
                    is_live_map[m["id"]] = False

            odds_map, good_map = {}, {}
            for mk in mk_list:
                mid = mk.get("matchupId")
                if mid not in m_map:
                    continue
                per = mk.get("period", -1)
                mtype = mk.get("type", "")
                plist = []
                for pr in mk.get("prices", []):
                    dec = am_to_dec(pr.get("price", 0))
                    label = format_pin_pick(sid, per, mtype, pr.get("designation", ""), pr.get("points"))
                    if dec > 1.01 and label:
                        if 1.60 <= dec <= 2.45:
                            good_map[mid] = True
                        plist.append(f"«{label}»={dec}")
                        pair_str, st_iso_str = raw_pair[mid]
                        sc_val = m_map[mid].split("Счёт: ")[-1] if "Счёт: " in m_map[mid] else ""
                        exact_map[(mid, label)] = (dec, pair_str, st_iso_str, is_live_map[mid], sc_val)
                if plist:
                    odds_map.setdefault(mid, []).append(", ".join(plist))

            sp_pre, sp_live = [], []
            for mid, title in m_map.items():
                if mid in odds_map:
                    if is_live_map[mid]:
                        live_found += 1
                        if mid in good_map:
                            sp_live.append(f"{title} | Рынки: {' ; '.join(odds_map[mid][:4])}")
                    else:
                        pre_found += 1
                        if mid in good_map:
                            sp_pre.append(f"{title} | Рынки: {' ; '.join(odds_map[mid][:4])}")
            pre_bal.extend(sp_pre[:4])
            live_bal.extend(sp_live[:3])
        except Exception:
            pass
    print(f"Pinnacle: Прематч {pre_found} (отбор {len(pre_bal)}), Лайв {live_found} (отбор {len(live_bal)})")
    lines = live_bal[:12] + pre_bal[:20]
    return "\n".join(lines), exact_map
def get_all_sources(include_prematch=True):
    out = []
    pin_txt, exact_map = get_pinnacle_feed(include_prematch=include_prematch)
    if pin_txt:
        out.append("=== ЛИНИЯ PINNACLE (LIVE И ПРЕМАТЧ — ТОЧНЫЕ РЫНКИ И КЭФЫ) ===\n" + pin_txt)

    if include_prematch:
        pm_list, pm_host = [], ".".join(["gamma-api", "polymarket", "com"])
        allow_pm = ("soccer", "football", "nba", "basketball", "nhl", "hockey", "mlb", "baseball", "volleyball", "handball", "counter-strike", "cs2", "dota", "league of legends", "lol")
        for tag in ["sports", "esports"]:
            try:
                r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug={tag}&limit=30", headers=HEADERS, timeout=10)
                if r.status_code == 200:
                    for ev in r.json():
                        title_low = (ev.get("title", "") + " " + ev.get("slug", "")).lower()
                        if not any(k in title_low for k in allow_pm):
                            continue
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
        print(f"Polymarket (по списку спорта): {len(pm_list)} рынков")
        if pm_list:
            out.append("=== POLYMARKET (ОРИЕНТИР ВЕРОЯТНОСТЕЙ) ===\n" + "\n".join(pm_list[:15]))
    return "\n\n".join(out), exact_map

def ask_ai(prompt):
    for circle in range(1, 4):
        cur_prompt = prompt if circle == 1 else prompt[:11000]

        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if groq_key:
            try:
                g_base = "https://" + ".".join(["api", "groq", "com"]) + "/openai/v1"
                hdr = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                mr = requests.get(f"{g_base}/models", headers=hdr, timeout=8)
                if mr.status_code == 200:
                    bad = ("whisper", "tts", "guard", "orpheus", "embed", "vision", "safeguard")
                    models = [x["id"] for x in mr.json().get("data", []) if not any(b in x["id"].lower() for b in bad)]
                    models.sort(key=lambda s: (0 if "120b" in s else 1 if "70b" in s else 2 if any(k in s for k in ("32b", "27b", "20b")) else 3))
                    for gm in models:
                        try:
                            r = requests.post(f"{g_base}/chat/completions", headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": cur_prompt}], "temperature": 0.2}, timeout=20)
                            if r.status_code == 200:
                                txt = next(iter(r.json()["choices"]))["message"]["content"]
                                if "{" in txt or "[" in txt:
                                    print(f"ИИ (круг {circle}, Groq {gm}) ответил: {len(txt)} симв.")
                                    return txt
                        except Exception:
                            continue
            except Exception:
                pass

        g_list = ["gemma-3-27b-it", "gemini-2.5-flash", "gemini-2.0-flash", "gemma-3-12b-it", "gemma-3-4b-it"]
        try:
            mr = requests.get(f"{GEM_HOST}/v1beta/models?key={GEMINI_API_KEY}", timeout=8)
            if mr.status_code == 200:
                skip = ("embed", "imagen", "veo", "aqa", "tts", "robotics", "computer", "research", "lite", "exp", "preview", "pro")
                for m in mr.json().get("models", []):
                    nm = m["name"].replace("models/", "")
                    if "generateContent" in m.get("supportedGenerationMethods", []) and not any(s in nm.lower() for s in skip) and nm not in g_list:
                        g_list.append(nm)
        except Exception:
            pass

        for gm in g_list:
            try:
                r = requests.post(f"{GEM_HOST}/v1beta/models/{gm}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": cur_prompt}]}], "generationConfig": {"temperature": 0.2}}, timeout=25)
                if r.status_code == 200:
                    cand = next(iter(r.json()["candidates"]))
                    txt = next(iter(cand["content"]["parts"]))["text"]
                    if "{" in txt or "[" in txt:
                        print(f"ИИ (круг {circle}, Google {gm}) ответил: {len(txt)} симв.")
                        return txt
            except Exception:
                continue

        p_url = "https://" + ".".join(["text", "pollinations", "ai"]) + "/openai"
        for pm in ["openai", "mistral", "deepseek"]:
            try:
                r = requests.post(p_url, headers={"Content-Type": "application/json"}, json={"model": pm, "messages": [{"role": "user", "content": cur_prompt}], "temperature": 0.2}, timeout=30)
                if r.status_code == 200:
                    txt = next(iter(r.json()["choices"]))["message"]["content"]
                    if "{" in txt or "[" in txt:
                        print(f"ИИ (круг {circle}, Резерв {pm}) ответил: {len(txt)} симв.")
                        return txt
            except Exception:
                continue

        if circle < 3:
            print(f"Круг {circle} занят, жду 10 сек и запускаю круг {circle + 1}...")
            time.sleep(10)

    return ""
def calc_ev(prob, odds):
    return round(float(np.mean(np.where(np.random.default_rng().random(100_000) < prob, odds - 1.0, -1.0))) * 100, 2)

def eval_line_diff(diff):
    def half_res(x):
        if x > 1e-6: return 1.0
        if x < -1e-6: return -1.0
        return 0.0
    if round(abs(diff) * 4) % 2 == 1:
        return (half_res(diff - 0.25) + half_res(diff + 0.25)) / 2.0
    return half_res(diff)

def settle_bet_math(pick, h_sc, a_sc):
    p = pick.strip()
    if p.startswith(("П1", "Победа К1")):
        return 1.0 if h_sc > a_sc else -1.0
    if p.startswith(("П2", "Победа К2")):
        return 1.0 if a_sc > h_sc else -1.0
    if p.startswith("Ничья"):
        return 1.0 if h_sc == a_sc else -1.0
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", p)
    if m:
        val = float(m.group(1))
        if p.startswith("Ф1"):
            return eval_line_diff((h_sc - a_sc) + val)
        if p.startswith("Ф2"):
            return eval_line_diff((a_sc - h_sc) + val)
        if p.startswith("ТБ"):
            return eval_line_diff((h_sc + a_sc) - val)
        if p.startswith("ТМ"):
            return eval_line_diff(val - (h_sc + a_sc))
    return None

def get_all_live_scores():
    espn, out = ".".join(["site", "api", "espn", "com"]), []
    paths = ["soccer/all/scoreboard", "hockey/nhl/scoreboard", "basketball/nba/scoreboard", "baseball/mlb/scoreboard"]
    for p in paths:
        try:
            r = requests.get(f"https://{espn}/apis/site/v2/sports/{p}", headers=HEADERS, timeout=8)
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    st_det = ev.get("status", {}).get("type", {}).get("shortDetail", "")
                    comp = next(iter(ev.get("competitions", [])), {})
                    sc = " : ".join([f"{c.get('team', {}).get('displayName', '')} ({c.get('score', '0')})" for c in comp.get("competitors", [])])
                    if sc:
                        out.append(f"{sc} | Статус: {st_det}".strip())
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
        if (NOW_TLT - st).total_seconds() / 3600.0 < 2.2:
            continue
        q_name = bet.get("orig_match") or bet["match"]
        info = web_search(f"{bet['match']} {q_name} финальный счет результат FT Final {st.strftime('%d.%m.%Y')}")
        raw = ask_ai(
            f"Проверь, ЗАВЕРШЁН ли матч окончательно. Матч: {bet['match']} ({q_name}). Лига: {bet.get('league', '')}. Ставка: {bet['pick']}.\n"
            f"Мировое табло:\n{live_board}\nПоиск:\n{info}\n\n"
            f"СТРОГОЕ ПРАВИЛО:\n"
            f"1. Если матч ещё идёт или нет точного подтверждения окончания (Final / FT / Завершён) — верни finished: false!\n"
            f"2. Если в ставке есть пометка «(с ОТ)» — укажи итоговый счёт с учётом овертайма/буллитов; если «(осн. время)» — счёт основного времени.\n"
            f"3. В поле lesson напиши 1 конкретное тактическое правило на будущее для этой лиги или рынка (ЗАПРЕЩЕНО пересказывать счёт).\n"
            f"Верни СТРОГО JSON: {{\"finished\": true|false, \"home_score\": 2, \"away_score\": 1, \"match_ru\": \"Команда 1 — Команда 2\", \"lesson\": \"конкретный вывод\"}}"
        )
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res.get("finished") and res.get("home_score") is not None and res.get("away_score") is not None:
                h_sc, a_sc = int(res["home_score"]), int(res["away_score"])
                mult = settle_bet_math(bet["pick"], h_sc, a_sc)
                if mult is None:
                    continue
                m_ru = str(res.get("match_ru") or bet["match"]).strip()
                bet["match"] = m_ru
                bet["score"] = f"{h_sc} : {a_sc}"
                stake = bet.get("stake_rub", 500)
                if mult > 0:
                    bet["status"] = "WIN"
                    prof = round(stake * (bet["odds"] - 1.0) * mult, 0)
                    head = "✅ <b>СТАВКА ЗАШЛА</b>"
                elif mult == 0:
                    bet["status"] = "VOID"
                    prof = 0
                    head = "🔄 <b>ВОЗВРАТ СТАВКИ</b>"
                else:
                    bet["status"] = "LOSE"
                    prof = round(stake * mult, 0)
                    head = "❌ <b>СТАВКА НЕ ЗАШЛА</b>"

                history["bank"] = round(history["bank"] + prof, 0)
                lesson = str(res.get("lesson", "")).strip()
                if bet["status"] in ("WIN", "LOSE") and lesson and len(lesson) > 15:
                    tag = "Плюс-паттерн" if bet["status"] == "WIN" else "Ошибка"
                    rules += f"\n- Вывод [{tag}] ({NOW_TLT.strftime('%d.%m')}): {lesson}"
                    base_lines = [l for l in rules.splitlines() if not l.startswith("- Вывод [")]
                    learned_lines = [l for l in rules.splitlines() if l.startswith("- Вывод [")][-15:]
                    rules = "\n".join(base_lines + learned_lines)

                done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                wr = round(len([b for b in done if b["status"] == "WIN"]) / len(done) * 100, 1) if done else 0
                ico = sport_emoji(bet.get("league", ""))
                bank_fmt = f"{int(history['bank']):,}".replace(",", " ")
                send_tg(
                    f"{head}\n"
                    f"{ico} <b>{m_ru}</b>\n\n"
                    f"📊 Итоговый счёт: <b>{bet['score']}</b>\n"
                    f"🎯 Исход: <b>{bet['pick']} за {bet['odds']}</b>\n"
                    f"💵 Результат: <b>{prof:+.0f} ₽</b>\n"
                    f"🏦 Банк: <b>{bank_fmt} ₽</b> • Проход: <b>{wr}%</b>"
                )
                upd = True
        except Exception:
            pass
    return history, rules, upd
def find_matches(history, rules, mkt_txt, exact_map):
    if not mkt_txt or not exact_map:
        return history, False
    taken = {b["match"] for b in history["bets"]}
    taken_orig = {b.get("orig_match", "") for b in history["bets"] if b.get("orig_match")}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    tom_str = (NOW_TLT + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    s1 = web_search(f"прогнозы обе забьют индивидуальный тотал ТБ ТМ {d_str} {tom_str} футбол хоккей баскетбол волейбол гандбол бейсбол")
    s2 = web_search(f"Counter-Strike CS2 Dota 2 League of Legends прогнозы тотал фора {d_str} {tom_str}")
    prompt = (
        f"Ты опытный квантовый аналитик ставок. Пиши СТРОГО на русском языке.\n"
        f"Текущее время: {d_str} {t_str}. Правила:\n{rules}\n\n{mkt_txt}\n\n"
        f"НОВОСТИ И ПРОГНОЗЫ:\n{s1}\n{s2}\n\n"
        f"Найди 2–5 лучших ставок из линии Pinnacle (прематч на ближайшие 4 часа от {t_str} и стабильный [LIVE] в перерыве/паузе между картами/при раннем отставании фаворита; исключи взятые: {list(taken)}):\n"
        f"• РАБОТАЕМ ТОЛЬКО ПО 9 ДИСЦИПЛИНАМ: Баскетбол, Бейсбол, Волейбол, Гандбол, Counter-Strike, Dota 2, League of Legends, Футбол, Хоккей.\n"
        f"• ПРИОРИТЕТ КАЧЕСТВА: выбирай только нормальные профессиональные турниры с хорошей статистикой; избегай глухих экзотических лиг. Кэфы 1.60–2.45, шанс захода от 53%, перевес от +3.5%.\n"
        f"• ЖЁСТКОЕ ПРАВИЛО ПО РЫНКАМ: в поле pick скопируй ТОЧНУЮ формулировку в кавычках из строки Рынки выбранного матча (например: «Ф1 (-1.5) (с ОТ)», «Победа К1 (с ОТ)», «ТБ (5.5) (осн. время)», «П2»), а в поле match_id вставь числовой ID из [ID:...]. Запрещено менять знак форы или пометку ОТ!\n"
        f"• ПЕРЕВЕДИ НА РУССКИЙ ВСЁ: команды (match) и вид спорта с лигой (league, напр. «Хоккей • Россия, ВХЛ»). Никаких английских слов!\n"
        f"Верни СТРОГО JSON-массив: [{{\"match_id\": 123456, \"match\": \"Команда 1 — Команда 2\", \"league\": \"Вид спорта • Лига\", \"pick\": \"Точная ставка из кавычек\", \"prob\": 0.57}}]."
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
            mid = int(c.get("match_id", 0))
            pick_exact = str(c.get("pick", "")).strip().strip("«»\"")
            m_name = str(c.get("match", "")).strip()
            if not m_name or m_name in taken or (mid, pick_exact) not in exact_map:
                continue
            odds, orig_pair, start_iso, is_live, sc_val = exact_map[(mid, pick_exact)]
            if orig_pair in taken_orig or not (1.58 <= odds <= 2.45):
                continue
            raw_prob = float(c["prob"])
            mkt_prob = 1.0 / odds
            prob = round(raw_prob * 0.75 + mkt_prob * 0.25, 3)
            ev = calc_ev(prob, odds)
            if prob < 0.53 or ev < 3.5:
                print(f"Отсеян фильтром 53%: {m_name} | {pick_exact} @ {odds} (шанс {prob*100:.1f}%, перевес {ev}%)")
                continue
            mode_tag = "LIVE" if is_live else "PRE"
            print(f"Принят моделью [{mode_tag}]: {m_name} | {pick_exact} @ {odds} | шанс={prob*100:.1f}% -> перевес={ev}%")
            fair_odds = round(1.0 / prob, 2)
            min_odds = round(1.03 / prob, 2)
            rel = "Высокая (3/3)" if (ev >= 6.5 and prob >= 0.55) else "Хорошая (2/3)"
            st = datetime.datetime.fromisoformat(start_iso)
            lg_str = c.get("league", "")
            ico = sport_emoji(lg_str)
            sc_part = f" • счёт {sc_val}" if sc_val else ""
            time_line = f"🔴 <b>LIVE • Идёт матч</b> <i>(старт {st.strftime('%H:%M')}{sc_part})</i>" if is_live else f"⏰ {st.strftime('%d.%m.%Y • %H:%M')}"
            history["bets"].append({"match": m_name, "orig_match": orig_pair, "league": lg_str, "start_iso": st.isoformat(), "is_live": is_live, "pick": pick_exact, "odds": odds, "prob": prob, "ev": ev, "stake_rub": 500, "status": "PENDING", "score": ""})
            send_tg(
                f"{ico} <b>{lg_str}</b>\n"
                f"🆚 <b>{m_name}</b>\n"
                f"{time_line}\n\n"
                f"✅ Исход: <b>{pick_exact}</b>\n"
                f"📈 Кэф в линии: <b>{odds:.2f}</b> <i>(честный: {fair_odds:.2f} | в Фонбете от {min_odds:.2f})</i>\n"
                f"🔥 Перевес над линией: <b>+{ev:.1f}%</b> • Шанс захода: <b>{prob*100:.0f}%</b>\n"
                f"⭐️ Надёжность: <b>{rel}</b>"
            )
            taken.add(m_name)
            taken_orig.add(orig_pair)
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
    rep_sent = send_daily_report(history)
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    now_ts, scan_ran = NOW_TLT.timestamp(), False
    do_pre = is_manual or (now_ts - history.get("last_scan_ts", 0) >= 840)
    if do_pre:
        history["last_scan_ts"], scan_ran = now_ts, True
    mkt_txt, exact_map = get_all_sources(include_prematch=do_pre)
    history, u2 = find_matches(history, rules, mkt_txt, exact_map)
    pin_upd = update_pinned_stats(history)
    if u1 or u2 or rep_sent or pin_upd or scan_ran:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%d.%m.%Y %H:%M')})</b>\nПрематч и лайв проверены. Новых матчей с перевесом пока нет.")
    print(f"Готово ({NOW_TLT.strftime('%d.%m.%Y %H:%M')}). Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
