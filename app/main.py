from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, Response
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import mailbox, csv, zipfile, io, uuid, json

# --- storage ---
DATA = Path("/data"); UP = DATA/"uploads"; JOBS = DATA/"jobs"; OUT = Path("/downloads")
for p in (DATA, UP, JOBS, OUT): p.mkdir(parents=True, exist_ok=True)

# --- limits / worker ---
MAX_BYTES = 20 * 1024 * 1024 * 1024
CHUNK = 16 * 1024 * 1024
POOL = ThreadPoolExecutor(max_workers=2)

app = FastAPI()

# --- UI (sexy dark, responsive, one page) ---
HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MBOX → CSV | mbox-csv.com</title>
<meta name="description" content="Convert .mbox email archives to CSV. Upload up to 20 GB. Server-side parsing. Get a ZIP with emails.csv.">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0b1020;--panel:#0f172a;--muted:#9aa4b2;--text:#e6e9ef;--brand:#7c5cff;--brand2:#22c55e;
  --ring:#334155;--ring2:#1f2937;--ok:#22c55e;--err:#ef4444;
}
*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:
 radial-gradient(1200px 800px at 75% -10%,#2a3458 0%,transparent 60%),
 radial-gradient(1000px 600px at -20% 40%,#1a2040 0%,transparent 55%),var(--bg);
 color:var(--text);font-family:Inter,system-ui,Segoe UI,Roboto,Arial}
.container{max-width:960px;margin:0 auto;padding:28px}
.header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin:8px 0 28px}
.brand{display:flex;align-items:center;gap:12px}
.badge{width:14px;height:14px;border-radius:50%;background:conic-gradient(from 0deg,#7c5cff,#22c55e);box-shadow:0 0 18px #7c5cff88}
h1{font-size:28px;letter-spacing:.2px;margin:0}
.sub{color:var(--muted);margin-top:6px}
.panel{background:linear-gradient(180deg,#0d1428 0%,#0c1326 100%);border:1px solid var(--ring2);border-radius:18px;padding:26px;box-shadow:0 20px 60px #0007}
.drop{border:1.5px dashed var(--ring);border-radius:14px;padding:40px;text-align:center;cursor:pointer;transition:.15s;background:#0b1224}
.drop:hover{border-color:#55627a}
.drop.drag{background:#0e1a34;border-color:#7c5cff}
.drop .hint{color:var(--muted)}
.controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:18px}
.btn{display:inline-flex;align-items:center;gap:10px;padding:12px 16px;border:0;border-radius:12px;font-weight:600;cursor:pointer}
.btn-primary{background:linear-gradient(90deg,#7c5cff,#5b85ff);color:#0b0f1e}
.btn-secondary{background:transparent;color:var(--text);border:1px solid var(--ring)}
.btn[disabled]{opacity:.6;cursor:not-allowed}
.progress{display:flex;align-items:center;gap:12px;margin-top:18px}
.bar{flex:1;height:12px;border-radius:999px;background:#0b1b2f;border:1px solid var(--ring2);overflow:hidden}
.fill{height:100%;width:0;background:linear-gradient(90deg,#22c55e,#7c5cff)}
.pct{min-width:48px;text-align:right;color:var(--muted)}
.status{min-height:24px;margin-top:10px;color:#cdd6e3}
.note{margin-top:14px;color:var(--muted);font-size:13px}
.footer{margin-top:28px;color:#7c8799;font-size:12px;text-align:center}
a.dl{display:none;color:#22c55e;text-decoration:none;font-weight:600}
kbd{background:#111a2e;padding:2px 6px;border-radius:6px;border:1px solid #1e293b}
</style>
</head><body>
<div class="container">
  <div class="header">
    <div class="brand"><div class="badge"></div><div>
      <h1>MBOX → CSV</h1>
      <div class="sub">Upload up to 20 GB. Server-side conversion. Download a ZIP with <b>emails.csv</b>.</div>
    </div></div>
  </div>

  <div class="panel">
    <div id="drop" class="drop">
      <div style="font-size:16px;margin-bottom:6px">Drag & drop your <b>.mbox</b> here</div>
      <div class="hint">or click to choose a file</div>
      <input id="file" type="file" accept=".mbox" hidden>
    </div>

    <div class="controls">
      <button id="go" class="btn btn-primary" disabled>
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l9 4-9 4-9-4 9-4Zm0 7l9 4-9 4-9-4 9-4Zm0 7l9 4-9 4-9-4 9-4Z"/></svg>
        Upload & Convert
      </button>
      <a id="dl" class="dl">Download ZIP</a>
    </div>

    <div class="progress">
      <div class="bar"><div id="fill" class="fill"></div></div>
      <div id="pct" class="pct">0%</div>
    </div>

    <div id="status" class="status">Idle.</div>
    <div class="note">Tip: You can leave this tab open while we parse your archive. When ready, download starts automatically.</div>
  </div>

  <div class="footer">mbox-csv.com • Privacy-first • No data retained after conversion</div>
</div>

<script>
const $=s=>document.querySelector(s);
const drop=$("#drop"), file=$("#file"), go=$("#go"), fill=$("#fill"), pct=$("#pct"), st=$("#status"), dl=$("#dl");
let selected=null, job=null, poll=null;

function setPct(v){ fill.style.width=v+"%"; pct.textContent=Math.floor(v)+"%" }
function setSt(t){ st.textContent=t }

drop.addEventListener("click",()=>file.click());
["dragover","dragenter"].forEach(evn=>drop.addEventListener(evn,e=>{e.preventDefault();drop.classList.add("drag")}));
["dragleave","drop"].forEach(evn=>drop.addEventListener(evn,()=>drop.classList.remove("drag")));
drop.addEventListener("drop",e=>{
  e.preventDefault();
  if(!e.dataTransfer.files.length) return;
  selected = e.dataTransfer.files[0];
  drop.querySelector(".hint").innerHTML = `<b>Selected:</b> ${selected.name}`;
  go.disabled = false; setPct(0); setSt("Ready.");
});
file.addEventListener("change",e=>{
  if(!e.target.files.length) return;
  selected = e.target.files[0];
  drop.querySelector(".hint").innerHTML = `<b>Selected:</b> ${selected.name}`;
  go.disabled = false; setPct(0); setSt("Ready.");
});

go.addEventListener("click",()=>{
  if(!selected) return;
  go.disabled=true; dl.style.display="none"; setSt("Uploading…");
  const fd = new FormData(); fd.append("file", selected);
  const xhr = new XMLHttpRequest();
  xhr.open("POST","/upload"); xhr.responseType="json";
  xhr.upload.onprogress = e => { if(e.lengthComputable) setPct(e.loaded/e.total*100) };
  xhr.onerror = ()=>{ setSt("Network error."); go.disabled=false };
  xhr.onload = ()=>{
    if(xhr.status!==200){ setSt("Error "+xhr.status); go.disabled=false; return }
    job = xhr.response.job_id; setPct(100); setSt("Upload complete. Parsing…");
    poll = setInterval(async ()=>{
      const r = await fetch("/status/"+job).then(r=>r.json());
      if(r.status==="processing"){ setSt(`Parsing… ${ (r.processed||0).toLocaleString() } messages`) }
      else if(r.status==="done"){
        clearInterval(poll);
        dl.href="/download/"+job; dl.download="emails.zip"; dl.style.display="inline";
        dl.click(); setSt("Done."); go.disabled=false;
      } else if(r.status==="error"){
        clearInterval(poll); setSt("Error: "+(r.error||"unknown")); go.disabled=false;
      }
    }, 1500);
  };
  xhr.send(fd);
});
</script>
</body></html>
"""

def _jpath(jid): return JOBS/f"{jid}.json"
def _load(jid):
    p=_jpath(jid); return json.loads(p.read_text()) if p.exists() else None
def _save(obj): _jpath(obj["id"]).write_text(json.dumps(obj))

def _parse_job(jid):
    j=_load(jid); 
    if not j: return
    j["status"]="processing"; j["processed"]=0; _save(j)
    src=Path(j["in_path"]); out_zip=OUT/f"{jid}-emails.zip"
    try:
        m = mailbox.mbox(str(src))
        with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            with zf.open("emails.csv","w") as zmember:
                with io.TextIOWrapper(zmember, encoding="utf-8", newline="") as txt:
                    w = csv.writer(txt)
                    w.writerow(["date","from","to","cc","bcc","subject","message_id"])
                    for i,msg in enumerate(m,1):
                        w.writerow([msg.get("Date",""), msg.get("From",""), msg.get("To",""),
                                    msg.get("Cc",""), msg.get("Bcc",""), msg.get("Subject",""),
                                    msg.get("Message-Id","")])
                        if i % 50000 == 0:
                            j["processed"]=i; _save(j)
        j["status"]="done"; j["processed"]=i if 'i' in locals() else 0; j["out_path"]=str(out_zip); _save(j)
    except Exception as e:
        j["status"]="error"; j["error"]=str(e); _save(j)
    finally:
        try: src.unlink(missing_ok=True)
        except: pass

@app.get("/", response_class=HTMLResponse)
def home(): return HTML

@app.head("/")
def head_ok(): return Response(status_code=200)

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    jid = uuid.uuid4().hex
    dst = UP/f"{jid}.mbox"; total=0
    with dst.open("wb") as f:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk: break
            total += len(chunk)
            if total > MAX_BYTES:
                dst.unlink(missing_ok=True)
                raise HTTPException(413,"File too large (max 20 GB)")
            f.write(chunk)
    job={"id":jid,"status":"queued","size":total,"in_path":str(dst)}
    _save(job); POOL.submit(_parse_job,jid)
    return JSONResponse({"job_id":jid})

@app.get("/status/{jid}")
def status(jid:str):
    j=_load(jid)
    if not j: return JSONResponse({"status":"unknown"}, status_code=404)
    return JSONResponse({"status":j["status"], "processed":j.get("processed"), "error":j.get("error")})

@app.get("/download/{jid}")
def download(jid:str):
    j=_load(jid)
    if not j or j.get("status")!="done" or "out_path" not in j:
        raise HTTPException(404,"Not ready")
    return FileResponse(j["out_path"], filename="emails.zip", media_type="application/zip")
