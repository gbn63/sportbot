import os, re, html, json, time, datetime, requests, warnings
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
        return r.status_code == 200
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
        sp_stats.setdefault(sp, {"w": 0, "t": 0})
        sp_stats[sp]["t"] += 1
        if b["status"] == "WIN":
            sp_stats[sp]["w"] += 1
    top_sp = "сбор данных"
    if sp_stats:
        best_sp, best_data = max(sp_stats.items(), key=lambda x: (x[1]["w"] / x[1]["t"], x[1]["t"]))
        top_sp = f"{best_sp} ({round(best_data['w'] / best_data['t'] * 100)}%)"
    bank_fmt = f"{int(history['bank']):,}".replace(",", " ")
    text = (
        f"📊 <b>ОТЧЁТ КАНАЛА</b>\n\n<b>Финансы:</b>\n"
        f"💰 Банк: <b>{bank_fmt} ₽</b> <i>({diff:+.0f} ₽)</i> • ROI: <b>{roi:+.1f}%</b>\n\n<b>Дистанция:</b>\n"
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
        if period == 0: suf = " (с ОТ)"
        elif period == 1: suf = " (осн. время)"
        else: return ""
    elif sid in (4, 3):
        if period != 0: return ""
        suf = " (с ОТ)"
    else:
        if period != 0: return ""
        suf = ""
    if mtype == "moneyline":
        if (sid == 19 and period == 0) or sid in (4, 3):
            return {"home": "Победа К1 (с ОТ)", "away": "Победа К2 (с ОТ)"}.get(des, "")
        base = {"home": "П1", "away": "П2", "draw": "Ничья (Х)"}.get(des, "")
        return f"{base}{suf}" if base else ""
    if mtype == "spread" and points is not None:
        pv = float(points)
        if round(pv * 4) % 2 != 0: return ""
        side = "Ф1" if des == "home" else "Ф2" if des == "away" else ""
        return f"{side} ({pv:+g}){suf}" if side else ""
    if mtype == "total" and points is not None:
        pv = float(points)
        if round(pv * 4) % 2 != 0: return ""
        side = "ТБ" if des == "over" else "ТМ" if des == "under" else ""
        return f"{side} ({pv:g}){suf}" if side else ""
    return ""
def get_pinnacle_feed(include_prematch=True, auto_banned=None, odds_mem=None):
    auto_banned = auto_banned or set()
    odds_mem = odds_mem if odds_mem is not None else {}
    now_ts, pre_found, live_found, pre_bal, live_bal, exact_map = NOW_TLT.timestamp(), 0, 0, [], [], {}
    pin = ".".join(["guest", "api", "arcadia", "pinnacle", "com"])
    sports = [(29, "Футбол"), (19, "Хоккей"), (4, "Баскетбол"), (3, "Бейсбол"), (34, "Волейбол"), (18, "Гандбол"), (12, "Киберспорт")]
    ban_words = ["u18", "u19", "youth", "friendly", "reserves", "юниор", "товар"]
    esports_ok = ["counter-strike", "cs2", "cs:", "dota", "league of legends", "lol"]
    live_sports_ok = {29, 19, 12}

    for sid, sname in sports:
        try:
            rm = requests.get(f"https://{pin}/0.1/sports/{sid}/matchups?brandId=0", headers=HEADERS, timeout=8)
            if rm.status_code != 200: continue
            mk_list = []
            rp_pre = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
            if rp_pre.status_code == 200: mk_list.extend(rp_pre.json())
            if sid in live_sports_ok:
                rp_live = requests.get(f"https://{pin}/0.1/sports/{sid}/markets/live/straight?primaryOnly=true&withSpecials=false", headers=HEADERS, timeout=8)
                if rp_live.status_code == 200: mk_list.extend(rp_live.json())

            m_map, raw_pair, is_live_map = {}, {}, {}
            for m in rm.json():
                st_iso = (m.get("startTime") or "").replace("Z", "+00:00")
                parts = m.get("participants", [])
                lg = m.get("league", {}).get("name", "")
                lg_low = lg.lower()
                if not st_iso or len(parts) < 2 or any(w in lg_low for w in ban_words) or lg in auto_banned: continue
                if sid == 12 and not any(k in lg_low for k in esports_ok): continue
                st_dt = datetime.datetime.fromisoformat(st_iso).astimezone(NOW_TLT.tzinfo)
                diff_min = (st_dt.timestamp() - now_ts) / 60.0
                live_flag = bool(m.get("isLive") or m.get("liveMode") == "live" or (-115 <= diff_min < 0))
                home = next((x.get("name") for x in parts if x.get("alignment") == "home"), next(iter(parts)).get("name", ""))
                away = next((x.get("name") for x in parts if x.get("alignment") == "away"), parts[-1].get("name", ""))
                if live_flag and sid in live_sports_ok and -115 <= diff_min <= 2:
                    st_state = m.get("state", {})
                    sc_txt = f" | Счёт: {st_state.get('homeScore', '?')}:{st_state.get('awayScore', '?')}" if "homeScore" in st_state else ""
                    m_map[m["id"]] = f"[LIVE] [ID:{m['id']}] [Старт {st_dt.strftime('%H:%M')}] {sname} ({lg}): К1={home} — К2={away}{sc_txt}"
                    raw_pair[m["id"]] = (f"{home} — {away}", st_dt.isoformat(), lg)
                    is_live_map[m["id"]] = True
                elif include_prematch and not live_flag and 10 <= diff_min <= 240:
                    m_map[m["id"]] = f"[PRE] [ID:{m['id']}] [{st_dt.strftime('%d.%m %H:%M')}] {sname} ({lg}): К1={home} — К2={away}"
                    raw_pair[m["id"]] = (f"{home} — {away}", st_dt.isoformat(), lg)
                    is_live_map[m["id"]] = False

            odds_map, good_map, steam_score = {}, {}, {}
            for mk in mk_list:
                mid = mk.get("matchupId")
                if mid not in m_map: continue
                per, mtype = mk.get("period", -1), mk.get("type", "")
                raw_prices = [(format_pin_pick(sid, per, mtype, pr.get("designation", ""), pr.get("points")), am_to_dec(pr.get("price", 0))) for pr in mk.get("prices", [])]
                raw_prices = [(l, d) for l, d in raw_prices if d > 1.01 and l]
                if not raw_prices: continue
                imp_sum = sum(1.0 / d for _, d in raw_prices)
                plist = []
                for label, dec in raw_prices:
                    true_p = round((1.0 / dec) / imp_sum, 4) if imp_sum > 0 else round(1.0 / dec, 4)
                    t_key = f"{mid}_{label}"
                    if t_key not in odds_mem: odds_mem[t_key] = dec
                    open_d = float(odds_mem[t_key])
                    drop_pct = round((open_d - dec) / open_d * 100, 1) if open_d > 0 else 0.0
                    anom_tag = f" [⚠️322/ОБВАЛ -{drop_pct}%]" if drop_pct >= 18.0 else (f" [🔥ПРОГРУЗ -{drop_pct}% с {open_d}]" if drop_pct >= 4.0 else (f" [⬆️РОСТ +{abs(drop_pct)}%]" if drop_pct <= -4.5 else ""))
                    if drop_pct >= 4.0: steam_score[mid] = steam_score.get(mid, 0) + 1
                    if 1.60 <= dec <= 2.45: good_map[mid] = True
                    plist.append(f"«{label}»={dec} (без маржи {true_p*100:.1f}%){anom_tag}")
                    pair_str, st_iso_str, raw_lg = raw_pair[mid]
                    sc_val = m_map[mid].split("Счёт: ")[-1] if "Счёт: " in m_map[mid] else ""
                    exact_map[(mid, label)] = (dec, pair_str, st_iso_str, is_live_map[mid], sc_val, raw_lg, true_p, open_d, drop_pct)
                if plist: odds_map.setdefault(mid, []).append(", ".join(plist))

            sp_pre, sp_live = [], []
            for mid in sorted(m_map.keys(), key=lambda x: steam_score.get(x, 0), reverse=True):
                if mid in odds_map:
                    if is_live_map[mid]:
                        live_found += 1
                        if mid in good_map: sp_live.append(f"{m_map[mid]} | Рынки: {' ; '.join(odds_map[mid][:4])}")
                    else:
                        pre_found += 1
                        if mid in good_map: sp_pre.append(f"{m_map[mid]} | Рынки: {' ; '.join(odds_map[mid][:4])}")
            pre_bal.extend(sp_pre[:5])
            live_bal.extend(sp_live[:3])
        except Exception:
            pass
    print(f"Pinnacle: Прематч {pre_found} (отбор {len(pre_bal)}), Лайв {live_found} (отбор {len(live_bal)}), авто-бан лиг: {len(auto_banned)}")
    return "\n".join(live_bal[:12] + pre_bal[:22]), exact_map
def get_soft_books_consensus():
    o_key = os.environ.get("ODDS_API_KEY", "").strip()
    if not o_key: return ""
    try:
        o_host = ".".join(["api", "the-odds-api", "com"])
        r = requests.get(f"https://{o_host}/v4/sports/upcoming/odds/?apiKey={o_key}&regions=eu,au&markets=h2h&oddsFormat=decimal", timeout=8)
        if r.status_code != 200: return ""
        diffs = []
        for ev in r.json()[:25]:
            bms = ev.get("bookmakers", [])
            pin_bm = next((b for b in bms if b.get("key") == "pinnacle"), None)
            soft_bms = [b for b in bms if b.get("key") != "pinnacle"]
            if not pin_bm or len(soft_bms) < 2: continue
            pin_out = {o["name"]: float(o["price"]) for o in next(iter(pin_bm.get("markets", [])), {}).get("outcomes", [])}
            for name, p_odd in pin_out.items():
                s_odds = [float(o["price"]) for sb in soft_bms for o in next(iter(sb.get("markets", [])), {}).get("outcomes", []) if o["name"] == name]
                if s_odds:
                    avg_soft = round(sum(s_odds) / len(s_odds), 2)
                    if avg_soft - p_odd >= 0.08 and 1.60 <= p_odd <= 2.45:
                        diffs.append(f"- {ev.get('home_team')} — {ev.get('away_team')}: киты грузят {name} (Pinnacle {p_odd} против мягких БК {avg_soft})")
        return "\n".join(diffs[:10])
    except Exception:
        return ""

def get_all_sources(include_prematch=True, auto_banned=None, odds_mem=None):
    out = []
    pin_txt, exact_map = get_pinnacle_feed(include_prematch=include_prematch, auto_banned=auto_banned, odds_mem=odds_mem)
    if pin_txt: out.append("=== ЛИНИЯ PINNACLE (БЕЗ МАРЖИ, STEAM-ПРОГРУЗЫ И 322) ===\n" + pin_txt)
    if include_prematch:
        soft_txt = get_soft_books_consensus()
        if soft_txt: out.append("=== СВЕРКА ОСТРЫХ И МЯГКИХ БК ===\n" + soft_txt)
        pm_list, pm_host = [], ".".join(["gamma-api", "polymarket", "com"])
        allow_pm = ("soccer", "football", "nba", "basketball", "nhl", "hockey", "mlb", "baseball", "volleyball", "handball", "counter-strike", "cs2", "dota", "league of legends", "lol")
        for tag in ["sports", "esports"]:
            try:
                r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug={tag}&limit=35", headers=HEADERS, timeout=10)
                if r.status_code == 200:
                    for ev in r.json():
                        if not any(k in (ev.get("title", "") + " " + ev.get("slug", "")).lower() for k in allow_pm): continue
                        vol = float(ev.get("volume24hr") or ev.get("volume") or 0)
                        vol_tag = f" [КИТЫ: ${int(vol):,}]" if vol >= 10000 else (f" [Объём: ${int(vol):,}]" if vol > 500 else "")
                        for m in ev.get("markets", [])[:2]:
                            q = m.get("question", ev.get("title", ""))
                            oc = json.loads(m.get("outcomes", "[]")) if isinstance(m.get("outcomes"), str) else m.get("outcomes", [])
                            pr = json.loads(m.get("outcomePrices", "[]")) if isinstance(m.get("outcomePrices"), str) else m.get("outcomePrices", [])
                            if q and len(oc) == len(pr) and pr:
                                line = f"- [{tag}]{vol_tag} {q} -> " + ", ".join([f"{o}: {round(float(p)*100, 1)}%" for o, p in zip(oc, pr)])
                                if line not in pm_list: pm_list.append(line)
            except Exception:
                pass
        print(f"Polymarket (киты и объёмы): {len(pm_list)} рынков")
        if pm_list: out.append("=== POLYMARKET (ДЕНЬГИ КИТОВ) ===\n" + "\n".join(pm_list[:15]))
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
                    models = sorted([x["id"] for x in mr.json().get("data", []) if not any(b in x["id"].lower() for b in bad)], key=lambda s: (0 if "120b" in s else 1 if "70b" in s else 2 if any(k in s for k in ("32b", "27b", "20b")) else 3))
                    for gm in models:
                        try:
                            r = requests.post(f"{g_base}/chat/completions", headers=hdr, json={"model": gm, "messages": [{"role": "user", "content": cur_prompt}], "temperature": 0.2}, timeout=20)
                            if r.status_code == 200:
                                txt = next(iter(r.json()["choices"]))["message"]["content"]
                                if "{" in txt or "[" in txt:
                                    print(f"ИИ (круг {circle}, Groq {gm}) ответил: {len(txt)} симв.")
                                    return txt
                        except Exception: continue
            except Exception: pass
        g_list = ["gemma-3-27b-it", "gemini-2.5-flash", "gemini-2.0-flash", "gemma-3-12b-it", "gemma-3-4b-it"]
        try:
            mr = requests.get(f"{GEM_HOST}/v1beta/models?key={GEMINI_API_KEY}", timeout=8)
            if mr.status_code == 200:
                skip = ("embed", "imagen", "veo", "aqa", "tts", "robotics", "computer", "research", "lite", "exp", "preview", "pro")
                for m in mr.json().get("models", []):
                    nm = m["name"].replace("models/", "")
                    if "generateContent" in m.get("supportedGenerationMethods", []) and not any(s in nm.lower() for s in skip) and nm not in g_list: g_list.append(nm)
        except Exception: pass
        for gm in g_list:
            try:
                r = requests.post(f"{GEM_HOST}/v1beta/models/{gm}:generateContent?key={GEMINI_API_KEY}", json={"contents": [{"parts": [{"text": cur_prompt}]}], "generationConfig": {"temperature": 0.2}}, timeout=25)
                if r.status_code == 200:
                    txt = next(iter(next(iter(r.json()["candidates"]))["content"]["parts"]))["text"]
                    if "{" in txt or "[" in txt:
                        print(f"ИИ (круг {circle}, Google {gm}) ответил: {len(txt)} симв.")
                        return txt
            except Exception: continue
        p_url = "https://" + ".".join(["text", "pollinations", "ai"]) + "/openai"
        for pm in ["openai", "mistral", "deepseek"]:
            try:
                r = requests.post(p_url, headers={"Content-Type": "application/json"}, json={"model": pm, "messages": [{"role": "user", "content": cur_prompt}], "temperature": 0.2}, timeout=30)
                if r.status_code == 200:
                    txt = next(iter(r.json()["choices"]))["message"]["content"]
                    if "{" in txt or "[" in txt:
                        print(f"ИИ (круг {circle}, Резерв {pm}) ответил: {len(txt)} симв.")
                        return txt
            except Exception: continue
        if circle < 3: time.sleep(10)
    return ""
def calc_ev(prob, odds):
    return round(float(np.mean(np.where(np.random.default_rng().random(100_000) < prob, odds - 1.0, -1.0))) * 100, 2)

def eval_line_diff(diff):
    half_res = lambda x: 1.0 if x > 1e-6 else (-1.0 if x < -1e-6 else 0.0)
    if round(abs(diff) * 4) % 2 == 1:
        return (half_res(diff - 0.25) + half_res(diff + 0.25)) / 2.0
    return half_res(diff)

def settle_bet_math(pick, h_sc, a_sc):
    p = pick.strip()
    if p.startswith(("П1", "Победа К1")): return 1.0 if h_sc > a_sc else -1.0
    if p.startswith(("П2", "Победа К2")): return 1.0 if a_sc > h_sc else -1.0
    if p.startswith("Ничья"): return 1.0 if h_sc == a_sc else -1.0
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)\)", p)
    if m:
        val = float(m.group(1))
        if p.startswith("Ф1"): return eval_line_diff((h_sc - a_sc) + val)
        if p.startswith("Ф2"): return eval_line_diff((a_sc - h_sc) + val)
        if p.startswith("ТБ"): return eval_line_diff((h_sc + a_sc) - val)
        if p.startswith("ТМ"): return eval_line_diff(val - (h_sc + a_sc))
    return None

