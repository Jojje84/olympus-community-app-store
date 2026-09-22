#!/usr/bin/env python3
import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP=Path(os.environ.get('FORGECORE_APP_ROOT','/forgecore/app')); CFG=APP/'config'; RD=CFG/'runners'; ST=APP/'state'; GC=CFG/'forgecore.env'
REPO=re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'); NAME=re.compile(r'^[A-Za-z0-9_.-]{0,63}$'); LABELS=re.compile(r'^[A-Za-z0-9_.-]+(?:,[A-Za-z0-9_.-]+)*$'); TOKEN=re.compile(r'^[A-Za-z0-9_-]{10,300}$')
HTML=r'''<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>ForgeCore</title><style>
:root{color-scheme:dark;--bg:#0b1017;--p:#121923;--b:#263142;--t:#f5f7fb;--m:#9ba8bb;--ok:#45d483;--a:#f59e0b;--bad:#fb7185}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:14px system-ui}main{max-width:1000px;margin:auto;padding:28px 18px}header,.row,.head,.actions{display:flex;align-items:center;gap:10px}header{margin-bottom:20px}.logo{display:grid;place-items:center;width:55px;height:55px;border:1px solid var(--b);border-radius:15px;color:var(--a);font-size:27px}h1,h2,p{margin:0}h1{font-size:30px}.muted,.sub,footer{color:var(--m)}.badge{margin-left:auto;border:1px solid #6b4d16;background:#231b0d;color:#fbbf24;padding:5px 9px;border-radius:99px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.card,.section{background:var(--p);border:1px solid var(--b);border-radius:16px;padding:17px}.value{font-size:22px;font-weight:700;margin-top:6px}.dot{width:10px;height:10px;border-radius:50%;background:var(--ok)}.dot.off{background:#667085}.dot.bad{background:var(--bad)}.bar{height:7px;background:#202a39;border-radius:20px;margin-top:10px;overflow:hidden}.bar i{display:block;height:100%;background:var(--ok)}.section{margin-top:13px}.head{justify-content:space-between;margin-bottom:12px}.runner{display:flex;justify-content:space-between;padding:11px;border:1px solid #202b3a;border-radius:12px;background:#0f1620;margin-top:8px}.repo{font-weight:700}.sub{font-size:12px;margin-top:4px}button,.btn{border:0;border-radius:9px;padding:9px 12px;font-weight:700;background:var(--a);color:#17110a;cursor:pointer;text-decoration:none}.secondary{background:#202a39;color:var(--t);border:1px solid #344154}details{margin-top:10px}summary{cursor:pointer;font-weight:700;color:#f3c969}form{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:12px}.full,.actions{grid-column:1/-1}label{display:grid;gap:5px;color:#c4cfdd}input{width:100%;padding:10px;border:1px solid #344154;border-radius:9px;background:#0d141d;color:var(--t)}.msg{margin-top:8px}.ok{color:var(--ok)}.badtext{color:var(--bad)}footer{margin-top:16px}@media(max-width:760px){.grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.grid,form{grid-template-columns:1fr}.full,.actions{grid-column:auto}.head{align-items:flex-start;flex-direction:column}}
</style></head><body><main><header><div class=logo>⚒</div><div><h1>ForgeCore</h1><div class=muted>Self-hosted CI on Umbrel</div></div><span class=badge>beta.9</span></header>
<section class=grid><div class=card><div class=muted>Runners</div><div class=row><span id=rd class="dot off"></span><div id=rs class=value>Starting…</div></div><div id=rn class=sub>Waiting</div></div><div class=card><div class=muted>Storage</div><div id=dv class=value>—</div><div class=bar><i id=db></i></div><div id=dp class=sub>External storage</div></div><div class=card><div class=muted>Docker</div><div class=row><span id=dd class="dot off"></span><div id=ds class=value>Checking…</div></div><div class=sub>Isolated CI engine</div></div><div class=card><div class=muted>Cleanup</div><div id=cv class=value>7 days</div><div id=cs class=sub>Cache max age: 14 days</div></div></section>
<section class=section><div class=head><div><h2>GitHub runners</h2><div class=muted>Add or repair repositories without SSH.</div></div><button id=restart class=secondary>Restart runners</button></div><div id=list></div><details><summary>+ Add or repair repository</summary><form id=f><label class=full>GitHub repository<input id=repo placeholder="Jojje84/ForgeCore" required></label><label class=full>Registration token<input id=token type=password placeholder="GitHub → Settings → Actions → Runners" autocomplete=off required></label><label>Runner name<input id=name placeholder=beelink-forgecore></label><label>Labels<input id=labels value="beelink,forgecore"></label><div class=actions><button>Connect runner</button><a id=setup class="btn secondary" target=_blank rel=noopener href=https://github.com/>Open GitHub runner setup</a></div></form><div id=fm class=msg></div></details></section>
<section class=section><div class=head><div><h2>Maintenance</h2><div id=ci class=muted>Remove stale CI data using ForgeCore settings.</div></div><button id=cleanup class=secondary>Run cleanup now</button></div><div id=am class=msg></div></section><footer id=up>ForgeCore status</footer></main><script>
const $=x=>document.getElementById(x),e=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function dot(id,on,bad=false){$(id).className='dot'+(on?'':' off')+(bad?' bad':'')};function link(){let r=$('repo').value.trim();$('setup').href=/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(r)?'https://github.com/'+r+'/settings/actions/runners/new':'https://github.com/'}$('repo').oninput=link;
async function api(p,o={}){let r=await fetch(p,{cache:'no-store',headers:{'Content-Type':'application/json'},...o}),d={};try{d=await r.json()}catch{}if(!r.ok)throw Error(d.error||'Request failed: '+r.status);return d}
async function refresh(){try{let s=await api('/api/status');$('rs').textContent=s.runner_online?'Online':'Offline';$('rn').textContent=s.runner_name||'Runner not configured';dot('rd',!!s.runner_online);$('ds').textContent=s.docker_online?'Running':'Offline';dot('dd',!!s.docker_online);let u=Number(s.disk_used_percent||0);$('dv').textContent=(s.disk_used||'—')+' / '+(s.disk_total||'—');$('dp').textContent=(s.disk_path||'External storage')+' · '+u+'% used';$('db').style.width=Math.max(0,Math.min(100,u))+'%';$('cv').textContent=(s.cleanup_interval_days||7)+' days';$('cs').textContent='Cache max age: '+(s.cache_max_age_days||14)+' days';$('list').innerHTML=s.runners?.length?s.runners.map(r=>`<div class=runner><div><div class=row><span class="dot ${r.online?'':'off'} ${r.error?'bad':''}"></span><span class=repo>${e(r.repository)}</span></div><div class=sub>${e(r.online?'Online':r.error?'Needs attention':'Offline')} · ${e(r.error||r.name||'Runner configured')}</div></div></div>`).join(''):'<div class=muted>No repository runner configured yet.</div>';$('ci').textContent=s.last_cleanup_epoch?'Last cleanup: '+new Date(s.last_cleanup_epoch*1000).toLocaleString():'Cleanup has not run yet';$('up').textContent='Last updated: '+new Date().toLocaleTimeString()}catch{$('up').textContent='Waiting for ForgeCore runtime…'}}
$('f').onsubmit=async ev=>{ev.preventDefault();let m=$('fm');m.className='msg';m.textContent='Saving and restarting runner…';try{await api('/api/runners',{method:'POST',body:JSON.stringify({repository:$('repo').value.trim(),token:$('token').value.trim(),name:$('name').value.trim(),labels:$('labels').value.trim()})});$('token').value='';m.className='msg ok';m.textContent='Saved. ForgeCore is registering the runner.';setTimeout(refresh,2500)}catch(x){m.className='msg badtext';m.textContent=x.message}};
$('restart').onclick=async()=>{let m=$('am');try{await api('/api/reload',{method:'POST',body:'{}'});m.className='msg ok';m.textContent='Runner restart requested.'}catch(x){m.className='msg badtext';m.textContent=x.message}};$('cleanup').onclick=async()=>{let m=$('am');try{await api('/api/cleanup',{method:'POST',body:'{}'});m.className='msg ok';m.textContent='Cleanup requested.'}catch(x){m.className='msg badtext';m.textContent=x.message}};link();refresh();setInterval(refresh,5000);
</script></body></html>'''

