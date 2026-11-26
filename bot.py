import os
import json
import datetime
import requests
import numpy as np
from openai import OpenAI
from duckduckgo_search import DDGS

TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT_ID = os.environ["TG_CHAT_ID"]
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]

TZ_TLT = datetime.timezone(datetime.timedelta(hours=4))
NOW_TLT = datetime.datetime.now(TZ_TLT)

client = OpenAI(
    base_url="https://openrouter.ai",
    api_key=OPENROUTER_API_KEY,
)

FREE_MODELS = [
    "openrouter/free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "deepseek/deepseek-chat:free",
    "qwen/qwen-2.5-72b-instruct:free",
]

def send_tg(text):
    url = f"https://telegram.org{TG_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"})

def web_search(query, max_results=6):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            return "\n".join([f"- {r['title']}: {r['body']}" for r in results])
    except Exception as e:
        return f"Ошибка поиска: {e}"

def ask_ai(prompt):
    for model in FREE_MODELS:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return resp.choices[0].message.content
        except Exception:
            continue
    return ""

def kelly_stake(prob, odds, bank):
    b = odds - 1.0
    if b <= 0:
        return 0.0, 0.0
    f = (prob * b - (1.0 - prob)) / b
    quarter_kelly = max(0.0, min(0.05, f * 0.25))
    return round(quarter_kelly * 100, 2), round(bank * quarter_kelly, 0)

def load_data():
    with open("history.json", "r", encoding="utf-8") as f:
        history = json.load(f)
    with open("rules.txt", "r", encoding="utf-8") as f:
        rules = f.read()
    return history, rules

