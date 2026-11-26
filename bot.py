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

def web_search(q, n=6):
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
    now_ts, out = NOW_TLT.timestamp(), []
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
            odds_map = {}
            for mk in rp.json():
                mid = mk.get("matchupId")
                if mid not in m_map or mk.get("period") != 0:
                    continue
                mtype = mk.get("type", "")
                plist = []
                for pr in mk.get("prices", []):
                    dec = am_to_dec(pr.get("price", 0))
                    if dec > 1.01:
                        pt = f"({pr['points']})" if "points" in pr else ""
                        plist.append(f"{pr.get('designation', '')}{pt}={dec}")
                if plist:
                    odds_map.setdefault(mid, []).append(f"{mtype}:[{','.join(plist)}]")
            for mid, title in m_map.items():
                if mid in odds_map:
                    out.append(f"{title} | {' ; '.join(odds_map[mid][:2])}")
        except Exception:
            pass
    print(f"Pinnacle (весь мир): {len(out)} матчей с кэфами")
    return "\n".join(out[:35])
def get_all_sources():
    now_ts, out = NOW_TLT.timestamp(), []
    pin_txt = get_pinnacle_feed()
    if pin_txt:
        out.append("=== ЛИНИЯ PINNACLE (MONEYLINE=1X2, TOTAL=ТОТАЛ, SPREAD=ФОРА) ===\n" + pin_txt)

    pm_list, pm_host = [], ".".join(["gamma-api", "polymarket", "com"])
    for tag in ["sports", "esports"]:
        try:
            r = requests.get(f"https://{pm_host}/events?active=true&closed=false&tag_slug={tag}&limit=30", headers=HEADERS, timeout=10)
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
        out.append("=== POLYMARKET ===\n" + "\n".join(pm_list[:18]))

    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key and ((NOW_TLT.hour * 60 + NOW_TLT.minute) % 120 < 5 or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"):
        try:
            oa_host = ".".join(["api", "the-odds-api", "com"])
            url = f"https://{oa_host}/v4/sports/upcoming/odds/?apiKey={odds_key}&regions=eu&markets=h2h,totals&oddsFormat=decimal"
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                bk_list = []
                for ev in r.json():
                    dt_iso = ev.get("commence_time", "").replace("Z", "+00:00")
                    if not dt_iso:
                        continue
                    st_dt = datetime.datetime.fromisoformat(dt_iso).astimezone(NOW_TLT.tzinfo)
                    if 2 <= (st_dt.timestamp() - now_ts) / 60.0 <= 1440:
                        bms = ev.get("bookmakers", [])
                        if not bms:
                            continue
                        mkt_strs = []
                        for m in next(iter(bms)).get("markets", []):
                            o_str = ", ".join([f"{o['name']}({o.get('point', '')})={o['price']}".replace("()", "") for o in m.get("outcomes", [])])
                            mkt_strs.append(f"{m.get('key', '')}: [{o_str}]")
                        bk_list.append(f"[{st_dt.strftime('%d.%m %H:%M')}] {ev.get('sport_title', '')}: {ev.get('home_team', '')} — {ev.get('away_team', '')} | {' ; '.join(mkt_strs)}")
                print(f"Odds API (1Х2+Тоталы): {len(bk_list)} матчей (остаток: {r.headers.get('x-requests-remaining', '?')})")
                if bk_list:
                    out.append("=== ODDS API ===\n" + "\n".join(bk_list[:20]))
        except Exception as e:
            print("Odds API err:", e)

    return "\n\n".join(out)

def ask_ai(prompt):
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if groq_key:
        g_url = "https://" + ".".join(["api", "groq", "com"]) + "/openai/v1/chat/completions"
        hdr = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
        for gm in ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "meta-llama/llama-4-scout-17b-16e-instruct"]:
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
            f"Счёт: [текущий счёт без минуты]\nДействие: [ДЕРЖАТЬ / ПРОДАТЬ / ПЕРЕКРЫТЬСЯ]\nПричина: [почему нужно так сделать (укажи минуту тут)]"
        ).strip()
        if adv and "OK" not in adv[:15].upper():
            first_line = next(iter(adv.splitlines()), "")
            if bet.get("last_live") != first_line and send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{adv}"):
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
        f"Время ТЛТ (UTC+4): {d_str} {t_str}. Правила:\n{rules}\n\n{mkt}\n\n"
        f"ПОИСК (ОЗ / ИТБ / ТОТАЛЫ / СПОРТ):\n{s1}\n\nПОИСК (КИБЕРСПОРТ / ТЕННИС / БАСКЕТ):\n{s2}\n\n"
        f"Перед тобой больше 200 матчей из Pinnacle, Polymarket, Odds API и поиска на ближайшие 16 часов от {t_str} (исключи уже взятые: {list(taken)}).\n"
        f"Твоя задача как профессионального аналитика — НЕ отписываться пустым списком, а найти 2–6 лучших валуйных ставок и «обраток» (на кэфах 1.75–3.50) с реальным перевесом +EV >= 4.5%.\n"
        f"Используй ВСЮ роспись: П1/Х/П2, Форы, Общие тоталы (ТБ/ТМ), Индивидуальные тоталы (ИТБ/ИТМ), Обе забьют (ОЗ Да/Нет), тоталы карт/сетов.\n"
        f"Верни СТРОГО JSON-массив: [{{\"match\": \"К1 — К2\", \"league\": \"Лига\", \"start_time\": \"ЧЧ:ММ\", \"type\": \"Обратка или Валуй\", \"pick\": \"Рынок и ставка (напр. ОЗ - Нет, ИТБ1 (1.5), ТМ (2.5), П2)\", \"odds\": 2.15, \"prob\": 0.52, \"reason\": \"Суть перевеса\", \"live_plan\": \"План в лайве\", \"risk\": \"Риск\"}}]."
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
            if ev < 4.5 or rub <= 0:
                continue
            min_odds = round(1.04 / prob, 2) if prob > 0 else odds
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
    if u1 or u2 or live_sent:
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        with open("rules.txt", "w", encoding="utf-8") as f:
            f.write(rules)
    if is_manual and not (u1 or u2 or live_sent):
        send_tg(f"🤖 <b>Система 5.0 MAX на связи ({NOW_TLT.strftime('%H:%M')} ТЛТ)</b>\nВсе мировые источники опрошены. Новых матчей с +EV ≥ 4.5% не найдено.")
    print(f"Готово ({NOW_TLT.strftime('%H:%M')} ТЛТ). Лайв: {live_sent}, Обновлено: {u1 or u2}")

if __name__ == "__main__":
    main()
# КОНЕЦ КОДА
