
import os, sqlite3, hashlib, secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, session, redirect, send_from_directory, render_template
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "vibra.db")
UPLOADS = os.path.join(BASE, "uploads")
os.makedirs(UPLOADS, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("VIBRA_SECRET", "cambia-questa-chiave-in-produzione")

DEFAULT_PASSWORD = "vibra2027"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT, phone TEXT, email TEXT,
    registration_status TEXT DEFAULT 'Incompleta',
    fee REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS team_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date TEXT,
    phone TEXT, email TEXT, shirt_number TEXT, role TEXT, notes TEXT,
    status TEXT DEFAULT 'Non autorizzato',
    manual_reason TEXT,
    manual_staff TEXT,
    manual_at TEXT,
    FOREIGN KEY(team_id) REFERENCES teams(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS player_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    original_name TEXT NOT NULL,
    doc_type TEXT,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS fields (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_no INTEGER,
    day TEXT NOT NULL,
    phase TEXT DEFAULT 'Gironi',
    group_name TEXT,
    field_id INTEGER,
    team_a INTEGER,
    team_b INTEGER,
    scheduled_start TEXT,
    duration_min INTEGER DEFAULT 15,
    break_min INTEGER DEFAULT 5,
    actual_start TEXT,
    actual_end TEXT,
    status TEXT DEFAULT 'Programmato',
    score_a INTEGER,
    score_b INTEGER,
    notes TEXT,
    FOREIGN KEY(field_id) REFERENCES fields(id),
    FOREIGN KEY(team_a) REFERENCES teams(id),
    FOREIGN KEY(team_b) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS penalties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id INTEGER NOT NULL,
    points INTEGER NOT NULL,
    reason TEXT NOT NULL,
    staff TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(team_id) REFERENCES teams(id)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    team_id INTEGER,
    player_id INTEGER,
    type TEXT NOT NULL,
    description TEXT,
    staff TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    staff TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    details TEXT
);
CREATE TABLE IF NOT EXISTS day_closures (
    day TEXT PRIMARY KEY,
    closed_at TEXT NOT NULL,
    summary TEXT NOT NULL
);
"""

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    con = db()
    con.executescript(SCHEMA)
    defaults = {
        "password_hash": hashlib.sha256(DEFAULT_PASSWORD.encode()).hexdigest(),
        "tournament_name": "VIBRA CALCIO SPLASH 2027",
        "match_duration": "15",
        "break_duration": "5",
        "current_day": "Sabato",
        "tournament_status": "Non iniziato",
        "fields_count": "3"
    }
    for k,v in defaults.items():
        con.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",(k,v))
    if con.execute("SELECT COUNT(*) c FROM fields").fetchone()["c"] == 0:
        for i in range(1,4):
            con.execute("INSERT INTO fields(name) VALUES(?)",(f"Campo {i}",))
    con.commit(); con.close()

def setting(key, default=None):
    con=db(); r=con.execute("SELECT value FROM settings WHERE key=?",(key,)).fetchone(); con.close()
    return r["value"] if r else default

def set_setting(key,value):
    con=db(); con.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(key,str(value))); con.commit(); con.close()

def audit(staff, entity, entity_id, action, details=""):
    con=db(); con.execute("INSERT INTO audit_log(created_at,staff,entity,entity_id,action,details) VALUES(?,?,?,?,?,?)",
                          (now(),staff,entity,entity_id,action,details)); con.commit(); con.close()

def auth(f):
    @wraps(f)
    def w(*a,**kw):
        if not session.get("auth"): return jsonify({"error":"Non autenticato"}),401
        return f(*a,**kw)
    return w

@app.route("/")
def index():
    return render_template("index.html")

@app.post("/api/login")
def login():
    p=request.json.get("password","")
    if hashlib.sha256(p.encode()).hexdigest()==setting("password_hash"):
        session["auth"]=True
        session["staff"]=request.json.get("staff","Staff")
        return jsonify(ok=True)
    return jsonify(ok=False,error="Password errata"),401

@app.post("/api/logout")
def logout():
    session.clear(); return jsonify(ok=True)

@app.get("/api/state")
@auth
def state():
    con=db()
    teams=con.execute("SELECT * FROM teams ORDER BY name").fetchall()
    players=con.execute("""SELECT p.*, t.name team_name FROM players p JOIN teams t ON t.id=p.team_id
                           ORDER BY t.name,p.last_name,p.first_name""").fetchall()
    fields=con.execute("SELECT * FROM fields WHERE active=1 ORDER BY id").fetchall()
    matches=con.execute("""SELECT m.*, fa.name field_name, ta.name team_a_name, tb.name team_b_name
                           FROM matches m LEFT JOIN fields fa ON fa.id=m.field_id
                           LEFT JOIN teams ta ON ta.id=m.team_a LEFT JOIN teams tb ON tb.id=m.team_b
                           ORDER BY CASE m.day WHEN 'Sabato' THEN 1 ELSE 2 END, m.scheduled_start, m.match_no""").fetchall()
    penalties=con.execute("""SELECT p.*,t.name team_name FROM penalties p JOIN teams t ON t.id=p.team_id ORDER BY p.id DESC""").fetchall()
    events=con.execute("""SELECT e.*,m.match_no,t.name team_name,p.first_name||' '||p.last_name player_name
                          FROM events e LEFT JOIN matches m ON m.id=e.match_id
                          LEFT JOIN teams t ON t.id=e.team_id LEFT JOIN players p ON p.id=e.player_id
                          ORDER BY e.id DESC LIMIT 100""").fetchall()
    logs=con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100").fetchall()
    closures=con.execute("SELECT * FROM day_closures").fetchall()
    con.close()
    return jsonify({
        "settings":{"current_day":setting("current_day"),"status":setting("tournament_status"),
                    "duration":int(setting("match_duration","15")),"break":int(setting("break_duration","5")),
                    "name":setting("tournament_name")},
        "teams":[dict(x) for x in teams], "players":[dict(x) for x in players],
        "fields":[dict(x) for x in fields], "matches":[dict(x) for x in matches],
        "penalties":[dict(x) for x in penalties], "events":[dict(x) for x in events],
        "logs":[dict(x) for x in logs], "closures":[dict(x) for x in closures]
    })

@app.post("/api/settings")
@auth
def settings():
    d=request.json
    for k in ["tournament_name","match_duration","break_duration","current_day","tournament_status"]:
        if k in d: set_setting(k,d[k])
    if "new_password" in d and d["new_password"]:
        set_setting("password_hash",hashlib.sha256(d["new_password"].encode()).hexdigest())
    audit(session.get("staff","Staff"),"settings",None,"Modifica impostazioni",json_string(d))
    return jsonify(ok=True)

def json_string(x):
    import json
    return json.dumps(x,ensure_ascii=False)

@app.post("/api/teams")
@auth
def add_team():
    d=request.json
    con=db(); cur=con.execute("""INSERT INTO teams(name,contact,phone,email,registration_status,fee,notes,created_at)
                                VALUES(?,?,?,?,?,?,?,?)""",
        (d["name"],d.get("contact",""),d.get("phone",""),d.get("email",""),
         d.get("registration_status","Incompleta"),float(d.get("fee",0)),d.get("notes",""),now()))
    con.commit(); tid=cur.lastrowid; con.close(); audit(session.get("staff","Staff"),"team",tid,"Creazione squadra",d["name"])
    return jsonify(id=tid)

@app.post("/api/teams/<int:tid>/documents")
@auth
def team_doc(tid):
    f=request.files.get("file")
    if not f: return jsonify(error="File mancante"),400
    fn=secure_filename(f.filename)
    stored=f"{secrets.token_hex(8)}_{fn}"; f.save(os.path.join(UPLOADS,stored))
    con=db(); con.execute("INSERT INTO team_documents(team_id,filename,original_name,uploaded_at) VALUES(?,?,?,?)",(tid,stored,fn,now())); con.commit(); con.close()
    audit(session.get("staff","Staff"),"team",tid,"Upload documento",fn)
    return jsonify(ok=True)

@app.post("/api/players")
@auth
def add_player():
    d=request.json
    con=db(); cur=con.execute("""INSERT INTO players(team_id,first_name,last_name,birth_date,phone,email,shirt_number,role,notes)
                                 VALUES(?,?,?,?,?,?,?,?,?)""",
        (d["team_id"],d["first_name"],d["last_name"],d.get("birth_date",""),d.get("phone",""),
         d.get("email",""),d.get("shirt_number",""),d.get("role",""),d.get("notes","")))
    con.commit(); pid=cur.lastrowid; con.close(); audit(session.get("staff","Staff"),"player",pid,"Creazione giocatore",f'{d["first_name"]} {d["last_name"]}')
    return jsonify(id=pid)

@app.post("/api/players/<int:pid>/authorize")
@auth
def authorize(pid):
    d=request.json; staff=d.get("staff") or session.get("staff","Staff")
    reason=d.get("reason","Documento verificato manualmente")
    con=db()
    con.execute("""UPDATE players SET status='Autorizzato manualmente',manual_reason=?,manual_staff=?,manual_at=? WHERE id=?""",(reason,staff,now(),pid))
    con.commit(); con.close(); audit(staff,"player",pid,"Svincolo manuale",reason)
    return jsonify(ok=True)

@app.post("/api/players/<int:pid>/block")
@auth
def block(pid):
    d=request.json; staff=d.get("staff") or session.get("staff","Staff")
    con=db(); con.execute("UPDATE players SET status='Non autorizzato',manual_reason=?,manual_staff=?,manual_at=? WHERE id=?",(d.get("reason",""),staff,now(),pid)); con.commit(); con.close()
    audit(staff,"player",pid,"Blocco giocatore",d.get("reason",""))
    return jsonify(ok=True)

@app.post("/api/players/<int:pid>/documents")
@auth
def player_doc(pid):
    f=request.files.get("file"); typ=request.form.get("doc_type","Documento")
    if not f: return jsonify(error="File mancante"),400
    fn=secure_filename(f.filename); stored=f"{secrets.token_hex(8)}_{fn}"; f.save(os.path.join(UPLOADS,stored))
    con=db(); con.execute("INSERT INTO player_documents(player_id,filename,original_name,doc_type,uploaded_at) VALUES(?,?,?,?,?)",(pid,stored,fn,typ,now()))
    con.execute("UPDATE players SET status='Autorizzato' WHERE id=?",(pid,)); con.commit(); con.close()
    audit(session.get("staff","Staff"),"player",pid,"Upload documento e autorizzazione",fn)
    return jsonify(ok=True)

@app.get("/uploads/<path:name>")
@auth
def upload(name):
    return send_from_directory(UPLOADS,name)

@app.post("/api/fields")
@auth
def add_field():
    name=request.json.get("name","Campo")
    con=db(); cur=con.execute("INSERT INTO fields(name) VALUES(?)",(name,)); con.commit(); i=cur.lastrowid; con.close()
    audit(session.get("staff","Staff"),"field",i,"Creazione campo",name); return jsonify(id=i)

@app.post("/api/matches")
@auth
def add_match():
    d=request.json
    con=db(); cur=con.execute("""INSERT INTO matches(match_no,day,phase,group_name,field_id,team_a,team_b,scheduled_start,duration_min,break_min,status)
                                  VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (d.get("match_no"),d.get("day",setting("current_day")),d.get("phase","Gironi"),d.get("group_name",""),
         d.get("field_id"),d.get("team_a"),d.get("team_b"),d.get("scheduled_start"),int(d.get("duration_min",setting("match_duration"))),
         int(d.get("break_min",setting("break_duration"))),"Programmato"))
    con.commit(); mid=cur.lastrowid; con.close(); audit(session.get("staff","Staff"),"match",mid,"Creazione partita",json_string(d))
    return jsonify(id=mid)

@app.post("/api/matches/<int:mid>/start")
@auth
def start_match(mid):
    con=db(); con.execute("UPDATE matches SET actual_start=?,status='In corso' WHERE id=?",(now(),mid)); con.commit(); con.close()
    set_setting("tournament_status","In corso"); audit(session.get("staff","Staff"),"match",mid,"Inizio partita","")
    return jsonify(ok=True)

@app.post("/api/matches/<int:mid>/finish")
@auth
def finish_match(mid):
    d=request.json
    con=db(); m=con.execute("SELECT * FROM matches WHERE id=?",(mid,)).fetchone()
    if not m: con.close(); return jsonify(error="Partita non trovata"),404
    con.execute("UPDATE matches SET actual_end=?,status='Terminata',score_a=?,score_b=? WHERE id=?",
                (now(),int(d["score_a"]),int(d["score_b"]),mid))
    con.commit(); con.close()
    audit(session.get("staff","Staff"),"match",mid,"Fine partita",f'{d["score_a"]}-{d["score_b"]}')
    return jsonify(ok=True)

@app.post("/api/penalties")
@auth
def penalty():
    d=request.json; con=db(); cur=con.execute("INSERT INTO penalties(team_id,points,reason,staff,created_at) VALUES(?,?,?,?,?)",
        (d["team_id"],int(d["points"]),d["reason"],d.get("staff") or session.get("staff","Staff"),now()))
    con.commit(); i=cur.lastrowid; con.close(); audit(session.get("staff","Staff"),"penalty",i,"Aggiunta penalità",json_string(d)); return jsonify(id=i)

@app.post("/api/events")
@auth
def event():
    d=request.json; con=db(); cur=con.execute("""INSERT INTO events(match_id,team_id,player_id,type,description,staff,created_at)
                                                   VALUES(?,?,?,?,?,?,?)""",
        (d.get("match_id"),d.get("team_id"),d.get("player_id"),d["type"],d.get("description",""),d.get("staff") or session.get("staff","Staff"),now()))
    con.commit(); i=cur.lastrowid; con.close(); audit(session.get("staff","Staff"),"event",i,"Evento torneo",d["type"]); return jsonify(id=i)

@app.get("/api/standings")
@auth
def standings():
    con=db(); teams=con.execute("SELECT * FROM teams ORDER BY name").fetchall()
    matches=con.execute("SELECT * FROM matches WHERE status='Terminata'").fetchall()
    pens=con.execute("SELECT team_id,SUM(points) p FROM penalties GROUP BY team_id").fetchall()
    pd={r["team_id"]:r["p"] for r in pens}; out=[]
    for t in teams:
        x={"team_id":t["id"],"team":t["name"],"played":0,"wins":0,"draws":0,"losses":0,"gf":0,"ga":0,"gd":0,"penalties":pd.get(t["id"],0),"points":pd.get(t["id"],0)}
        for m in matches:
            if m["team_a"]==t["id"] or m["team_b"]==t["id"]:
                a,b=m["score_a"] or 0,m["score_b"] or 0
                x["played"]+=1
                if m["team_a"]==t["id"]: gf,ga=a,b
                else: gf,ga=b,a
                x["gf"]+=gf;x["ga"]+=ga
                if gf>ga:x["wins"]+=1;x["points"]+=3
                elif gf==ga:x["draws"]+=1;x["points"]+=1
                else:x["losses"]+=1
        x["gd"]=x["gf"]-x["ga"]; out.append(x)
    con.close()
    out.sort(key=lambda x:(-x["points"],-x["gd"],-x["gf"],x["team"].lower()))
    return jsonify(out)

@app.post("/api/day/close")
@auth
def close_day():
    day=request.json.get("day",setting("current_day"))
    con=db()
    total=con.execute("SELECT COUNT(*) c FROM matches WHERE day=?",(day,)).fetchone()["c"]
    done=con.execute("SELECT COUNT(*) c FROM matches WHERE day=? AND status='Terminata'",(day,)).fetchone()["c"]
    if total and total!=done:
        con.close(); return jsonify(error=f"Partite completate {done}/{total}. Non puoi chiudere la giornata."),400
    summary=f"Partite completate: {done}/{total}; classifiche aggiornate; chiusura {day}."
    con.execute("INSERT OR REPLACE INTO day_closures(day,closed_at,summary) VALUES(?,?,?)",(day,now(),summary))
    con.commit(); con.close(); audit(session.get("staff","Staff"),"day",None,"Chiusura giornata",summary)
    if day=="Sabato": set_setting("current_day","Domenica")
    return jsonify(ok=True,summary=summary)

@app.post("/api/matches/recalculate")
@auth
def recalc():
    con=db()
    # Ricalcola gli orari per ciascun giorno/campo a partire dagli orari programmati,
    # propagando la durata reale delle partite concluse e le pause.
    rows=con.execute("SELECT * FROM matches ORDER BY day, field_id, scheduled_start, match_no").fetchall()
    groups={}
    for m in rows: groups.setdefault((m["day"],m["field_id"]),[]).append(m)
    changes=0
    for key, ms in groups.items():
        cursor=None
        for m in ms:
            base=m["scheduled_start"]
            if not base: continue
            try: dt=datetime.fromisoformat(base)
            except: continue
            if cursor and cursor>dt: dt=cursor
            if m["status"]=="Terminata" and m["actual_end"]:
                try: end=datetime.fromisoformat(m["actual_end"])
                except: end=dt+timedelta(minutes=m["duration_min"])
            elif m["status"]=="In corso" and m["actual_start"]:
                try: end=datetime.fromisoformat(m["actual_start"])+timedelta(minutes=m["duration_min"])
                except: end=dt+timedelta(minutes=m["duration_min"])
            else:
                end=dt+timedelta(minutes=m["duration_min"])
            next_start=end+timedelta(minutes=m["break_min"])
            # For display, store the current calculated start in notes-like field via scheduled_start.
            if m["status"] in ("Programmato","In attesa"):
                new=dt.strftime("%Y-%m-%d %H:%M")
                if new != m["scheduled_start"]:
                    con.execute("UPDATE matches SET scheduled_start=? WHERE id=?",(new,m["id"])); changes+=1
            cursor=next_start
    con.commit(); con.close(); audit(session.get("staff","Staff"),"matches",None,"Ricalcolo orari",f"Modifiche: {changes}")
    return jsonify(ok=True,changes=changes)

@app.post("/api/matches/<int:mid>/status")
@auth
def match_status(mid):
    status=request.json.get("status")
    con=db(); con.execute("UPDATE matches SET status=? WHERE id=?",(status,mid)); con.commit(); con.close()
    audit(session.get("staff","Staff"),"match",mid,"Cambio stato",status); return jsonify(ok=True)

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0",port=5000,debug=True)