def get_all_live_scores():
    espn, out = ".".join(["site", "api", "espn", "com"]), []
    for p in ["soccer/all/scoreboard", "hockey/nhl/scoreboard", "basketball/nba/scoreboard", "baseball/mlb/scoreboard"]:
        try:
            r = requests.get(f"https://{espn}/apis/site/v2/sports/{p}", headers=HEADERS, timeout=8)
            if r.status_code == 200:
                for ev in r.json().get("events", []):
                    st_det = ev.get("status", {}).get("type", {}).get("shortDetail", "")
                    comp = next(iter(ev.get("competitions", [])), {})
                    sc = " : ".join([f"{c.get('team', {}).get('displayName', '')} ({c.get('score', '0')})" for c in comp.get("competitors", [])])
                    if sc: out.append(f"{sc} | Статус: {st_det}".strip())
        except Exception: pass
    try:
        sdb = ".".join(["www", "thesportsdb", "com"])
        r = requests.get(f"https://{sdb}/api/v1/json/3/eventsday.php?d={NOW_TLT.strftime('%Y-%m-%d')}", headers=HEADERS, timeout=8)
        if r.status_code == 200 and r.json().get("events"):
            for e in r.json()["events"][:40]:
                if e.get("intHomeScore") is not None:
                    out.append(f"{e.get('strHomeTeam')} ({e.get('intHomeScore')}) : {e.get('strAwayTeam')} ({e.get('intAwayScore')}) | Статус: {e.get('strStatus', '')}")
    except Exception: pass
    return "\n".join(out)