def env(path):
    out={}
    try:
        for raw in path.read_text().splitlines():
            s=raw.strip()
            if not s or s.startswith('#') or '=' not in s: continue
            k,v=s.split('=',1); v=v.strip(); out[k.strip()]=v[1:-1] if len(v)>1 and v[0]==v[-1]=='"' else v
    except OSError: pass
    return out

def slug(repo): return re.sub(r'[^a-z0-9]+','-',repo.lower()).strip('-')
def settings():
    c=env(GC)
    def n(k,d):
        try:return int(c.get(k,d))
        except ValueError:return d
    return {'cleanup_interval_days':max(1,n('CLEANUP_INTERVAL_HOURS',168)//24),'cache_max_age_days':max(1,n('CACHE_MAX_AGE_DAYS',14))}
def runners():
    out=[]
    for p in sorted(RD.glob('*.env')):
        if p.name=='runner.env.example':continue
        c=env(p); repo=c.get('REPOSITORY','')
        if not REPO.fullmatch(repo):continue
        s=slug(repo); ep=ST/f'runner-{s}.error'; np=ST/f'runner-{s}.name'
        er=ep.read_text().strip() if ep.exists() else ''; name=c.get('NAME','')
        if np.exists(): name=np.read_text().strip()
        out.append({'repository':repo,'name':name,'online':(ST/f'runner-{s}.online').exists(),'error':er})
    return out
def status():
    x={'runner_online':False,'runner_name':'Runner not configured','docker_online':False,'disk_used':'—','disk_total':'—','disk_used_percent':0,'disk_path':'External storage'}
    try:x.update(json.loads((ST/'status.json').read_text()))
    except (OSError,json.JSONDecodeError):pass
    x.update(settings()); x['runners']=runners()
    try:x['last_cleanup_epoch']=int((ST/'last-cleanup-epoch').read_text().strip())
    except (OSError,ValueError):x['last_cleanup_epoch']=0
    return x
def origin_ok(h):
    o=h.headers.get('Origin'); host=h.headers.get('Host','')
    if not o:return True
    p=urlparse(o); return p.netloc==host and p.scheme in ('http','https')
def save_runner(d):
    repo=str(d.get('repository','')).strip(); tok=str(d.get('token','')).strip(); name=str(d.get('name','')).strip(); labels=str(d.get('labels','beelink,forgecore')).strip() or 'beelink,forgecore'
    if not REPO.fullmatch(repo):raise ValueError('Repository must look like owner/repository.')
    if not TOKEN.fullmatch(tok):raise ValueError('Enter a fresh GitHub self-hosted runner registration token.')
    if not NAME.fullmatch(name):raise ValueError('Invalid runner name.')
    if not LABELS.fullmatch(labels):raise ValueError('Invalid labels.')
    s=slug(repo); dst=RD/f'{s}.env'
    for candidate in RD.glob('*.env'):
        if candidate.name!='runner.env.example' and env(candidate).get('REPOSITORY','')==repo:
            dst=candidate; break
    tmp=dst.with_name('.'+dst.name+'.tmp'); tmp.write_text(f'REPOSITORY="{repo}"\nREGISTRATION_TOKEN="{tok}"\nNAME="{name}"\nLABELS="{labels}"\n'); os.chmod(tmp,0o600); os.replace(tmp,dst); (ST/'reload-runners.request').touch()

class H(BaseHTTPRequestHandler):
    server_version='ForgeCoreDashboard/0.1'
    def log_message(self,f,*a): print('[forgecore-web] '+f%a,flush=True)
    def send(self,n,data,typ='application/json; charset=utf-8'):
        if not isinstance(data,bytes):data=json.dumps(data,separators=(',',':')).encode()
        self.send_response(n); self.send_header('Content-Type',typ); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','SAMEORIGIN'); self.send_header('Content-Security-Policy',"default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self'"); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self):
        p=urlparse(self.path).path
        if p=='/':self.send(200,HTML.encode(),'text/html; charset=utf-8')
        elif p=='/api/status':self.send(200,status())
        elif p=='/health':self.send(200,{'ok':True})
        else:self.send(404,{'error':'Not found'})
    def do_POST(self):
        if not origin_ok(self):self.send(403,{'error':'Origin rejected'});return
        if self.headers.get('Content-Type','').split(';',1)[0].strip()!='application/json':self.send(415,{'error':'JSON required'});return
        try:n=int(self.headers.get('Content-Length','0'))
        except ValueError:n=0
        if n<0 or n>8192:self.send(413,{'error':'Request too large'});return
        try:d=json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:self.send(400,{'error':'Invalid JSON'});return
        try:
            p=urlparse(self.path).path
            if p=='/api/runners':save_runner(d)
            elif p=='/api/reload':(ST/'reload-runners.request').touch()
            elif p=='/api/cleanup':(ST/'cleanup-now.request').touch()
            else:self.send(404,{'error':'Not found'});return
            self.send(202,{'ok':True})
        except ValueError as x:self.send(400,{'error':str(x)})
        except OSError:self.send(500,{'error':'ForgeCore could not write its app data.'})

def main():
    RD.mkdir(parents=True,exist_ok=True); ST.mkdir(parents=True,exist_ok=True); print('[forgecore-web] dashboard listening on :8080',flush=True); ThreadingHTTPServer(('0.0.0.0',8080),H).serve_forever()
if __name__=='__main__':main()
