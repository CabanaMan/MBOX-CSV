from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Form
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    FileResponse,
    PlainTextResponse,
    Response,
)
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import mailbox
import csv
import zipfile
import io
import uuid
import json
import hashlib
import math
from typing import Optional, Dict, Any

from email.parser import BytesHeaderParser, BytesParser
from email import policy

from pydantic import BaseModel

# --- paths ---
BASE_DIR = Path(__file__).resolve().parent
PAGES = BASE_DIR / "pages"
STATIC = BASE_DIR / "static"

# --- storage ---
DATA = Path("/data")
UP = DATA / "uploads"
JOBS = DATA / "jobs"
OUT = Path("/downloads")
for p in (DATA, UP, JOBS, OUT):
    p.mkdir(parents=True, exist_ok=True)

# --- limits / worker ---
MAX_BYTES = 20 * 1024 * 1024 * 1024
CHUNK = 16 * 1024 * 1024
BODY_LIMIT = 32000
POOL = ThreadPoolExecutor(max_workers=2)

app = FastAPI()

# --- helpers ---
def read_page(name: str) -> str:
    page_path = PAGES / name
    if not page_path.is_file():
        raise HTTPException(status_code=404, detail="Page not found")
    return page_path.read_text(encoding="utf-8")


def read_static(name: str) -> str:
    asset_path = STATIC / name
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset_path.read_text(encoding="utf-8")