def check_results(history, rules):
    upd, live_board = False, get_all_live_scores()
    for bet in history["bets"]:
        if bet["status"] != "PENDING": continue
        st = datetime.datetime.fromisoformat(bet["start_iso"])
        if (NOW_TLT - st).total_seconds() / 3600.0 < 2.2: continue
        q_name = bet.get("orig_match") or bet["match"]
        info = web_search(f"{bet['match']} {q_name} финальный счет результат FT Final {st.strftime('%d.%m.%Y')}")
        raw = ask_ai(
            f"Проверь, ЗАВЕРШЁН ли матч окончательно. Матч: {bet['match']} ({q_name}). Ставка: {bet['pick']}.\nТабло:\n{live_board}\nПоиск:\n{info}\n"
            f"1. Если матч не завершён (нет Final / FT) — finished: false. 2. Учти (с ОТ) или (осн. время). 3. В lesson напиши 1 тактическое правило для этой лиги/рынка (не пересказывай счёт).\n"
            f"Верни JSON: {{\"finished\": true|false, \"home_score\": 2, \"away_score\": 1, \"match_ru\": \"Команда 1 — Команда 2\", \"lesson\": \"вывод\"}}"
        )
        try:
            res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
            if res.get("finished") and res.get("home_score") is not None and res.get("away_score") is not None:
                h_sc, a_sc = int(res["home_score"]), int(res["away_score"])
                mult = settle_bet_math(bet["pick"], h_sc, a_sc)
                if mult is None: continue
                m_ru = str(res.get("match_ru") or bet["match"]).strip()
                bet["match"], bet["score"] = m_ru, f"{h_sc} : {a_sc}"
                stake = bet.get("stake_rub", 500)
                if mult > 0: bet["status"], prof, head = "WIN", round(stake * (bet["odds"] - 1.0) * mult, 0), "✅ <b>СТАВКА ЗАШЛА</b>"
                elif mult == 0: bet["status"], prof, head = "VOID", 0, "🔄 <b>ВОЗВРАТ СТАВКИ</b>"
                else: bet["status"], prof, head = "LOSE", round(stake * mult, 0), "❌ <b>СТАВКА НЕ ЗАШЛА</b>"
                history["bank"] = round(history["bank"] + prof, 0)
                lesson = str(res.get("lesson", "")).strip()
                if bet["status"] in ("WIN", "LOSE") and lesson and len(lesson) > 15:
                    tag = "Плюс-паттерн" if bet["status"] == "WIN" else "Ошибка"
                    rules += f"\n- Вывод [{tag}] ({NOW_TLT.strftime('%d.%m')}): {lesson}"
                    base_l = [l for l in rules.splitlines() if not l.startswith("- Вывод [")]
                    learn_l = [l for l in rules.splitlines() if l.startswith("- Вывод [")][-15:]
                    rules = "\n".join(base_l + learn_l)
                done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                wr = round(len([b for b in done if b["status"] == "WIN"]) / len(done) * 100, 1) if done else 0
                bank_fmt = f"{int(history['bank']):,}".replace(",", " ")
                send_tg(f"{head}\n{sport_emoji(bet.get('league', ''))} <b>{m_ru}</b>\n\n📊 Итоговый счёт: <b>{bet['score']}</b>\n🎯 Исход: <b>{bet['pick']} за {bet['odds']}</b>\n💵 Результат: <b>{prof:+.0f} ₽</b>\n🏦 Банк: <b>{bank_fmt} ₽</b> • Проход: <b>{wr}%</b>")
                upd = True
        except Exception: pass
    return history, rules, upd
