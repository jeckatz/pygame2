"""MathQuest - a Flask game that teaches the standard written method for
addition, subtraction, multiplication and division. Guests can play;
logged-in players get their scores saved and appear on the leaderboard."""
import os, random, re, sqlite3
from flask import (Flask, g, session, request, jsonify, redirect, url_for,
                   render_template, flash)
from jinja2 import DictLoader
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mathquest.db")
TOTAL = 10
SYMBOL = {"add": "+", "sub": "−", "mul": "×", "div": "÷"}
PLACES = ["ones", "tens", "hundreds", "thousands", "ten-thousands"]

# ---------------------------------------------------------------- database
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    conn = g.pop("db", None)
    if conn:
        conn.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, pw_hash TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS scores(
        id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, op TEXT, level INTEGER,
        score INTEGER, correct INTEGER, created TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
    """)
    conn.commit()
    conn.close()

# ------------------------------------------------- teaching: standard methods
def digits(n, width):
    return [int(c) for c in str(n).zfill(width)][::-1]  # ones first

def carry_steps(da, factor_or_digits, mode):
    """Column addition (mode 'add') or column multiplication by one digit."""
    steps, carry, w = [], 0, len(da)
    for i in range(w):
        if mode == "add":
            val = da[i] + factor_or_digits[i] + carry
            calc = f"{da[i]} + {factor_or_digits[i]}"
            sign = "Add"
        else:
            val = da[i] * factor_or_digits + carry
            calc = f"{da[i]} × {factor_or_digits}"
            sign = "Multiply"
        if carry:
            calc += f" + {carry} (carried)"
        text = f"{sign} the {PLACES[i]}: {calc} = {val}."
        if val >= 10 and i < w - 1:
            text += f" Write {val % 10} and carry {val // 10} to the {PLACES[i + 1]}."
        else:
            text += f" Write {val}."
        carry = val // 10
        steps.append(text)
    return steps

def add_steps(a, b):
    w = max(len(str(a)), len(str(b)))
    steps = ["Line up the numbers so ones sit above ones, tens above tens. Start on the right."]
    steps += carry_steps(digits(a, w), digits(b, w), "add")
    steps.append(f"Read the answer: {a + b}.")
    return steps

def sub_steps(a, b):
    w = len(str(a))
    da, db_ = digits(a, w), digits(b, w)
    steps = ["Put the bigger number on top and line up the places. Start on the right."]
    for i in range(w):
        top = da[i]
        if top < db_[i]:
            if top < 0:
                steps.append(f"The {PLACES[i]} lent one away, so borrow again from the {PLACES[i + 1]}: it becomes {top + 10}.")
            else:
                steps.append(f"{top} is smaller than {db_[i]}, so borrow 1 from the {PLACES[i + 1]}: {top} becomes {top + 10}.")
            top += 10
            da[i + 1] -= 1
        steps.append(f"Subtract the {PLACES[i]}: {top} − {db_[i]} = {top - db_[i]}.")
    steps.append(f"Read the answer: {a - b}.")
    return steps

def mul_steps(a, b):
    if a < 10:
        counts = ", ".join(str(a * k) for k in range(1, b + 1))
        return [f"Think of {b} groups of {a}.",
                f"Skip count by {a}, {b} times: {counts}.",
                f"The last number is the answer: {a * b}."]
    w = len(str(a))
    steps = [f"Write {a} on top and {b} below. Multiply each digit of {a} by {b}, starting on the right."]
    steps += carry_steps(digits(a, w), b, "mul")
    steps.append(f"Read the answer: {a * b}.")
    return steps

def div_steps(a, b):
    q = a // b
    if a < 100:
        ladder = ", ".join(str(b * k) for k in range(1, q + 1))
        return ["Division is the opposite of multiplication.",
                f"Ask: {b} × what = {a}?",
                f"Count by {b}s: {ladder}.",
                f"{b} × {q} = {a}, so {a} ÷ {b} = {q}."]
    steps = ["Use long division. Remember D-M-S-B: Divide, Multiply, Subtract, Bring down."]
    s, cur, qd = str(a), 0, ""
    for i, ch in enumerate(s):
        cur = cur * 10 + int(ch)
        if cur < b and not qd:
            steps.append(f"{cur} is too small to divide by {b}, so use the next digit too.")
            continue
        d = cur // b
        steps.append(f"Divide: {cur} ÷ {b} = {d}. Multiply: {d} × {b} = {d * b}. Subtract: {cur} − {d * b} = {cur - d * b}.")
        qd += str(d)
        cur -= d * b
        if i < len(s) - 1:
            steps.append(f"Bring down the next digit, {s[i + 1]}.")
    steps.append(f"The digits on top spell the answer: {int(qd)}.")
    return steps

def make_question(op, level):
    rng = {1: (1, 9), 2: (10, 99), 3: (100, 999)}[level]
    if op == "add":
        a, b = random.randint(*rng), random.randint(*rng)
        ans, steps = a + b, add_steps(a, b)
    elif op == "sub":
        a, b = sorted((random.randint(*rng), random.randint(*rng)), reverse=True)
        ans, steps = a - b, sub_steps(a, b)
    elif op == "mul":
        a = random.randint(2, 9) if level == 1 else random.randint(*rng)
        b = random.randint(2, 9)
        ans, steps = a * b, mul_steps(a, b)
    else:
        b = random.randint(2, 9)
        q = {1: random.randint(2, 9), 2: random.randint(10, 30), 3: random.randint(100, 300)}[level]
        a, ans = b * q, q
        steps = div_steps(a, b)
    return {"op": op, "a": a, "b": b, "ans": ans, "steps": steps,
            "text": f"{a} {SYMBOL[op]} {b} = ?", "hint": False, "answered": False}

# --------------------------------------------------------------- game API
def public(state):
    q = session["q"]
    return {"round": state["round"], "total": TOTAL, "score": state["score"],
            "streak": state["streak"], "text": q["text"], "op": q["op"]}

def new_question():
    st = session["g"]
    op = st["op"] if st["op"] != "mix" else random.choice(list(SYMBOL))
    st["round"] += 1
    session["q"] = make_question(op, st["level"])
    session["g"] = st
    return public(st)

@app.post("/api/start")
def api_start():
    data = request.get_json(silent=True) or {}
    op = data.get("op", "add")
    level = int(data.get("level", 1))
    if op not in list(SYMBOL) + ["mix"] or level not in (1, 2, 3):
        return jsonify(error="Bad settings"), 400
    session["g"] = {"op": op, "level": level, "round": 0, "score": 0,
                    "streak": 0, "correct": 0, "saved": False}
    return jsonify(new_question())

@app.post("/api/next")
def api_next():
    st = session.get("g")
    if not st or st["round"] >= TOTAL:
        return jsonify(error="No game in progress"), 400
    return jsonify(new_question())

@app.post("/api/hint")
def api_hint():
    q = session.get("q")
    if not q or q["answered"]:
        return jsonify(error="No question"), 400
    q["hint"] = True
    session["q"] = q
    return jsonify(steps=q["steps"])

@app.post("/api/answer")
def api_answer():
    st, q = session.get("g"), session.get("q")
    if not st or not q or q["answered"]:
        return jsonify(error="No open question"), 400
    try:
        value = int((request.get_json(silent=True) or {}).get("value", ""))
    except (TypeError, ValueError):
        return jsonify(error="Type a whole number"), 400
    correct = value == q["ans"]
    points = 0
    if correct:
        base = 10 * st["level"]
        points = base // 2 if q["hint"] else base + 2 * min(st["streak"], 5)
        st["score"] += points
        st["streak"] += 1
        st["correct"] += 1
    else:
        st["streak"] = 0
    q["answered"] = True
    done = st["round"] >= TOTAL
    summary = None
    if done:
        if session.get("uid") and not st["saved"]:
            db().execute("INSERT INTO scores(user_id,op,level,score,correct) VALUES(?,?,?,?,?)",
                         (session["uid"], st["op"], st["level"], st["score"], st["correct"]))
            db().commit()
            st["saved"] = True
        summary = {"score": st["score"], "correct": st["correct"], "total": TOTAL,
                   "saved": st["saved"], "logged_in": bool(session.get("uid"))}
    session["g"], session["q"] = st, q
    return jsonify(correct=correct, points=points, answer=q["ans"], score=st["score"],
                   streak=st["streak"], done=done, summary=summary,
                   steps=None if correct and not q["hint"] else q["steps"])

# -------------------------------------------------------------- pages/auth
@app.get("/")
def home():
    top = db().execute("""SELECT u.username, MAX(s.score) best FROM scores s
                          JOIN users u ON u.id = s.user_id
                          GROUP BY u.id ORDER BY best DESC LIMIT 5""").fetchall()
    mine = None
    if session.get("uid"):
        mine = db().execute("SELECT MAX(score) FROM scores WHERE user_id=?",
                            (session["uid"],)).fetchone()[0]
    return render_template("home.html", top=top, mine=mine)

def auth(kind):
    if request.method == "POST":
        name = request.form.get("username", "").strip()
        pw = request.form.get("password", "")
        if kind == "register":
            if not re.fullmatch(r"\w{3,20}", name):
                flash("Username needs 3 to 20 letters, numbers or underscores.")
            elif len(pw) < 6:
                flash("Password needs at least 6 characters.")
            elif db().execute("SELECT 1 FROM users WHERE username=?", (name,)).fetchone():
                flash("That username is taken. Try another one.")
            else:
                cur = db().execute("INSERT INTO users(username,pw_hash) VALUES(?,?)",
                                   (name, generate_password_hash(pw)))
                db().commit()
                session["uid"], session["uname"] = cur.lastrowid, name
                return redirect(url_for("home"))
        else:
            row = db().execute("SELECT * FROM users WHERE username=?", (name,)).fetchone()
            if row and check_password_hash(row["pw_hash"], pw):
                session["uid"], session["uname"] = row["id"], row["username"]
                return redirect(url_for("home"))
            flash("Wrong username or password.")
    return render_template("auth.html", kind=kind)

@app.route("/register", methods=["GET", "POST"])
def register():
    return auth("register")

@app.route("/login", methods=["GET", "POST"])
def login():
    return auth("login")

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

# --------------------------------------------------------------- templates
BASE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MathQuest</title>
<link rel="icon" type="image/png" href="static/image.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Fredoka:wght@500;700&family=Nunito:wght@500;700&display=swap" rel="stylesheet">
<style>
:root{--paper:#f6fbff;--grid:#cfe3f1;--ink:#1d3557;--pencil:#f4b400;--eraser:#ef6f6c;--leaf:#2a9d6f;--card:#fff}
@media (prefers-color-scheme:dark){:root{--paper:#14202e;--grid:#22364b;--ink:#eaf2fa;--card:#1c2d40}}
*{box-sizing:border-box}
body{margin:0;font:600 18px/1.5 Nunito,system-ui,sans-serif;color:var(--ink);background-color:var(--paper);
background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px);background-size:28px 28px}
header{display:flex;justify-content:space-between;align-items:center;padding:14px 20px;flex-wrap:wrap;gap:8px}
h1,h2{font-family:Fredoka,sans-serif;margin:0}
h1 a{color:var(--ink);text-decoration:none;font-size:30px}
nav a{color:var(--ink);margin-left:14px}
main{max-width:720px;margin:0 auto;padding:0 16px 48px}
.card{background:var(--card);border:3px solid var(--ink);border-radius:18px;padding:20px;margin:16px 0;box-shadow:5px 5px 0 var(--ink)}
button,.btn{font:700 18px Fredoka,sans-serif;border:3px solid var(--ink);border-radius:12px;padding:10px 18px;background:var(--card);color:var(--ink);cursor:pointer;text-decoration:none;display:inline-block}
button:hover,.btn:hover{background:var(--pencil);color:#1d3557}
button.on{background:var(--pencil);color:#1d3557}
button.go{background:var(--leaf);color:#fff}
button:focus-visible,input:focus-visible,a:focus-visible{outline:4px solid var(--eraser);outline-offset:2px}
.row{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}
.stats{display:flex;gap:18px;font-family:Fredoka;font-size:20px;flex-wrap:wrap}
#question{font:700 clamp(44px,12vw,72px)/1.1 Fredoka,sans-serif;text-align:center;margin:18px 0}
input{font:700 32px Fredoka;width:100%;max-width:240px;padding:8px 12px;border:3px solid var(--ink);border-radius:12px;background:var(--card);color:var(--ink);text-align:center}
.fb{margin-top:12px}.good{color:var(--leaf)}.bad{color:var(--eraser)}
ol.steps{background:var(--paper);border-left:6px solid var(--pencil);padding:10px 10px 10px 36px;border-radius:8px}
.flash{background:var(--eraser);color:#fff;padding:10px 14px;border-radius:10px;margin:10px 0}
form.auth label{display:block;margin:12px 0 4px}form.auth input{max-width:none;font-size:22px;text-align:left}
.toast{position:fixed;left:50%;top:18px;transform:translateX(-50%);background:var(--leaf);color:#fff;font:700 22px Fredoka,sans-serif;
padding:12px 24px;border:3px solid var(--ink);border-radius:14px;box-shadow:4px 4px 0 var(--ink);z-index:10}
@media (prefers-reduced-motion:no-preference){.toast{animation:pop .25s ease-out}@keyframes pop{from{transform:translateX(-50%) scale(.85);opacity:0}}}
footer{text-align:center;padding:20px 16px 28px;font:700 18px Fredoka,sans-serif;opacity:.8}
[hidden]{display:none!important}
</style></head><body>
<header><h1><a href="{{ url_for('home') }}">MathQuest</a></h1>
<nav>{% if session.get('uid') %}Hi, {{ session['uname'] }}! <a href="{{ url_for('logout') }}">Log out</a>
{% else %}Playing as guest <a href="{{ url_for('login') }}">Log in</a> <a href="{{ url_for('register') }}">Register</a>{% endif %}</nav></header>
<main>{% for m in get_flashed_messages() %}<div class="flash">{{ m }}</div>{% endfor %}{% block body %}{% endblock %}</main>
<footer>&lt;/&gt; jeckatz</footer>
</body></html>"""

AUTH = """{% extends 'base.html' %}{% block body %}
<div class="card"><h2>{{ 'Create your account' if kind == 'register' else 'Log in' }}</h2>
<form class="auth" method="post">
<label for="u">Username</label><input id="u" name="username" autocomplete="username" required>
<label for="p">Password</label><input id="p" name="password" type="password" autocomplete="{{ 'new-password' if kind == 'register' else 'current-password' }}" required>
<div class="row"><button class="go">{{ 'Register' if kind == 'register' else 'Log in' }}</button>
<a class="btn" href="{{ url_for('home') }}">Play as guest</a></div></form>
<p>{% if kind == 'register' %}Have an account? <a href="{{ url_for('login') }}">Log in</a>
{% else %}New here? <a href="{{ url_for('register') }}">Register</a>{% endif %}</p></div>{% endblock %}"""

HOME = """{% extends 'base.html' %}{% block body %}
<section class="card" id="setup"><h2>Pick your challenge</h2>
<p>Learn the standard written method, one step at a time. Each game has 10 questions.</p>
<div class="row" role="group" aria-label="Operation">
<button data-op="add" class="on">Add +</button><button data-op="sub">Subtract −</button>
<button data-op="mul">Multiply ×</button><button data-op="div">Divide ÷</button><button data-op="mix">Mix it up</button></div>
<div class="row" role="group" aria-label="Level">
<button data-level="1" class="on">Level 1: small</button><button data-level="2">Level 2: medium</button><button data-level="3">Level 3: big</button></div>
<button class="go" id="start">Start game</button>
{% if mine is not none %}<p>Your best score: <b>{{ mine }}</b></p>{% endif %}
</section>

<section class="card" id="game" hidden>
<div class="stats"><span>Question <b id="qnum"></b></span><span>Score <b id="score">0</b></span><span>Streak <b id="streak">0</b></span></div>
<div id="question" aria-live="polite"></div>
<div style="text-align:center"><input id="ans" inputmode="numeric" autocomplete="off" aria-label="Your answer"></div>
<div class="row" style="justify-content:center">
<button class="go" id="check">Check answer</button><button id="hint">Show me the steps (half points)</button>
<button id="next" hidden>Next question</button></div>
<div class="fb" id="fb" aria-live="polite"></div>
</section>

<div class="toast" id="toast" role="status" hidden></div>
<section class="card" id="results" hidden><h2>Game over!</h2>
<p style="font:700 28px Fredoka">Score: <span id="fscore"></span> &nbsp; Correct: <span id="fcorrect"></span></p>
<p id="fsave"></p><button class="go" id="again">Play again</button></section>

<section class="card"><h2>Top players</h2>
{% if top %}<ol>{% for r in top %}<li>{{ r.username }}: {{ r.best }}</li>{% endfor %}</ol>
{% else %}<p>No scores yet. Register and be the first on the board!</p>{% endif %}</section>

<script>
const $=id=>document.getElementById(id);
let op='add',level=1,lastDone=false;
function pick(sel,attr,btn){document.querySelectorAll(sel).forEach(b=>b.classList.remove('on'));btn.classList.add('on');return btn.dataset[attr];}
document.querySelectorAll('[data-op]').forEach(b=>b.onclick=()=>op=pick('[data-op]','op',b));
document.querySelectorAll('[data-level]').forEach(b=>b.onclick=()=>level=+pick('[data-level]','level',b));
async function api(p,body){const r=await fetch(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})});return r.json();}
const stepsHtml=s=>'<ol class="steps">'+s.map(x=>'<li>'+x+'</li>').join('')+'</ol>';
function show(id){['setup','game','results'].forEach(x=>$(x).hidden=x!==id);}
function render(d){
  $('qnum').textContent=d.round+' / '+d.total;$('score').textContent=d.score;$('streak').textContent=d.streak;
  $('question').textContent=d.text;$('ans').value='';$('ans').disabled=false;$('fb').innerHTML='';
  $('check').hidden=false;$('hint').hidden=false;$('next').hidden=true;$('ans').focus();
}
$('start').onclick=async()=>{lastDone=false;show('game');render(await api('/api/start',{op,level}));};
$('hint').onclick=async()=>{const d=await api('/api/hint');if(d.steps)$('fb').innerHTML='<b>Here is the standard method:</b>'+stepsHtml(d.steps);$('ans').focus();};
function showResults(s){
  $('fscore').textContent=s.score;$('fcorrect').textContent=s.correct+'/'+s.total;
  $('fsave').innerHTML=s.saved?'Your score was saved to your account.':'Playing as a guest, so this score was not saved. <a href="/register">Register</a> or <a href="/login">log in</a> to keep your scores.';
  show('results');
}
let busy=false;
function toast(msg){const t=$('toast');t.textContent=msg;t.hidden=false;clearTimeout(t._h);t._h=setTimeout(()=>t.hidden=true,1100);}
$('check').onclick=async()=>{
  if(busy)return;
  const d=await api('/api/answer',{value:$('ans').value});
  if(d.error){$('fb').innerHTML='<span class="bad">'+d.error+'</span>';return;}
  $('score').textContent=d.score;$('streak').textContent=d.streak;$('ans').disabled=true;
  $('check').hidden=true;$('hint').hidden=true;
  if(d.correct){
    busy=true;toast('Correct! +'+d.points+' points');
    setTimeout(async()=>{
      busy=false;
      if(d.done)showResults(d.summary);else render(await api('/api/next'));
    },900);
    return;
  }
  $('next').hidden=false;$('next').textContent=d.done?'See results':'Next question';
  lastDone=d.done;window._sum=d.summary;
  $('fb').innerHTML='<b class="bad">Not quite. The answer is '+d.answer+'.</b>'+stepsHtml(d.steps);
  $('next').focus();
};
$('next').onclick=async()=>{
  if(lastDone){showResults(window._sum);return;}
  render(await api('/api/next'));
};
$('again').onclick=()=>show('setup');
$('ans').addEventListener('keydown',e=>{if(e.key==='Enter'&&!busy){(!$('check').hidden?$('check'):$('next')).click();}});
</script>{% endblock %}"""

app.jinja_loader = DictLoader({"base.html": BASE, "auth.html": AUTH, "home.html": HOME})
init_db()

if __name__ == "__main__":
    app.run(debug=True)