def save_data(history, rules):
    with open("history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    with open("rules.txt", "w", encoding="utf-8") as f:
        f.write(rules)

def check_results_and_learn(history, rules):
    updated = False
    for bet in history["bets"]:
        if bet["status"] == "PENDING":
            start_dt = datetime.datetime.fromisoformat(bet["start_iso"])
            hours_passed = (NOW_TLT - start_dt).total_seconds() / 3600.0
            if hours_passed >= 2.8:
                res_info = web_search(f"{bet['match']} результат счет итог матча {start_dt.strftime('%d.%m.%Y')}")
                check_prompt = f"""
                Проверь итог матча по данным поиска.
                Матч: {bet['match']}
                Наша ставка: {bet['pick']} (кэф {bet['odds']})
                Данные из сети:
                {res_info}
                
                Верни СТРОГО JSON без лишнего текста:
                {{"status": "WIN" или "LOSE" или "PENDING", "score": "счет матча", "lesson": "если LOSE — одно короткое правило-патч для rules.txt, почему ошиблись и как не повторить; иначе пустая строка"}}
                """
                raw = ask_ai(check_prompt)
                try:
                    clean = raw[raw.find("{"):raw.rfind("}")+1]
                    parsed = json.loads(clean)
                    if parsed["status"] in ("WIN", "LOSE"):
                        bet["status"] = parsed["status"]
                        bet["score"] = parsed.get("score", "")
                        if parsed["status"] == "WIN":
                            profit = round(bet["stake_rub"] * (bet["odds"] - 1.0), 0)
                            history["bank"] = round(history["bank"] + profit, 0)
                            icon = "✅ ЗАХОД"
                        else:
                            profit = -bet["stake_rub"]
                            history["bank"] = round(history["bank"] + profit, 0)
                            icon = "❌ ПРОИГРЫШ"
                            if parsed.get("lesson"):
                                rules += f"\n- Авто-патч ({NOW_TLT.strftime('%d.%m')}): {parsed['lesson']}"
                        
                        done = [b for b in history["bets"] if b["status"] in ("WIN", "LOSE")]
                        wins = len([b for b in done if b["status"] == "WIN"])
                        wr = round(wins / len(done) * 100, 1) if done else 0
                        
                        msg = (
                            f"{icon} | <b>{bet['match']}</b>\n"
                            f"Счёт: {bet['score']} | Ставка: {bet['pick']} ({bet['odds']})\n"
                            f"Итог: {profit:+.0f} ₽ | Банк: <b>{history['bank']:.0f} ₽</b> (Проход: {wr}%)"
                        )
                        if parsed["status"] == "LOSE" and parsed.get("lesson"):
                            msg += f"\n🧠 <i>Самообучение: {parsed['lesson']}</i>"
                        send_tg(msg)
                        updated = True
                except Exception:
                    continue
    return history, rules, updated

def check_live_bets(history):
    for bet in history["bets"]:
        if bet["status"] == "PENDING":
            start_dt = datetime.datetime.fromisoformat(bet["start_iso"])
            mins_from_start = (NOW_TLT - start_dt).total_seconds() / 60.0
            if 10 <= mins_from_start <= 135:
                live_info = web_search(f"{bet['match']} live счет статистика сейчас")
                live_prompt = f"""
                Матч {bet['match']} сейчас идёт в лайве (прошло ~{int(mins_from_start)} мин).
                Наша ставка: {bet['pick']} за {bet['odds']} (сумма {bet['stake_rub']} ₽).
                Сводка из сети:
                {live_info}
                
                Оцени ситуацию. Если всё идёт по плану — верни слово OK.
                Если всё пошло против плана (красная карточка, провал счёта/драфта) — напиши короткий совет на 3 строки: ДЕРЖАТЬ, ПРОДАТЬ (кэшаут) или ПЕРЕКРЫТЬСЯ (каким исходом и примерной суммой).
                """
                advice = ask_ai(live_prompt).strip()
                if advice and "OK" not in advice[:10].upper():
                    send_tg(f"⚡ <b>ЛАЙВ-КОНТРОЛЬ: {bet['match']}</b>\n{advice}")

def find_new_matches(history, rules):
    existing_matches = {b["match"] for b in history["bets"]}
    date_str = NOW_TLT.strftime("%d.%m.%Y")
    time_str = NOW_TLT.strftime("%H:%M")
    
    s1 = web_search(f"расписание матчей сегодня {date_str} футбол хоккей КХЛ НХЛ баскетбол прогнозы коэффициенты")
    s2 = web_search(f"Dota 2 CS2 матчи сегодня {date_str} прогнозы коэффициенты sentrybot hltv")
    s3 = web_search(f"progsport forebet прогнозы на сегодня {date_str} коэффициенты")
    
    prompt = f"""
    Сейчас точное время в Тольятти (UTC+4): {date_str} {time_str}.
    Используй строгие правила из базы знаний:
    {rules}
    
    Свежие данные из сети:
    {s1}
    {s2}
    {s3}
    
    Найди 1–2 лучших матча, которые начнутся в ближайшие 15–120 минут от {time_str} (время Тольятти) и которых НЕТ в списке уже взятых: {list(existing_matches)}.
    Оцени реальную вероятность исхода (prob от 0.01 до 0.99) и коэффициент БК (odds). Перевес +EV должен быть >= 7%.
    
    Верни СТРОГО JSON-массив (без лишнего текста):
    [
      {{
        "match": "Команда 1 — Команда 2",
        "league": "Турнир",
        "start_time": "ЧЧ:ММ",
        "type": "Обратка" или "Валуй",
        "pick": "Ставка по-русски (например: 1X или ТМ 5.5 или П2)",
        "odds": 2.15,
        "prob": 0.54,
        "reason": "2 коротких предложения сути перевеса",
        "live_plan": "1 предложение: когда добирать или перекрываться в лайве",
        "risk": "1 главная угроза ставке"
      }}
    ]
    Если матчей с реальным перевесом сейчас нет — верни пустой массив [].
    """
    raw = ask_ai(prompt)
    try:
        clean = raw[raw.find("["):raw.rfind("]")+1]
        candidates = json.loads(clean)
    except Exception:
        return history, False

    added = False
    for c in candidates[:2]:
        if c["match"] in existing_matches:
            continue
        odds = float(c["odds"])
        prob = float(c["prob"])
        ev = round((prob * odds - 1.0) * 100, 1)
        if ev < 7.0:
            continue
        fair_odds = round(1.0 / prob, 2)
        min_odds = round(fair_odds * 1.04, 2)
        pct, stake_rub = kelly_stake(prob, odds, history["bank"])
        if stake_rub < 50:
            continue

        hh, mm = map(int, c["start_time"].split(":"))
        start_dt = NOW_TLT.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if start_dt < NOW_TLT - datetime.timedelta(hours=2):
            start_dt += datetime.timedelta(days=1)

        history["bets"].append({
            "match": c["match"],
            "league": c["league"],
            "start_iso": start_dt.isoformat(),
            "pick": c["pick"],
            "odds": odds,
            "stake_rub": stake_rub,
            "status": "PENDING"
        })

        msg = (
            f"🎯 <b>[{c['type']}] {c['league']}</b>\n"
            f"🕒 Старт: <b>{c['start_time']} (Тольятти)</b>\n"
            f"⚔️ <b>{c['match']}</b>\n"
            f"📌 Ставка: <b>{c['pick']}</b> | Кэф: <b>{odds}</b> (мин. вход: {min_odds})\n"
            f"📈 Честный кэф: {fair_odds} | Перевес: <b>+{ev}% EV</b>\n"
            f"💰 Ставка: <b>{pct}% банка ({stake_rub:.0f} ₽)</b>\n\n"
            f"📊 <b>Суть:</b> {c['reason']}\n"
            f"⚡ <b>Лайв-план:</b> {c['live_plan']}\n"
            f"⚠️ <b>Риск:</b> {c['risk']}"
        )
        send_tg(msg)
        added = True
    return history, added

if __name__ == "__main__":
    history, rules = load_data()
    history, rules, u1 = check_results_and_learn(history, rules)
    check_live_bets(history)
    history, u2 = find_new_matches(history, rules)
    if u1 or u2:
        save_data(history, rules)