HTML = """<!doctype html><html lang=\"en\"><head>
<meta charset=\"utf-8\">
<title>MBOX → CSV Email Converter | Free 20 GB Uploads</title>
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<meta name=\"description\" content=\"Convert large MBOX email archives to CSV spreadsheets in minutes. Upload up to 20 GB with resumable, checksum-verified transfers, monitor progress, and download a privacy-first ZIP export.\">
<meta name=\"keywords\" content=\"mbox to csv, email converter, export gmail mbox, pst to csv alternative, email archive to spreadsheet\">
<link rel=\"canonical\" href=\"https://mbox-csv.com/\">
<meta name=\"robots\" content=\"index,follow\">
<meta name=\"author\" content=\"MBOX-CSV\">
<meta name=\"theme-color\" content=\"#0b1020\">
<meta property=\"og:type\" content=\"website\">
<meta property=\"og:title\" content=\"MBOX → CSV Email Converter\">
<meta property=\"og:description\" content=\"Fast, secure, and free MBOX to CSV conversion with uploads up to 20 GB.\">
<meta property=\"og:url\" content=\"https://mbox-csv.com/\">
<meta property=\"og:image\" content=\"https://mbox-csv.com/static/csv-preview.svg\">
<meta name=\"twitter:card\" content=\"summary_large_image\">
<meta name=\"twitter:title\" content=\"MBOX → CSV Email Converter\">
<meta name=\"twitter:description\" content=\"Convert large MBOX archives to CSV spreadsheets with server-side parsing.\">
<link rel=\"preconnect\" href=\"https://fonts.gstatic.com\" crossorigin>
<link href=\"https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;800&display=swap\" rel=\"stylesheet\">
<script type=\"application/ld+json\">
{
  \"@context\": \"https://schema.org\",
  \"@graph\": [
    {
      \"@type\": \"SoftwareApplication\",
      \"name\": \"MBOX → CSV Email Converter\",
      \"applicationCategory\": \"UtilityApplication\",
      \"operatingSystem\": \"Web\",
      \"description\": \"Convert MBOX email archives to CSV securely online. Upload up to 20 GB with resumable transfers, parse messages server-side, and download a ZIP export.\",
      \"url\": \"https://mbox-csv.com/\",
      \"offers\": {
        \"@type\": \"Offer\",
        \"price\": \"0\",
        \"priceCurrency\": \"USD\"
      }
    },
    {
      \"@type\": \"FAQPage\",
      \"mainEntity\": [
        {
          \"@type\": \"Question\",
          \"name\": \"Can I convert very large MBOX files?\",
          \"acceptedAnswer\": {
            \"@type\": \"Answer\",
            \"text\": \"Yes. The converter accepts archives up to 20 GB and streams them directly on the server for reliable processing.\"
          }
        },
        {
          \"@type\": \"Question\",
          \"name\": \"What data is included in the CSV export?\",
          \"acceptedAnswer\": {
            \"@type\": \"Answer\",
            \"text\": \"Each row in emails.csv contains the message date, sender, recipients, subject, and the Message-ID header. Optional toggles add Gmail thread IDs, body text, and an attachments manifest.\"
          }
        },
        {
          \"@type\": \"Question\",
          \"name\": \"Do you retain my uploaded emails?\",
          \"acceptedAnswer\": {
            \"@type\": \"Answer\",
            \"text\": \"No. Files are processed in a private job directory and removed automatically after conversion completes.\"
          }
        }
      ]
    }
  ]
}
</script>
<style>
:root{
  --bg:#0b1020;--panel:#0f172a;--muted:#9aa4b2;--text:#e6e9ef;--brand:#7c5cff;--brand2:#22c55e;
  --ring:#334155;--ring2:#1f2937;--ok:#22c55e;--err:#ef4444;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:
 radial-gradient(1200px 800px at 75% -10%,#2a3458 0%,transparent 60%),
 radial-gradient(1000px 600px at -20% 40%,#1a2040 0%,transparent 55%),var(--bg);
 color:var(--text);font-family:Inter,system-ui,Segoe UI,Roboto,Arial;line-height:1.6}
.page{min-height:100%;display:flex;flex-direction:column}
.container{max-width:960px;margin:0 auto;padding:28px 24px}
.hero{padding-top:28px;padding-bottom:12px}
.nav-links{display:flex;gap:18px;margin-top:18px;flex-wrap:wrap}
.nav-links a{color:#9ecbff;text-decoration:none;font-weight:500}
.nav-links a:hover,.nav-links a:focus{color:#c4dcff;text-decoration:underline}
.hero .badge{width:16px;height:16px;border-radius:50%;background:conic-gradient(from 0deg,#7c5cff,#22c55e);box-shadow:0 0 22px #7c5cff88}
.hero h1{margin:0;font-size:32px;letter-spacing:.3px}
.hero .tagline{margin-top:8px;color:var(--muted);max-width:600px}
.panel{background:linear-gradient(180deg,#0d1428 0%,#0c1326 100%);border:1px solid var(--ring2);border-radius:18px;padding:28px;box-shadow:0 20px 60px #0007}
.panel h2{margin:0 0 12px;font-size:24px}
.drop{border:1.5px dashed var(--ring);border-radius:16px;padding:42px;text-align:center;cursor:pointer;transition:.15s;background:#0b1224}
.drop:hover{border-color:#55627a}
.drop.drag{background:#0e1a34;border-color:#7c5cff}
.drop .hint{color:var(--muted)}
.controls{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:20px}
.btn{display:inline-flex;align-items:center;gap:10px;padding:12px 18px;border:0;border-radius:12px;font-weight:600;cursor:pointer}
.btn-primary{background:linear-gradient(90deg,#7c5cff,#5b85ff);color:#0b0f1e}
.btn-ghost{background:#111a2e;color:#d8ddf5;border:1px solid #1f2a44}
.btn[disabled]{opacity:.6;cursor:not-allowed}
.options{margin-top:22px;border:1px solid #162037;border-radius:14px;padding:16px;display:flex;flex-wrap:wrap;gap:12px}
.options legend{padding:0 6px;color:#9ecbff;font-size:14px;font-weight:600}
.option{display:flex;align-items:center;gap:8px;font-size:14px;color:#cdd6e3}
.option input{width:18px;height:18px}
.progress{display:flex;align-items:center;gap:12px;margin-top:18px}
.bar{flex:1;height:12px;border-radius:999px;background:#0b1b2f;border:1px solid var(--ring2);overflow:hidden}
.fill{height:100%;width:0;background:linear-gradient(90deg,#22c55e,#7c5cff)}
.pct{min-width:160px;display:flex;justify-content:flex-end;gap:10px;color:var(--muted);font-variant-numeric:tabular-nums;text-align:right;flex-wrap:wrap}
.pct span{display:inline-block}
.pct .elapsed{opacity:.8}
.status{min-height:24px;margin-top:10px;color:#cdd6e3}
.note{margin-top:16px;color:var(--muted);font-size:14px}
.main{flex:1;display:flex;flex-direction:column;gap:36px;padding-bottom:20px}
.seo-section{background:rgba(10,16,34,.65);border:1px solid #111c32;border-radius:18px;padding:28px}
.seo-section h2{margin-top:0;font-size:22px}
.seo-section p{margin:8px 0;color:#cdd6e3}
.list-check{list-style:none;padding:0;margin:16px 0 0;display:grid;gap:12px}
.list-check li{position:relative;padding-left:28px}
.list-check li::before{content:\"✓\";position:absolute;left:0;top:0;color:var(--brand2);font-weight:700}
.seo-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-top:18px}
.seo-grid article{background:#0b1224;border:1px solid #132035;border-radius:14px;padding:18px;color:#d4d9e4}
.seo-grid h3{margin:0 0 8px;font-size:18px}
.csv-preview{margin-top:18px;border:1px solid #152038;border-radius:14px;overflow:hidden}
.csv-preview table{width:100%;border-collapse:collapse;font-size:13px}
.csv-preview th,.csv-preview td{padding:10px 14px;border-bottom:1px solid #1f2a3d;text-align:left}
.csv-preview th{background:#101a33;color:#9ecbff;text-transform:uppercase;font-size:12px;letter-spacing:.5px}
.csv-preview tbody tr:nth-child(even){background:#0e172d}
.provider-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:20px;margin-top:24px}
.provider-card{background:linear-gradient(160deg,#0b1224 0%,#121b35 100%);border:1px solid #1b2a44;border-radius:18px;padding:22px;box-shadow:0 18px 40px #00000033;display:flex;flex-direction:column;gap:14px;min-height:220px}
.provider-card header{display:flex;align-items:center;justify-content:space-between;gap:12px}
.provider-card h3{margin:0;font-size:18px;color:#f2f5ff}
.provider-tag{background:rgba(124,92,255,.12);color:#9faaf5;padding:4px 10px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.3px;text-transform:uppercase}
.provider-card p{margin:0;color:#cdd6e3;font-size:14px;line-height:1.6}
.step-list{counter-reset:step;margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px}
.step-list li{counter-increment:step;position:relative;padding-left:38px;font-size:14px;color:#d7dceb;line-height:1.55}
.step-list li::before{content:counter(step);position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;background:rgba(124,92,255,.22);color:#c7d2ff;font-weight:600;display:flex;align-items:center;justify-content:center}
.step-list a{color:#9ecbff;text-decoration:none;font-weight:500}
.step-list a:hover{color:#c4dcff}
.faq details{background:#0b1224;border:1px solid #132035;border-radius:14px;margin-top:12px;padding:16px}
.faq summary{font-weight:600;cursor:pointer;color:#e6e9ef}
.faq p{margin:12px 0 0;color:#cdd6e3}
.about-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;margin-top:18px}
.about-grid article{background:#0b1224;border:1px solid #132035;border-radius:14px;padding:18px;color:#d4d9e4}
.about-grid h3{margin:0 0 8px;font-size:18px}
.keyword-cloud{display:flex;flex-wrap:wrap;gap:10px;margin-top:16px}
.keyword-cloud span{background:rgba(124,92,255,.16);border:1px solid #1f2a44;border-radius:999px;padding:6px 14px;font-size:13px;letter-spacing:.3px;color:#c7d2ff;font-weight:600}
.trust-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:18px;margin-top:18px}
.trust-card{background:#0b1224;border:1px solid #132035;border-radius:14px;padding:18px;color:#d4d9e4;display:flex;flex-direction:column;gap:10px}
.trust-card strong{color:#9ecbff}
.ad-wrapper{margin:16px auto;width:100%;max-width:960px;padding:0 24px;text-align:center;color:var(--muted);font-size:12px}
.footer{margin:32px auto 28px;color:#7c8799;font-size:12px;text-align:center;padding:0 24px}
.footer a{color:#9ecbff;text-decoration:none}
a.dl{display:none;color:#22c55e;text-decoration:none;font-weight:600}
kbd{background:#111a2e;padding:2px 6px;border-radius:6px;border:1px solid #1e293b}
@media (max-width:720px){
  .hero h1{font-size:28px}
  .panel{padding:24px}
  .drop{padding:32px}
  .seo-section{padding:24px}
  .provider-card{padding:20px}
  .pct{justify-content:flex-start}
}
</style>
</head><body>
<div class=\"page\">
  <header class=\"hero\">
    <div class=\"container\">
      <div style=\"display:flex;align-items:center;gap:14px\">
        <div class=\"badge\" aria-hidden=\"true\"></div>
        <div>
          <h1>MBOX → CSV Email Converter</h1>
          <p class=\"tagline\">Upload up to 20 GB per file, convert everything on secure servers, and receive a clean <b>emails.csv</b> download ready for analysis.</p>
        </div>
      </div>
      <nav class=\"nav-links\" aria-label=\"Helpful links\">
        <a href=\"/how-to\">Export instructions</a>
        <a href=\"/faq\">FAQ</a>
        <a href=\"/privacy\">Privacy</a>
        <a href=\"/terms\">Terms</a>
        <a href=\"/contact\">Contact</a>
      </nav>
    </div>
  </header>

  <div class=\"ad-wrapper\" aria-label=\"Top advertisement slot\">
    <script async src=\"https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8714478254404273\" crossorigin=\"anonymous\"></script>
    <p>Advertisements are served via Google AdSense.</p>
  </div>

  <main class=\"main\">
    <div class=\"container\">
      <section class=\"panel\" aria-label=\"MBOX to CSV conversion form\">
        <h2>Convert your archive</h2>
        <div id=\"drop\" class=\"drop\" role=\"button\" tabindex=\"0\" aria-label=\"Upload area\">
          <div style=\"font-size:18px;margin-bottom:6px\">Drag &amp; drop your <b>.mbox</b> here</div>
          <div class=\"hint\">or use the buttons below to choose a file from your device</div>
          <input id=\"file\" type=\"file\" accept=\".mbox\" hidden>
        </div>

        <div class=\"controls\">
          <button id=\"browse\" class=\"btn btn-ghost\" type=\"button\">Choose a file</button>
          <button id=\"go\" class=\"btn btn-primary\" disabled>
            <svg width=\"16\" height=\"16\" viewBox=\"0 0 24 24\" fill=\"currentColor\"><path d=\"M12 2l9 4-9 4-9-4 9-4Zm0 7l9 4-9 4-9-4 9-4Zm0 7l9 4-9 4-9-4 9-4Z\"/></svg>
            Upload &amp; Convert
          </button>
          <a id=\"dl\" class=\"dl\">Download ZIP</a>
        </div>

        <fieldset class=\"options\">
          <legend>Optional fields</legend>
          <label class=\"option\"><input id=\"opt-thread\" type=\"checkbox\">Include Gmail thread IDs</label>
          <label class=\"option\"><input id=\"opt-body\" type=\"checkbox\">Include message body text (plain text)</label>
          <label class=\"option\"><input id=\"opt-attachments\" type=\"checkbox\">Generate attachments.csv manifest</label>
        </fieldset>

        <div class=\"progress\" aria-label=\"Progress\">
          <div class=\"bar\"><div id=\"fill\" class=\"fill\"></div></div>
          <div class=\"pct\"><span id=\"pct\">0%</span><span id=\"eta\" class=\"eta\">ETA --:--</span><span id=\"elapsed\" class=\"elapsed\">00:00</span></div>
        </div>

        <div id=\"status\" class=\"status\" role=\"status\" aria-live=\"polite\">Idle.</div>
        <p class=\"note\">Resumable uploads keep giant archives moving, and every chunk is verified with SHA-256 checksums before processing begins. Leave this tab open so we can start the download automatically.</p>
      </section>

      <section class=\"seo-section\" id=\"features\">
        <h2>Why choose this MBOX to CSV converter?</h2>
        <ul class=\"list-check\">
          <li>Handles archives up to 20 GB with resumable, checksum-verified uploads.</li>
          <li>Server-side parsing keeps the heavy lifting off your device while protecting your data.</li>
          <li>Optional toggles let you include Gmail thread IDs, message bodies, and an attachments manifest.</li>
          <li>Privacy-first processing — temporary files are automatically deleted after each job finishes.</li>
        </ul>
      </section>

      <section class=\"seo-section\" id=\"preview\">
        <h2>See the CSV layout</h2>
        <p>The export arrives as <code>emails.csv</code> inside <code>emails.zip</code>. Here is a preview of the default columns with body text enabled:</p>
        <figure class=\"csv-preview\">
          <table>
            <thead>
              <tr><th>date</th><th>from</th><th>to</th><th>subject</th><th>message_id</th><th>thread_id</th><th>body</th></tr>
            </thead>
            <tbody>
              <tr><td>Tue, 12 Mar 2024 09:24:10 -0500</td><td>alice@example.com</td><td>team@example.com</td><td>Kickoff notes</td><td>&lt;abc123@example.com&gt;</td><td>1782346987123</td><td>Thanks for joining the kickoff! Attached are the next steps.</td></tr>
              <tr><td>Tue, 12 Mar 2024 09:31:44 -0500</td><td>bob@example.com</td><td>alice@example.com</td><td>Re: Kickoff notes</td><td>&lt;def456@example.com&gt;</td><td>1782346987123</td><td>Appreciate the summary. I will update the brief.</td></tr>
              <tr><td>Wed, 13 Mar 2024 07:02:05 -0500</td><td>carol@example.com</td><td>team@example.com</td><td>Status update</td><td>&lt;ghi789@example.com&gt;</td><td>2789346123400</td><td>Morning! Today’s deployment is on track. CSV export scheduled for 2 PM.</td></tr>
            </tbody>
          </table>
        </figure>
        <p>When attachments are enabled an additional <code>attachments.csv</code> lists filename, content type, and size for every part.</p>
      </section>

      <section class=\"seo-section\" id=\"how-it-works\">
        <h2>How to convert an MBOX file to CSV</h2>
        <div class=\"seo-grid\">
          <article>
            <h3>1. Upload your archive</h3>
            <p>Select or drop the MBOX export from Gmail, Thunderbird, Apple Mail, or any other client. Large files resume if your connection blips.</p>
          </article>
          <article>
            <h3>2. Let the server parse it</h3>
            <p>We read each message on secure infrastructure, keeping track of progress so you always know what is happening.</p>
          </article>
          <article>
            <h3>3. Download <code>emails.csv</code></h3>
            <p>Receive a ZIP containing the CSV file with your chosen columns for spreadsheets, BI tools, and legal reviews.</p>
          </article>
        </div>
      </section>

      <section class=\"seo-section\" id=\"export-guides\">
        <h2>How to export an MBOX from popular providers</h2>
        <p>Use these quick steps to grab the right archive from your mailbox. Need more detail? Read the full <a href=\"/how-to\">email export guide</a>.</p>
        <div class=\"provider-grid\">
          <article class=\"provider-card\">
            <header>
              <h3>Gmail</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Export every label or your entire inbox with Google Takeout.</p>
            <ol class=\"step-list\">
              <li>Visit <a href=\"https://takeout.google.com\" target=\"_blank\" rel=\"noreferrer\">Google Takeout</a> and deselect all services.</li>
              <li>Enable <strong>Mail</strong>, then use “All Mail data included” if you want only certain labels.</li>
              <li>Choose a <strong>.zip</strong> export, create the archive, and unzip the downloaded <strong>.mbox</strong> files.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Outlook.com / Hotmail</h3>
              <span class=\"provider-tag\">PST → MBOX</span>
            </header>
            <p>Microsoft exports arrive as .pst. Convert them to MBOX with a desktop tool or contact us for a concierge conversion.</p>
            <ol class=\"step-list\">
              <li>Open <a href=\"https://account.microsoft.com/privacy\" target=\"_blank\" rel=\"noreferrer\">account.microsoft.com/privacy</a> → <strong>Download your data</strong>.</li>
              <li>Create a new export, choose <strong>Mail</strong>, and wait for the email notification that the PST is ready.</li>
              <li>Convert the PST to MBOX with a utility like <strong>MailStore Home</strong>, then upload the resulting <strong>.mbox</strong>.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Microsoft 365 / Outlook desktop</h3>
              <span class=\"provider-tag\">PST → MBOX</span>
            </header>
            <p>Export mailboxes with Outlook’s Import/Export wizard and convert to MBOX before uploading.</p>
            <ol class=\"step-list\">
              <li>In Outlook, go to <strong>File → Open &amp; Export → Import/Export</strong>.</li>
              <li>Select <strong>Export to a file → Outlook Data File (.pst)</strong>.</li>
              <li>Use a PST-to-MBOX converter or <a href=\"/contact\">ask support</a> for a white-glove conversion, then upload the MBOX.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Yahoo Mail</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Yahoo’s privacy dashboard offers full mailbox exports.</p>
            <ol class=\"step-list\">
              <li>Go to the <a href=\"https://mail.yahoo.com/d/folders/1\" target=\"_blank\" rel=\"noreferrer\">Yahoo Privacy Dashboard</a> → <strong>Download &amp; view your data</strong>.</li>
              <li>Request a Mail export and watch for the confirmation email.</li>
              <li>Download the archive and extract the enclosed <strong>.mbox</strong> file.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Apple Mail &amp; iCloud</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Export directly from the Mail app on macOS.</p>
            <ol class=\"step-list\">
              <li>Select the mailbox or folder you want to archive.</li>
              <li>Choose <strong>Mailbox → Export Mailbox…</strong> and pick a destination folder.</li>
              <li>The export folder contains a ready-to-upload <strong>.mbox</strong> file.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Thunderbird</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Install a free add-on to save any folder as an MBOX file.</p>
            <ol class=\"step-list\">
              <li>Install the <strong>ImportExportTools NG</strong> extension.</li>
              <li>Right-click a folder → <strong>Export folder</strong> → choose <strong>MBOX</strong>.</li>
              <li>Repeat for extra folders or use “Export all folders” to batch them.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Proton Mail</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Paid plans unlock Proton’s Import-Export desktop app.</p>
            <ol class=\"step-list\">
              <li>Download the Import-Export tool from your Proton Mail account settings.</li>
              <li>Sign in, select the mailboxes to export, and choose the <strong>MBOX</strong> format.</li>
              <li>Upload the generated archive once the export finishes.</li>
            </ol>
          </article>
          <article class=\"provider-card\">
            <header>
              <h3>Zoho Mail</h3>
              <span class=\"provider-tag\">MBOX</span>
            </header>
            <p>Admins can export any mailbox from Zoho’s settings.</p>
            <ol class=\"step-list\">
              <li>Open <strong>Settings → Import/Export</strong> in the Zoho Mail admin console.</li>
              <li>Select <strong>Export</strong>, choose the folder or account, and pick <strong>MBOX</strong>.</li>
              <li>Start the export and download the <strong>.mbox</strong> file when notified.</li>
            </ol>
          </article>
        </div>
      </section>

      <section class=\"seo-section\" id=\"about\">
        <h2>About mbox-csv.com</h2>
        <p><strong>mbox-csv.com</strong> is a focused utility built for teams that need a dependable way to turn raw email archives into spreadsheets. Search engines sometimes surface generic converters; this is the original hosted app designed specifically for <em>MBOX to CSV</em> workflows.</p>
        <div class=\"about-grid\">
          <article>
            <h3>Built for analysts</h3>
            <p>Every conversion produces a consistent header row and UTF-8 output so your BI tools, CRM imports, or audit spreadsheets work without cleanup.</p>
          </article>
          <article>
            <h3>Secure processing</h3>
            <p>Jobs run in isolated directories, links are unique per upload, and files are deleted automatically after delivery.</p>
          </article>
          <article>
            <h3>Why researchers trust us</h3>
            <p>Unlike desktop scripts or unmaintained projects, mbox-csv.com handles multi-gigabyte archives in the cloud with progress tracking and a published privacy program.</p>
          </article>
        </div>
        <div class=\"keyword-cloud\" aria-label=\"Popular searches\">
          <span>mbox csv converter</span>
          <span>mbox-csv.com</span>
          <span>convert gmail mbox to csv</span>
          <span>mbox email export</span>
          <span>mbox to spreadsheet</span>
        </div>
        <p style=\"margin-top:18px\">Need a hand? <a href=\"/contact\">Email the operator</a> and we will help with stuck archives or custom data pulls.</p>
      </section>

      <section class=\"seo-section\" id=\"trust\">
        <h2>Security and trust</h2>
        <div class=\"trust-grid\">
          <div class=\"trust-card\">
            <strong>HTTPS everywhere</strong>
            <p>SSL/TLS 1.3 is enforced across the app. Uploads, downloads, and API calls are encrypted in transit.</p>
          </div>
          <div class=\"trust-card\">
            <strong>Automatic deletion</strong>
            <p>Temporary files are purged within 24 hours or immediately after your download completes.</p>
          </div>
          <div class=\"trust-card\">
            <strong>Checksum verification</strong>
            <p>Each upload chunk is verified with SHA-256 before processing begins, preventing corrupt exports.</p>
          </div>
          <div class=\"trust-card\">
            <strong>Human support</strong>
            <p>Have compliance questions? <a href=\"/contact\">Contact support</a> for a written data handling summary.</p>
          </div>
        </div>
      </section>

      <section class=\"seo-section\" id=\"faq\">
        <h2>Frequently asked questions</h2>
        <div class=\"faq\">
          <details>
            <summary>Can I convert MBOX files created by Google Takeout?</summary>
            <p>Yes. Google Takeout exports Gmail mailboxes as standard MBOX archives that work perfectly with this converter.</p>
          </details>
          <details>
            <summary>Is there a limit to how many times I can use the tool?</summary>
            <p>You can submit multiple jobs. Each upload can be up to 20 GB, and you can start another conversion as soon as the previous one finishes.</p>
          </details>
          <details>
            <summary>Can I upload PST files directly?</summary>
            <p>PST support is available through our concierge service. Convert the PST to MBOX with a desktop tool or <a href=\"/contact\">email support</a> and we will handle it for you.</p>
          </details>
          <details>
            <summary>What extras do the toggles add?</summary>
            <p><strong>Thread IDs</strong> add Gmail’s <code>X-GM-THRID</code> value, <strong>message body</strong> adds the plain-text portion (trimmed to 32K characters), and <strong>attachments.csv</strong> lists filenames, content types, and approximate sizes.</p>
            <p style=\"margin-top:10px\"><img src=\"/static/csv-preview.svg\" alt=\"Screenshot of the CSV output\" style=\"max-width:100%;border:1px solid #1f2a3d;border-radius:12px\"></p>
          </details>
          <details>
            <summary>How do I fix upload errors?</summary>
            <p>If you see a “file too large” message, the archive exceeded 20 GB. Split the export and retry. For “Not ready” download errors, the job may still be processing—wait for the status to show <strong>Done</strong> and refresh. Persistent issues? <a href=\"/contact\">Contact support</a> with the job ID.</p>
          </details>
        </div>
      </section>
    </div>
  </main>

  <div class=\"ad-wrapper\" aria-label=\"Bottom advertisement slot\">
    <script async src=\"https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client=ca-pub-8714478254404273\" crossorigin=\"anonymous\"></script>
    <p>Advertisements are served via Google AdSense.</p>
  </div>

  <footer class=\"footer\">mbox-csv.com • <a href=\"/privacy\">Privacy Policy</a> • <a href=\"/terms\">Terms of Service</a> • <a href=\"/contact\">Contact</a></footer>
</div>
<script>
const $=s=>document.querySelector(s);
const drop=$("#drop"), file=$("#file"), browse=$("#browse"), go=$("#go"), fill=$("#fill"), pct=$("#pct"), eta=$("#eta"), elapsed=$("#elapsed"), st=$("#status"), dl=$("#dl"), optThread=$("#opt-thread"), optBody=$("#opt-body"), optAttachments=$("#opt-attachments");
const DEFAULT_UPLOAD_WEIGHT=0.6;
const DEFAULT_PARSE_FALLBACK_SECONDS=45;
const progressState={
  upload:{total:0,uploaded:0,startedAt:null,completed:false,completedAt:null,duration:0},
  parse:{total:0,processed:0,startedAt:null,completed:false,completedAt:null}
};
let selected=null, job=null, poll=null, timer=null, startedAt=null;

function setPct(v){ fill.style.width=v+"%"; pct.textContent=Math.min(100,Math.floor(v)) + "%" }
function renderElapsed(ms){
  const totalSeconds = Math.max(0, Math.floor(ms/1000));
  const hours = Math.floor(totalSeconds/3600);
  const minutes = Math.floor((totalSeconds%3600)/60);
  const seconds = totalSeconds%60;
  if(hours){
    elapsed.textContent = `${hours}:${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
  } else {
    elapsed.textContent = `${String(minutes).padStart(2,"0")}:${String(seconds).padStart(2,"0")}`;
  }
}
function renderEta(seconds){
  if(!Number.isFinite(seconds) || seconds < 0){
    eta.textContent = "ETA --:--";
    return;
  }
  const totalSeconds = Math.ceil(seconds);
  const hours = Math.floor(totalSeconds/3600);
  const minutes = Math.floor((totalSeconds%3600)/60);
  const secs = totalSeconds%60;
  if(hours){
    eta.textContent = `ETA ${hours}:${String(minutes).padStart(2,"0")}:${String(secs).padStart(2,"0")}`;
  } else {
    eta.textContent = `ETA ${String(minutes).padStart(2,"0")}:${String(secs).padStart(2,"0")}`;
  }
}
function resetProgressTracking(){
  progressState.upload.total=0;
  progressState.upload.uploaded=0;
  progressState.upload.startedAt=null;
  progressState.upload.completed=false;
  progressState.upload.completedAt=null;
  progressState.upload.duration=0;
  progressState.parse.total=0;
  progressState.parse.processed=0;
  progressState.parse.startedAt=null;
  progressState.parse.completed=false;
  progressState.parse.completedAt=null;
}
function beginJobTracking(totalBytes){
  resetProgressTracking();
  progressState.upload.total=totalBytes||0;
  progressState.upload.startedAt=Date.now();
  updateProgress();
}
function updateProgress(){
  const now=Date.now();
  const upload=progressState.upload;
  const parse=progressState.parse;
  const uploadTotal=upload.total||0;
  const uploadFraction=uploadTotal>0?Math.min(1,upload.uploaded/uploadTotal):0;
  const uploadElapsedSeconds=upload.startedAt?((upload.completedAt||now)-upload.startedAt)/1000:0;
  const uploadDuration=upload.completed?upload.duration:uploadElapsedSeconds;
  let parseFraction=0;
  const parseTotal=parse.total||0;
  if(parse.completed){
    parseFraction=1;
  }else if(parseTotal>0 && parse.processed>=0){
    parseFraction=Math.min(1,parse.processed/parseTotal);
  }
  const parseElapsedSeconds=parse.startedAt?((parse.completedAt||now)-parse.startedAt)/1000:0;
  let parseEstimatedTotal=null;
  if(parseFraction>0){
    parseEstimatedTotal=parseElapsedSeconds/parseFraction;
  }else if(parse.completed){
    parseEstimatedTotal=parseElapsedSeconds;
  }
  let uploadWeight=DEFAULT_UPLOAD_WEIGHT;
  let parseWeight=1-DEFAULT_UPLOAD_WEIGHT;
  if(parseEstimatedTotal!==null && uploadDuration>0){
    const totalTime=uploadDuration+parseEstimatedTotal;
    if(totalTime>0){
      uploadWeight=uploadDuration/totalTime;
      parseWeight=parseEstimatedTotal/totalTime;
    }
  }
  const progressFraction=(uploadFraction*uploadWeight)+(parseFraction*parseWeight);
  setPct(progressFraction*100);
  let remainingSeconds=0;
  if(uploadFraction<1 && uploadWeight>0){
    if(uploadFraction>0){
      const estimatedUploadTotal=uploadElapsedSeconds/Math.max(uploadFraction,1e-6);
      const uploadRemaining=estimatedUploadTotal-uploadElapsedSeconds;
      if(uploadRemaining>0){
        remainingSeconds+=uploadRemaining;
      }
    }
  }
  if(parseWeight>0 && parseFraction<1){
    if(parseEstimatedTotal!==null){
      const parseRemaining=parseEstimatedTotal-parseElapsedSeconds;
      if(parseRemaining>0){
        remainingSeconds+=parseRemaining;
      }
    }else if(parse.startedAt){
      remainingSeconds+=DEFAULT_PARSE_FALLBACK_SECONDS;
    }
  }
  if(remainingSeconds>0){
    renderEta(remainingSeconds);
  }else if(uploadFraction>=1 && parseFraction>=1){
    renderEta(0);
  }else{
    renderEta(NaN);
  }
}
function updateUploadMetrics(uploaded,total){
  const now=Date.now();
  if(total>0){
    progressState.upload.total=total;
  }
  progressState.upload.uploaded=Math.min(progressState.upload.total,Math.max(0,uploaded));
  if(!progressState.upload.startedAt){
    progressState.upload.startedAt=now;
  }
  updateProgress();
}
function markUploadComplete(){
  const now=Date.now();
  if(!progressState.upload.startedAt){
    progressState.upload.startedAt=now;
  }
  progressState.upload.completed=true;
  progressState.upload.completedAt=now;
  progressState.upload.uploaded=progressState.upload.total;
  progressState.upload.duration=(now-progressState.upload.startedAt)/1000;
  updateProgress();
}
function updateParseTracking(status,processed,totalMessages){
  const now=Date.now();
  if(status==="queued" || status==="processing" || status==="done"){
    if(!progressState.parse.startedAt){
      progressState.parse.startedAt=now;
    }
  }
  if(Number.isFinite(totalMessages) && totalMessages>=0){
    progressState.parse.total=Math.max(progressState.parse.total,totalMessages);
  }
  if(Number.isFinite(processed) && processed>=0){
    progressState.parse.processed=processed;
    if(progressState.parse.total>0 && processed>progressState.parse.total){
      progressState.parse.total=processed;
    }
  }
  if(status==="done"){
    progressState.parse.completed=true;
    progressState.parse.completedAt=now;
    if(progressState.parse.total===0 && Number.isFinite(processed)){
      progressState.parse.total=Math.max(0,processed);
    }
  }else if(status==="error"){
    progressState.parse.completed=false;
    progressState.parse.completedAt=null;
  }else if(status==="queued" || status==="processing"){
    progressState.parse.completed=false;
    progressState.parse.completedAt=null;
  }
  updateProgress();
}
function resetTimer(){
  if(timer){ clearInterval(timer); timer=null; }
  startedAt=null;
  renderElapsed(0);
  renderEta(NaN);
}
function startTimer(){
  resetTimer();
  startedAt=Date.now();
  timer=setInterval(()=>{
    if(!startedAt) return;
    renderElapsed(Date.now()-startedAt);
  },1000);
}
function stopTimer(){
  if(timer){ clearInterval(timer); timer=null; }
  if(startedAt){ renderElapsed(Date.now()-startedAt); }
  startedAt=null;
}
resetProgressTracking();
updateProgress();
resetTimer();
function setSt(t){ st.textContent=t }

drop.addEventListener("click",()=>file.click());
drop.addEventListener("keydown",e=>{ if(e.key==="Enter"||e.key===" "){ e.preventDefault(); file.click(); }});
["dragover","dragenter"].forEach(evn=>drop.addEventListener(evn,e=>{e.preventDefault();drop.classList.add("drag")}));
["dragleave","drop"].forEach(evn=>drop.addEventListener(evn,()=>drop.classList.remove("drag")));
drop.addEventListener("drop",e=>{
  e.preventDefault();
  if(!e.dataTransfer.files.length) return;
  selected = e.dataTransfer.files[0];
  drop.querySelector(".hint").innerHTML = `<b>Selected:</b> ${selected.name}`;
  go.disabled = false;
  resetProgressTracking();
  updateProgress();
  setSt("Ready.");
  resetTimer();
});
file.addEventListener("change",e=>{
  if(!e.target.files.length) return;
  selected = e.target.files[0];
  drop.querySelector(".hint").innerHTML = `<b>Selected:</b> ${selected.name}`;
  go.disabled = false;
  resetProgressTracking();
  updateProgress();
  setSt("Ready.");
  resetTimer();
});
browse.addEventListener("click",()=>file.click());

async function sha256Hex(buffer){
  const hashBuffer = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(hashBuffer)).map(b=>b.toString(16).padStart(2,"0")).join("");
}

async function uploadChunks(chunkSize){
  const total = selected.size;
  if(total === 0){ throw new Error("File is empty"); }
  const totalChunks = Math.ceil(total / chunkSize);
  let uploaded = 0;
  for(let index=0; index<totalChunks; index++){
    const start = index * chunkSize;
    const end = Math.min(start + chunkSize, total);
    const slice = selected.slice(start, end);
    const arrayBuffer = await slice.arrayBuffer();
    const hash = await sha256Hex(arrayBuffer);
    const form = new FormData();
    form.append("job_id", job);
    form.append("index", String(index));
    form.append("total", String(totalChunks));
    form.append("final", String(index === totalChunks - 1));
    form.append("chunk_hash", hash);
    form.append("chunk", new Blob([arrayBuffer]));
    const res = await fetch("/upload/chunk", { method:"POST", body: form });
    if(!res.ok){
      const text = await res.text();
      throw new Error(text || `Chunk upload failed (${res.status})`);
    }
    uploaded += arrayBuffer.byteLength;
    updateUploadMetrics(uploaded,total);
    setSt(`Uploading… ${index+1}/${totalChunks}`);
  }
}

go.addEventListener("click",async()=>{
  if(!selected) return;
  go.disabled=true; dl.style.display="none"; setSt("Preparing upload…");
  if(poll){ clearInterval(poll); poll=null; }
  startTimer();
  beginJobTracking(selected.size);
  try{
    const initPayload = {
      filename: selected.name,
      size: selected.size,
      include_body: optBody.checked,
      include_thread_id: optThread.checked,
      include_attachments: optAttachments.checked
    };
    const initRes = await fetch("/upload/init", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(initPayload)});
    if(!initRes.ok){
      const text = await initRes.text();
      throw new Error(text || `Init failed (${initRes.status})`);
    }
    const init = await initRes.json();
    job = init.job_id;
    renderEta(NaN);
    await uploadChunks(init.chunk_size);
    markUploadComplete();
    setSt("Upload complete. Parsing…");
    poll = setInterval(async ()=>{
      try{
        const r = await fetch("/status/"+job).then(r=>r.json());
        updateParseTracking(r.status, r.processed ?? null, r.total_messages ?? null);
        if(r.status==="processing"){
          const processed=r.processed||0;
          const total=r.total_messages;
          if(Number.isFinite(total) && total>0){
            setSt(`Parsing… ${processed.toLocaleString()} / ${total.toLocaleString()} messages`);
          }else{
            setSt(`Parsing… ${processed.toLocaleString()} messages`);
          }
        }
        else if(r.status==="queued"){
          setSt("Queued for parsing…");
        }
        else if(r.status==="done"){
          clearInterval(poll); poll=null;
          dl.href="/download/"+job; dl.download="emails.zip"; dl.style.display="inline";
          dl.click(); setSt("Done."); go.disabled=false; stopTimer(); renderEta(0);
        } else if(r.status==="error"){
          clearInterval(poll); poll=null; setSt("Error: "+(r.error||"unknown")); go.disabled=false; stopTimer(); renderEta(NaN);
        }
      }catch(err){
        clearInterval(poll); poll=null; setSt("Error checking status."); go.disabled=false; stopTimer(); renderEta(NaN);
      }
    }, 1500);
  }catch(err){
    setSt(err.message || "Upload failed");
    go.disabled=false; stopTimer(); renderEta(NaN);
  }
});
</script>
</body></html>
"""