def build_league_memory(history):
    lg_stats = {}
    for b in history["bets"]:
        st = b.get("status")
        if st not in ("WIN", "LOSE"): continue
        lg_key = b.get("orig_league") or b.get("league", "")
        if not lg_key: continue
        lg_stats.setdefault(lg_key, {"w": 0, "l": 0})
        lg_stats[lg_key]["w" if st == "WIN" else "l"] += 1
    banned, lines = set(), []
    for lg_name, d in lg_stats.items():
        tot = d["w"] + d["l"]
        wr = round(d["w"] / tot * 100)
        if (d["l"] >= 2 and d["w"] == 0) or (tot >= 4 and wr < 35):
            banned.add(lg_name)
            lines.append(f"- [АВТО-БАН] {lg_name}: {d['w']}W / {d['l']}L ({wr}%)")
        elif tot >= 2:
            lines.append(f"- [ОПЫТ] {lg_name}: {d['w']}W / {d['l']}L ({wr}%)")
    return banned, "\n".join(lines)

def verify_candidate(orig_pair, m_name, league, pick, odds, init_prob, line_move_txt):
    y_cur = NOW_TLT.year
    h2h_info = web_search(f"{orig_pair} {m_name} личные встречи H2H результаты {y_cur-1} {y_cur}", n=5)
    form_info = web_search(f"{orig_pair} {m_name} последние матчи форма травмы {NOW_TLT.strftime('%B %Y')}", n=5)
    fix_info = web_search(f"{orig_pair} 322 договорной матч match fixing", n=3)
    prompt = (
        f"Ты риск-менеджер синдиката. Проверь и попытайся опровергнуть ставку: {m_name} ({orig_pair}) | Лига: {league} | «{pick}» @ {odds} (шанс {init_prob*100:.1f}%).\n"
        f"Линия Pinnacle: {line_move_txt}\nH2H за год:\n{h2h_info}\nФорма за месяц:\n{form_info}\n322/Аномалии:\n{fix_info}\n"
        f"Отклони (approve: false), если: 1) нет статистики по турниру/командам; 2) H2H за год или форма за месяц против ставки; 3) признаки 322 или рост кэфа против нас.\n"
        f"Верни JSON: {{\"approve\": true|false, \"final_prob\": 0.57, \"reason\": \"1 короткое предложение\"}}"
    )
    raw = ask_ai(prompt)
    try:
        res = json.loads(raw[raw.find("{"):raw.rfind("}")+1])
        return bool(res.get("approve")), float(res.get("final_prob", 0)), str(res.get("reason", ""))
    except Exception:
        return False, 0.0, "Ошибка ответа критика"