class UploadInit(BaseModel):
    filename: str
    size: int
    sha256: Optional[str] = None
    include_body: bool = False
    include_thread_id: bool = False
    include_attachments: bool = False


def _jpath(jid: str) -> Path:
    return JOBS / f"{jid}.json"


def _load(jid: str) -> Optional[Dict]:
    p = _jpath(jid)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _save(obj: Dict) -> None:
    _jpath(obj["id"]).write_text(json.dumps(obj))


def _cleanup_job(jid: str, out_path: str) -> None:
    try:
        Path(out_path).unlink(missing_ok=True)
    except Exception:
        pass
    try:
        _jpath(jid).unlink(missing_ok=True)
    except Exception:
        pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_body_text(message) -> str:
    try:
        if message.is_multipart():
            for part in message.walk():
                if part.get_filename():
                    continue
                if part.get_content_type() == "text/plain":
                    try:
                        text = part.get_content()
                    except Exception:
                        payload = part.get_payload(decode=True) or b""
                        charset = part.get_content_charset() or "utf-8"
                        text = payload.decode(charset, errors="replace")
                    text = text.strip()
                    if text:
                        return text[:BODY_LIMIT]
        else:
            if message.get_content_type() == "text/plain":
                try:
                    text = message.get_content()
                except Exception:
                    payload = message.get_payload(decode=True) or b""
                    charset = message.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                return text.strip()[:BODY_LIMIT]
    except Exception:
        return ""
    return ""


def _iter_attachment_rows(message, message_id: str):
    if not hasattr(message, "iter_attachments"):
        return
    index = 0
    for part in message.iter_attachments():
        index += 1
        filename = part.get_filename() or f"attachment-{index}"
        content_type = part.get_content_type() or ""
        size_bytes = 0
        try:
            payload = part.get_payload(decode=True)
            if payload:
                size_bytes = len(payload)
        except Exception:
            size_bytes = 0
        yield (message_id, filename, content_type, size_bytes)


def _normalize_options(options: Optional[Dict]) -> Dict[str, bool]:
    options = options or {}
    return {
        "include_body": bool(options.get("include_body")),
        "include_thread_id": bool(options.get("include_thread_id")),
        "include_attachments": bool(options.get("include_attachments")),
    }


def _coerce_header_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    for attr in ("value", "_value"):
        attr_value = getattr(value, attr, None)
        if isinstance(attr_value, str):
            return attr_value
    addresses = getattr(value, "addresses", None)
    if addresses:
        rendered = []
        for addr in addresses:
            addr_spec = getattr(addr, "addr_spec", "") or ""
            display = getattr(addr, "display_name", "") or ""
            if display and addr_spec:
                rendered.append(f"{display} <{addr_spec}>")
            elif addr_spec:
                rendered.append(addr_spec)
            else:
                fallback = getattr(addr, "value", None)
                if isinstance(fallback, str) and fallback:
                    rendered.append(fallback)
        if rendered:
            return ", ".join(rendered)
    encode = getattr(value, "encode", None)
    if callable(encode):
        try:
            encoded = encode()
            if isinstance(encoded, str):
                return encoded
        except Exception:
            pass
    try:
        return str(value)
    except Exception:
        return ""