def find_matches(history, rules, mkt_txt, exact_map, league_mem=""):
    if not mkt_txt or not exact_map: return history, False
    taken = {b["match"] for b in history["bets"]}
    taken_orig = {b.get("orig_match", "") for b in history["bets"] if b.get("orig_match")}
    d_str, t_str = NOW_TLT.strftime("%d.%m.%Y"), NOW_TLT.strftime("%H:%M")
    tom_str = (NOW_TLT + datetime.timedelta(days=1)).strftime("%d.%m.%Y")
    q_teams = " ".join(list({v[1] for v in exact_map.values()})[:3])
    s1 = web_search(f"{q_teams} статистика форма прогноз {d_str} {tom_str}", n=5)
    mem_block = f"\nДОСЬЕ ЛИГ:\n{league_mem}\n" if league_mem else ""
    prompt = (
        f"Ты квантовый аналитик синдиката. Пиши на русском. Время: {d_str} {t_str}.\nПравила:\n{rules}\n{mem_block}\n{mkt_txt}\n\nФорма:\n{s1}\n\n"
        f"Отбери 0–4 лучших кандидата (прематч 4ч от {t_str} и стабильный [LIVE]; исключи: {list(taken)}) по 9 дисциплинам (Баскетбол, Бейсбол, Волейбол, Гандбол, CS2, Dota 2, LoL, Футбол, Хоккей), кэфы 1.60–2.45.\n"
        f"Ищи [🔥ПРОГРУЗ], перекос с мягкими БК и китов Polymarket; избегай [⚠️322/ОБВАЛ] и глухих лиг без статистики. В pick скопируй ТОЧНУЮ фразу в кавычках из Рынки, в match_id — число из [ID:...]. Переведи команды и лигу на русский.\n"
        f"Верни JSON-массив: [{{\"match_id\": 123456, \"match\": \"Команда 1 — Команда 2\", \"league\": \"Вид спорта • Лига\", \"pick\": \"Точная ставка\", \"prob\": 0.58}}]."
    )
    raw = ask_ai(prompt)
    try: cands = json.loads(raw[raw.find("["):raw.rfind("]")+1])
    except Exception as e:
        print("JSON parse err:", e, raw[:120])
        return history, False
    upd = False
    for c in cands[:4]:
        try:
            mid, pick_exact, m_name = int(c.get("match_id", 0)), str(c.get("pick", "")).strip().strip("«»\""), str(c.get("match", "")).strip()
            if not m_name or m_name in taken or (mid, pick_exact) not in exact_map: continue
            odds, orig_pair, start_iso, is_live, sc_val, raw_lg, true_p, open_d, drop_pct = exact_map[(mid, pick_exact)]
            if orig_pair in taken_orig or not (1.58 <= odds <= 2.45) or drop_pct <= -4.5 or drop_pct >= 20.0: continue
            line_move = f"прогруз -{drop_pct}% (с {open_d} до {odds}), без маржи {true_p*100:.1f}%" if drop_pct >= 3.5 else f"стабилен ({odds}), без маржи {true_p*100:.1f}%"
            init_prob = round(float(c["prob"]) * 0.70 + true_p * 0.30, 3)
            if init_prob < 0.52: continue
            approved, crit_prob, reason = verify_candidate(orig_pair, m_name, c.get("league", ""), pick_exact, odds, init_prob, line_move)
            final_prob = round(crit_prob * 0.75 + true_p * 0.25 + (0.015 if drop_pct >= 4.0 else 0.0), 3)
            ev = calc_ev(final_prob, odds)
            if not approved or final_prob < 0.55 or ev < 4.5:
                print(f"Критик отклонил: {m_name} | {pick_exact} @ {odds} (шанс {final_prob*100:.1f}%, EV {ev}%) -> {reason}")
                continue
            print(f"Одобрено критиком [{'LIVE' if is_live else 'PRE'}]: {m_name} | {pick_exact} @ {odds} | шанс={final_prob*100:.1f}% -> EV={ev}% ({reason})")
            fair_odds, min_odds = round(1.0 / final_prob, 2), round(1.03 / final_prob, 2)
            rel = "Высокая (3/3)" if (ev >= 7.0 and final_prob >= 0.57) else "Хорошая (2/3)"
            st, lg_str = datetime.datetime.fromisoformat(start_iso), c.get("league", "")
            sc_part = f" • счёт {sc_val}" if sc_val else ""
            time_line = f"🔴 <b>LIVE • Идёт матч</b> <i>(старт {st.strftime('%H:%M')}{sc_part})</i>" if is_live else f"⏰ {st.strftime('%d.%m.%Y • %H:%M')}"
            history["bets"].append({"match": m_name, "orig_match": orig_pair, "league": lg_str, "orig_league": raw_lg, "start_iso": st.isoformat(), "is_live": is_live, "pick": pick_exact, "odds": odds, "prob": final_prob, "ev": ev, "stake_rub": 500, "status": "PENDING", "score": ""})
            send_tg(f"{sport_emoji(lg_str)} <b>{lg_str}</b>\n🆚 <b>{m_name}</b>\n{time_line}\n\n✅ Исход: <b>{pick_exact}</b>\n📈 Кэф в линии: <b>{odds:.2f}</b> <i>(честный: {fair_odds:.2f} | в Фонбете от {min_odds:.2f})</i>\n🔥 Перевес над линией: <b>+{ev:.1f}%</b> • Шанс захода: <b>{final_prob*100:.0f}%</b>\n⭐️ Надёжность: <b>{rel}</b>")
            taken.add(m_name); taken_orig.add(orig_pair); upd = True
        except Exception: continue
    return history, upd
def send_daily_report(history):
    today_str = NOW_TLT.strftime("%Y-%m-%d")
    if NOW_TLT.hour == 9 and history.get("last_report") != today_str:
        done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
        wins = len([b for b in done if b["status"] == "WIN"])
        pend = len([b for b in history["bets"] if b["status"] == "PENDING"])
        wr = round(wins / len(done) * 100, 1) if done else 0
        diff = history["bank"] - 10000
        send_tg(f"☀️ <b>УТРЕННЯЯ СВОДКА ({NOW_TLT.strftime('%d.%m.%Y')})</b>\n💰 Текущий банк: <b>{history['bank']:.0f} ₽</b> ({diff:+.0f} ₽)\n📈 Проход: <b>{wr}%</b> ({wins} из {len(done)} завершённых)\n⏳ Активных ставок в игре: <b>{pend}</b>")
        history["last_report"] = today_str
        return True
    return False

def generate_web_table(history):
    done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
    wins, losses = len([b for b in done if b["status"] == "WIN"]), len([b for b in done if b["status"] == "LOSE"])
    wr = round(wins / len(done) * 100, 1) if done else 0.0
    diff, staked = history["bank"] - 10000, sum(b.get("stake_rub", 500) for b in done)
    roi = round((diff / staked) * 100, 1) if staked > 0 else 0.0
    rows = []
    for b in reversed(history["bets"]):
        st, stake, odds = b.get("status", "PENDING"), b.get("stake_rub", 500), float(b.get("odds", 0))
        if st == "WIN": badge, cls, prof = "✅ Зашла", "win", f"+{round(stake * (odds - 1.0)):.0f} ₽"
        elif st == "LOSE": badge, cls, prof = "❌ Минус", "lose", f"-{stake:.0f} ₽"
        elif st == "VOID": badge, cls, prof = "🔄 Возврат", "void", "0 ₽"
        else: badge, cls, prof = "⏳ В игре", "pend", "—"
        dt_txt = b.get("start_iso", "")[:16].replace("T", " ")
        lg, mt, pk, sc = html.escape(b.get("league", "")), html.escape(b.get("match", "")), html.escape(b.get("pick", "")), html.escape(b.get("score", "") or "—")
        rows.append(f"<tr data-st='{st}'><td>{dt_txt}</td><td>{lg}</td><td><b>{mt}</b></td><td>{pk}</td><td><b>{odds:.2f}</b></td><td>{sc}</td><td class='{cls}'>{badge}</td><td class='{cls}'><b>{prof}</b></td></tr>")
    page = f"<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Статистика канала</title><style>body{{font-family:system-ui,sans-serif;background:#0b1120;color:#e2e8f0;margin:0;padding:20px}}.wrap{{max-width:1100px;margin:0 auto}}h1{{font-size:20px;margin:0 0 16px}}.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:18px}}.card{{background:#1e293b;padding:14px;border-radius:12px;border:1px solid #334155}}.card span{{font-size:12px;color:#94a3b8;display:block}}.card b{{font-size:20px;margin-top:4px;display:block}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}}button{{background:#1e293b;color:#e2e8f0;border:1px solid #334155;padding:7px 12px;border-radius:8px;cursor:pointer}}button.act{{background:#2563eb;border-color:#2563eb}}.tbl{{overflow-x:auto;background:#1e293b;border-radius:12px;border:1px solid #334155}}table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid #334155}}th{{color:#94a3b8;background:#162032}}.win{{color:#4ade80}}.lose{{color:#f87171}}.pend{{color:#fbbf24}}.void{{color:#94a3b8}}</style></head><body><div class='wrap'><h1>📊 Журнал сигналов (обновлено {NOW_TLT.strftime('%d.%m.%Y %H:%M')})</h1><div class='cards'><div class='card'><span>Банк</span><b>{int(history['bank']):,} ₽</b></div><div class='card'><span>Профит</span><b>{diff:+.0f} ₽</b></div><div class='card'><span>ROI</span><b>{roi:+.1f}%</b></div><div class='card'><span>Винрейт</span><b>{wr}% ({wins}/{losses})</b></div></div><div class='filters'><button class='act' onclick=\"flt('ALL',this)\">Все</button><button onclick=\"flt('WIN',this)\">✅ Зашли</button><button onclick=\"flt('LOSE',this)\">❌ Минус</button><button onclick=\"flt('PENDING',this)\">⏳ В игре</button></div><div class='tbl'><table><thead><tr><th>Время</th><th>Лига</th><th>Матч</th><th>Исход</th><th>Кэф</th><th>Счёт</th><th>Статус</th><th>Итог</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></div><script>function flt(s,b){{document.querySelectorAll('button').forEach(x=>x.classList.remove('act'));b.classList.add('act');document.querySelectorAll('tbody tr').forEach(r=>{{r.style.display=(s==='ALL'||r.dataset.st===s)?'':'none'}})}}</script></body></html>"
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(page)