def _header_value(msg, name: str) -> str:
    try:
        raw_value = msg.get(name)
    except Exception:
        return ""
    return _coerce_header_value(raw_value)


def _parse_job(jid: str) -> None:
    j = _load(jid)
    if not j:
        return
    j["status"] = "processing"
    j["processed"] = 0
    j["total_messages"] = j.get("total_messages", 0)
    _save(j)
    src = Path(j["in_path"])
    out_zip = OUT / f"{jid}-emails.zip"
    options = _normalize_options(j.get("options"))
    include_body = options["include_body"]
    include_thread = options["include_thread_id"]
    include_attachments = options["include_attachments"]
    header_fields = ["date", "from", "to", "cc", "bcc", "subject", "message_id"]
    if include_thread:
        header_fields.append("thread_id")
    if include_body:
        header_fields.append("body")
    attachments_fields = ["message_id", "filename", "content_type", "size_bytes"]
    try:
        m = mailbox.mbox(str(src))
        header_parser = BytesHeaderParser()
        full_parser = BytesParser(policy=policy.default)
        processed = 0
        try:
            total_messages = len(m)
        except Exception:
            total_messages = 0
        j["total_messages"] = total_messages
        j["processed"] = 0
        _save(j)
        try:
            with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                with zf.open("emails.csv", "w") as emails_member:
                    with io.TextIOWrapper(emails_member, encoding="utf-8", newline="") as emails_txt:
                        writer = csv.writer(emails_txt)
                        writer.writerow(header_fields)
                        attachments_txt = None
                        attachments_writer = None
                        if include_attachments:
                            attachments_member = zf.open("attachments.csv", "w")
                            attachments_txt = io.TextIOWrapper(attachments_member, encoding="utf-8", newline="")
                            attachments_writer = csv.writer(attachments_txt)
                            attachments_writer.writerow(attachments_fields)
                        update_interval = max(1, total_messages // 200) if total_messages else 50000
                        try:
                            for idx, key in enumerate(m.iterkeys(), 1):
                                with m.get_file(key) as msg_fp:
                                    if include_body or include_attachments:
                                        msg = full_parser.parse(msg_fp)
                                    else:
                                        msg = header_parser.parse(msg_fp, headersonly=True)
                                message_id = _header_value(msg, "Message-Id")
                                row = [
                                    _header_value(msg, "Date"),
                                    _header_value(msg, "From"),
                                    _header_value(msg, "To"),
                                    _header_value(msg, "Cc"),
                                    _header_value(msg, "Bcc"),
                                    _header_value(msg, "Subject"),
                                    message_id,
                                ]
                                if include_thread:
                                    row.append(_header_value(msg, "X-GM-THRID"))
                                if include_body:
                                    row.append(_extract_body_text(msg))
                                writer.writerow(row)
                                if include_attachments and attachments_writer:
                                    for attachment_row in _iter_attachment_rows(msg, message_id):
                                        attachments_writer.writerow(attachment_row)
                                processed = idx
                                if processed % update_interval == 0:
                                    j["processed"] = processed
                                    _save(j)
                        finally:
                            if attachments_txt:
                                attachments_txt.flush()
                                attachments_txt.close()
            j["status"] = "done"
            j["processed"] = processed
            j["total_messages"] = total_messages
            j["out_path"] = str(out_zip)
            _save(j)
        finally:
            try:
                m.close()
            except Exception:
                pass
    except Exception as e:
        j["status"] = "error"
        j["error"] = str(e)
        _save(j)
    finally:
        try:
            src.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/", response_class=HTMLResponse)
def home():
    return HTML


@app.head("/")
def head_ok():
    return Response(status_code=200)


@app.get("/how-to", response_class=HTMLResponse)
def how_to():
    return read_page("how-to.html")


@app.head("/how-to")
def how_to_head():
    return Response(status_code=200)


@app.get("/faq", response_class=HTMLResponse)
def faq():
    return read_page("faq.html")


@app.head("/faq")
def faq_head():
    return Response(status_code=200)


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return read_page("privacy.html")


@app.head("/privacy")
def privacy_head():
    return Response(status_code=200)


@app.get("/terms", response_class=HTMLResponse)
def terms():
    return read_page("terms.html")


@app.head("/terms")
def terms_head():
    return Response(status_code=200)


@app.get("/contact", response_class=HTMLResponse)
def contact():
    return read_page("contact.html")


@app.head("/contact")
def contact_head():
    return Response(status_code=200)


@app.get("/support", response_class=HTMLResponse)
def support():
    return read_page("support.html")


@app.head("/support")
def support_head():
    return Response(status_code=200)


@app.get("/robots.txt")
def robots():
    txt = (PAGES / "robots.txt").read_text(encoding="utf-8")
    return Response(
        txt,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.head("/robots.txt")
def robots_head():
    return Response(status_code=200)


@app.get("/sitemap.xml")
def sitemap():
    xml = (PAGES / "sitemap.xml").read_text(encoding="utf-8")
    return Response(
        xml,
        media_type="application/xml; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.head("/sitemap.xml")
def sitemap_head():
    return Response(status_code=200)


@app.get("/ads.txt", response_class=PlainTextResponse)
def ads_txt():
    return read_static("ads.txt")


@app.head("/ads.txt")
def ads_head():
    return Response(status_code=200)


@app.post("/upload/init")
async def upload_init(payload: UploadInit):
    if payload.size <= 0:
        raise HTTPException(400, "File is empty")
    if payload.size > MAX_BYTES:
        raise HTTPException(413, "File too large (max 20 GB)")
    jid = uuid.uuid4().hex
    dst = UP / f"{jid}.upload"
    dst.write_bytes(b"")
    job = {
        "id": jid,
        "status": "uploading",
        "size": payload.size,
        "filename": payload.filename,
        "in_path": str(dst),
        "received": 0,
        "next_index": 0,
        "expected_chunks": max(1, math.ceil(payload.size / CHUNK)),
        "sha256": payload.sha256,
        "total_messages": 0,
        "options": {
            "include_body": payload.include_body,
            "include_thread_id": payload.include_thread_id,
            "include_attachments": payload.include_attachments,
        },
    }
    _save(job)
    return JSONResponse({"job_id": jid, "chunk_size": CHUNK})


@app.post("/upload/chunk")
async def upload_chunk(
    job_id: str = Form(...),
    index: int = Form(...),
    total: int = Form(...),
    final: bool = Form(False),
    chunk_hash: str = Form(...),
    chunk: UploadFile = File(...),
):
    job = _load(job_id)
    if not job:
        raise HTTPException(404, "Unknown job")
    if job.get("status") not in {"uploading", "queued"}:
        raise HTTPException(409, "Job no longer accepts chunks")
    expected_index = job.get("next_index", 0)
    if index != expected_index:
        raise HTTPException(409, f"Unexpected chunk index {index}, expected {expected_index}")
    data = await chunk.read()
    if not data:
        raise HTTPException(400, "Empty chunk")
    digest = hashlib.sha256(data).hexdigest()
    if digest != chunk_hash:
        raise HTTPException(400, "Checksum mismatch")
    received = job.get("received", 0) + len(data)
    if received > job.get("size", MAX_BYTES):
        raise HTTPException(400, "Received more data than declared")
    with open(job["in_path"], "ab") as dest:
        dest.write(data)
    job["received"] = received
    job["next_index"] = index + 1
    job["expected_chunks"] = total
    _save(job)
    if final:
        if received != job.get("size"):
            raise HTTPException(400, "Size mismatch on finalize")
        if job.get("sha256"):
            file_hash = _sha256_file(Path(job["in_path"]))
            if file_hash != job["sha256"]:
                raise HTTPException(400, "Final checksum mismatch")
        final_path = Path(job["in_path"]).with_suffix(".mbox")
        Path(job["in_path"]).rename(final_path)
        job["in_path"] = str(final_path)
        job["status"] = "queued"
        _save(job)
        POOL.submit(_parse_job, job_id)
        return JSONResponse({"status": "queued"})
    return JSONResponse({"status": "partial", "received": received})


@app.post("/upload")
async def legacy_upload(file: UploadFile = File(...)):
    """Legacy single-request upload kept for compatibility."""
    jid = uuid.uuid4().hex
    dst = UP / f"{jid}.mbox"
    total = 0
    with dst.open("wb") as f:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BYTES:
                dst.unlink(missing_ok=True)
                raise HTTPException(413, "File too large (max 20 GB)")
            f.write(chunk)
    job = {
        "id": jid,
        "status": "queued",
        "size": total,
        "filename": file.filename or "upload.mbox",
        "in_path": str(dst),
        "total_messages": 0,
        "options": {
            "include_body": False,
            "include_thread_id": False,
            "include_attachments": False,
        },
    }
    _save(job)
    POOL.submit(_parse_job, jid)
    return JSONResponse({"job_id": jid})


@app.get("/status/{jid}")
def status(jid: str):
    j = _load(jid)
    if not j:
        return JSONResponse({"status": "unknown"}, status_code=404)
    return JSONResponse(
        {
            "status": j["status"],
            "processed": j.get("processed"),
            "received": j.get("received"),
            "size": j.get("size"),
            "total_messages": j.get("total_messages"),
            "error": j.get("error"),
        }
    )


@app.get("/download/{jid}")
def download(jid: str, background_tasks: BackgroundTasks):
    j = _load(jid)
    if not j or j.get("status") != "done" or "out_path" not in j:
        raise HTTPException(404, "Not ready")
    j["status"] = "downloaded"
    _save(j)
    background_tasks.add_task(_cleanup_job, jid, j["out_path"])
    return FileResponse(j["out_path"], filename="emails.zip", media_type="application/zip")