def main():
    with open("history.json", "r", encoding="utf-8") as f: history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f: rules = f.read()
    history, rules, u1 = check_results(history, rules)
    rep_sent = send_daily_report(history)
    auto_banned, league_mem = build_league_memory(history)
    odds_mem = history.setdefault("odds_tracker", {})
    is_manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    now_ts, scan_ran = NOW_TLT.timestamp(), False
    do_pre = is_manual or (now_ts - history.get("last_scan_ts", 0) >= 840)
    if do_pre: history["last_scan_ts"], scan_ran = now_ts, True
    mkt_txt, exact_map = get_all_sources(include_prematch=do_pre, auto_banned=auto_banned, odds_mem=odds_mem)
    history, u2 = find_matches(history, rules, mkt_txt, exact_map, league_mem=league_mem)
    if len(odds_mem) > 600: history["odds_tracker"] = dict(list(odds_mem.items())[-300:])
    pin_upd = update_pinned_stats(history)
    generate_web_table(history)
    if u1 or u2 or rep_sent or pin_upd or scan_ran or not os.path.exists("index.html"):
        with open("history.json", "w", encoding="utf-8") as f: json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f: f.write(rules)
    if is_manual and not (u1 or u2):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%d.%m.%Y %H:%M')})</b>\nПрематч, лайв и прогрузы проверены. Железобетонных ставок пока нет.")
    print(f"Готово ({NOW_TLT.strftime('%d.%m.%Y %H:%M')}). Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
