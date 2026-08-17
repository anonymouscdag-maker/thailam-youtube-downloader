#!/usr/bin/env python3
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import defaultdict, deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HOST = os.getenv('HOST', '0.0.0.0')
PORT = int(os.getenv('PORT', '10000'))
API_KEY = os.getenv('API_KEY', '')
DOWNLOAD_SECRET = os.getenv('DOWNLOAD_SECRET', '')
PUBLIC_BASE_URL = (os.getenv('PUBLIC_BASE_URL') or os.getenv('RENDER_EXTERNAL_URL') or '').rstrip('/')
DATA_DIR = Path(os.getenv('DATA_DIR', '/tmp/thailam-downloader'))
JOBS_DIR = DATA_DIR / 'jobs'
MAX_CONCURRENT = max(1, int(os.getenv('MAX_CONCURRENT_JOBS', '1')))
MAX_QUEUED = max(MAX_CONCURRENT, int(os.getenv('MAX_QUEUED_JOBS', '6')))
MAX_DURATION = int(os.getenv('MAX_DURATION_SECONDS', '21600'))
MAX_FILE_BYTES = int(os.getenv('MAX_FILE_BYTES', str(2 * 1024 * 1024 * 1024)))
JOB_TTL = int(os.getenv('JOB_TTL_SECONDS', '1800'))
SIGNED_URL_TTL = int(os.getenv('SIGNED_URL_TTL_SECONDS', '900'))
RATE_LIMIT_PER_MIN = max(5, int(os.getenv('RATE_LIMIT_PER_MINUTE', '60')))

JOBS_DIR.mkdir(parents=True, exist_ok=True)
JOBS = {}
JOBS_LOCK = threading.RLock()
SEMAPHORE = threading.Semaphore(MAX_CONCURRENT)
RATE = defaultdict(deque)
STOP = threading.Event()
YOUTUBE_HOSTS = {'youtube.com','m.youtube.com','music.youtube.com','youtu.be'}

def now(): return int(time.time())
def json_bytes(obj): return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
def is_youtube_url(url):
    try:
        p = urlparse(url)
        if p.scheme not in ('http','https') or not p.hostname: return False
        h = p.hostname.lower().removeprefix('www.')
        return h in YOUTUBE_HOSTS or h.endswith('.youtube.com')
    except Exception: return False

def duration_text(seconds):
    seconds=max(0,int(seconds or 0)); h=seconds//3600; m=(seconds%3600)//60; s=seconds%60
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

def cmd_version(name):
    try:
        args=[name,'-version'] if name=='ffmpeg' else [name,'--version']
        p=subprocess.run(args,capture_output=True,text=True,timeout=8)
        return (p.stdout or p.stderr).strip().splitlines()[0][:120] if p.returncode==0 else None
    except Exception: return None

def ytdlp_base(): return ['yt-dlp','--ignore-config','--no-playlist','--no-warnings','--js-runtimes','deno']

def analyze_url(url):
    p=subprocess.run(ytdlp_base()+['--dump-single-json','--skip-download',url],capture_output=True,text=True,timeout=90)
    if p.returncode!=0: raise RuntimeError((p.stderr or p.stdout or 'Không đọc được video.').strip()[-1200:])
    data=json.loads(p.stdout); duration=int(data.get('duration') or 0)
    if duration>MAX_DURATION: raise RuntimeError('Video vượt giới hạn thời lượng của server.')
    exact=set(); max_h=0
    for f in data.get('formats') or []:
        if (f.get('vcodec') or 'none')=='none': continue
        try: h=int(f.get('height') or 0)
        except Exception: h=0
        if h>0: exact.add(h); max_h=max(max_h,h)
    qualities=[{'height':h,'label':label} for h,label in [(2160,'4K'),(1440,'2K'),(1080,'1080p'),(720,'720p')] if h in exact]
    thumbs=data.get('thumbnails') or []; thumb=data.get('thumbnail') or ''
    if thumbs:
        best=max(thumbs,key=lambda x:(int(x.get('width') or 0)*int(x.get('height') or 0),int(x.get('preference') or 0)))
        thumb=best.get('url') or thumb
    return {'id':data.get('id') or '','title':data.get('title') or 'YouTube video','channel':data.get('channel') or data.get('uploader') or '','duration':duration,'duration_text':duration_text(duration),'thumbnail':thumb,'max_height':max_h,'qualities':qualities,'mp3':True}

def update_job(job_id,**fields):
    with JOBS_LOCK:
        j=JOBS.get(job_id)
        if not j: return
        j.update(fields); j['updated_at']=now(); status_file=Path(j['dir'])/'status.json'
        try: status_file.write_text(json.dumps(j,ensure_ascii=False,indent=2),encoding='utf-8')
        except Exception: pass

def safe_filename(name):
    name=re.sub(r'[\x00-\x1f\x7f/\\<>:"|?*]+','-',name).strip().strip('.')
    return name[:180] or 'download'

def parse_progress(line):
    m=re.search(r'([0-9]{1,3}(?:\.[0-9]+)?)%',line)
    if m:
        try: return min(95.0,max(4.0,float(m.group(1))*0.92))
        except Exception: pass
    return None

def sign_download(job_id,exp): return hmac.new(DOWNLOAD_SECRET.encode(),f'{job_id}:{exp}'.encode(),hashlib.sha256).hexdigest()
def valid_signature(job_id,exp,sig): return bool(DOWNLOAD_SECRET and exp>=now() and hmac.compare_digest(sign_download(job_id,exp),sig))

def run_job(job_id):
    with SEMAPHORE:
        with JOBS_LOCK: j=dict(JOBS[job_id])
        update_job(job_id,status='processing',progress=2,message='Đang kiểm tra video...')
        job_dir=Path(j['dir']); url=j['url']; typ=j['type']; height=int(j.get('height') or 0)
        try:
            info=analyze_url(url)
            if typ=='video' and height not in [int(q.get('height') or 0) for q in info.get('qualities',[])]: raise RuntimeError(f'Video không có chất lượng {height}p.')
            update_job(job_id,status='downloading',progress=4,message='Đang tải dữ liệu từ YouTube...')
            outtmpl=str(job_dir/'%(title).140B [%(id)s].%(ext)s')
            cmd=ytdlp_base()+['--newline','--no-part','--no-overwrites','-o',outtmpl,'--ffmpeg-location','/usr/bin/ffmpeg']
            if typ=='mp3': cmd+=['-x','--audio-format','mp3','--audio-quality','0','--embed-metadata','--embed-thumbnail',url]
            else:
                selector=f'bv*[height={height}][ext=mp4]+ba[ext=m4a]/bv*[height={height}]+ba/b[height={height}]'
                cmd+=['-f',selector,'--merge-output-format','mp4','--remux-video','mp4',url]
            p=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1); last=''
            for raw in p.stdout or []:
                line=raw.strip(); last=line[-1000:]; prog=parse_progress(line)
                if prog is not None: update_job(job_id,progress=prog,message='Đang tải video...' if typ=='video' else 'Đang tải âm thanh...')
                elif '[Merger]' in line or '[VideoRemuxer]' in line or '[ExtractAudio]' in line or '[EmbedThumbnail]' in line: update_job(job_id,status='processing',progress=96,message='Đang ghép và hoàn thiện file...')
            if p.wait()!=0: raise RuntimeError(last or 'yt-dlp tải thất bại.')
            files=[x for x in job_dir.iterdir() if x.is_file() and x.name!='status.json' and not x.name.endswith('.part')]
            if not files: raise RuntimeError('Không tìm thấy file sau khi xử lý.')
            file=max(files,key=lambda x:x.stat().st_size); size=file.stat().st_size
            if size<=0: raise RuntimeError('File tải về bị lỗi.')
            if size>MAX_FILE_BYTES: raise RuntimeError('File vượt giới hạn dung lượng của server.')
            clean=safe_filename(file.name)
            if clean!=file.name:
                try: file.rename(job_dir/clean); file=job_dir/clean
                except Exception: pass
            exp=now()+SIGNED_URL_TTL; sig=sign_download(job_id,exp); base=PUBLIC_BASE_URL or f'http://localhost:{PORT}'
            update_job(job_id,status='ready',progress=100,message='Sẵn sàng tải xuống.',filename=file.name,filepath=str(file),filesize=size,download_url=f'{base}/download/{quote(job_id)}?exp={exp}&sig={sig}',expires_at=now()+JOB_TTL)
        except Exception as e: update_job(job_id,status='error',progress=0,message='Tải thất bại.',error=str(e)[:1500])

def create_job(url,typ,height):
    with JOBS_LOCK: active=sum(1 for x in JOBS.values() if x.get('status') in ('queued','downloading','processing'))
    if active>=MAX_QUEUED: raise RuntimeError('Hàng đợi đang đầy. Vui lòng thử lại sau.')
    job_id=uuid.uuid4().hex[:20]; job_dir=JOBS_DIR/job_id; job_dir.mkdir(parents=True,exist_ok=False)
    j={'job_id':job_id,'url':url,'type':typ,'height':height,'status':'queued','progress':1,'message':'Đang xếp hàng...','created_at':now(),'updated_at':now(),'dir':str(job_dir),'error':None,'download_url':None}
    with JOBS_LOCK: JOBS[job_id]=j
    update_job(job_id); threading.Thread(target=run_job,args=(job_id,),daemon=True).start(); return job_id

def cleanup_loop():
    while not STOP.wait(300):
        cutoff=now()-JOB_TTL
        with JOBS_LOCK: ids=list(JOBS.keys())
        for jid in ids:
            with JOBS_LOCK: j=JOBS.get(jid)
            if j and int(j.get('updated_at') or 0)<cutoff:
                shutil.rmtree(j.get('dir',''),ignore_errors=True)
                with JOBS_LOCK: JOBS.pop(jid,None)

def load_existing():
    for p in JOBS_DIR.glob('*/status.json'):
        try:
            j=json.loads(p.read_text(encoding='utf-8'))
            if int(j.get('updated_at') or 0)>=now()-JOB_TTL:
                if j.get('status') in ('queued','downloading','processing'): j['status']='error'; j['error']='Worker đã khởi động lại khi tác vụ đang chạy.'; j['message']='Tác vụ bị gián đoạn.'
                JOBS[j['job_id']]=j
        except Exception: pass

class Handler(BaseHTTPRequestHandler):
    server_version='TLDownloader/1.0'
    def log_message(self,fmt,*args): print('%s - %s'%(self.address_string(),fmt%args),flush=True)
    def send_json(self,obj,status=200):
        body=json_bytes(obj); self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
    def auth(self):
        if not API_KEY: self.send_json({'ok':False,'error':'Worker chưa cấu hình API_KEY.'},500); return False
        key=self.headers.get('X-API-Key','')
        if not hmac.compare_digest(key,API_KEY): self.send_json({'ok':False,'error':'API Key không hợp lệ.'},401); return False
        bucket=RATE[key]; t=time.time()
        while bucket and bucket[0]<t-60: bucket.popleft()
        if len(bucket)>=RATE_LIMIT_PER_MIN: self.send_json({'ok':False,'error':'Quá nhiều yêu cầu. Thử lại sau.'},429); return False
        bucket.append(t); return True
    def read_json(self):
        try:
            n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(min(n,1024*128)) or b'{}')
        except Exception: return {}
    def do_GET(self):
        u=urlparse(self.path)
        if u.path=='/': return self.send_json({'ok':True,'service':'Thái Lâm Downloader Worker'})
        if u.path=='/v1/health':
            if not self.auth(): return
            yt=cmd_version('yt-dlp'); ff=cmd_version('ffmpeg'); den=cmd_version('deno'); ready=bool(yt and ff and den and API_KEY and DOWNLOAD_SECRET)
            return self.send_json({'ok':True,'ready':ready,'yt_dlp':yt,'ffmpeg':ff,'deno':den,'max_concurrent_jobs':MAX_CONCURRENT})
        m=re.fullmatch(r'/v1/jobs/([A-Za-z0-9_-]+)',u.path)
        if m:
            if not self.auth(): return
            with JOBS_LOCK: j=JOBS.get(m.group(1))
            if not j: return self.send_json({'ok':False,'error':'Không tìm thấy tác vụ.'},404)
            public={k:v for k,v in j.items() if k not in ('dir','filepath','url','download_url')}
            if j.get('status')=='ready' and Path(j.get('filepath','')).is_file():
                exp=now()+SIGNED_URL_TTL; sig=sign_download(j['job_id'],exp); base=PUBLIC_BASE_URL or f'http://localhost:{PORT}'; public['download_url']=f'{base}/download/{quote(j["job_id"])}?exp={exp}&sig={sig}'
            public['ok']=True; return self.send_json(public)
        m=re.fullmatch(r'/download/([A-Za-z0-9_-]+)',u.path)
        if m:
            q=parse_qs(u.query); exp=int((q.get('exp') or ['0'])[0] or 0); sig=(q.get('sig') or [''])[0]; jid=m.group(1)
            if not valid_signature(jid,exp,sig): return self.send_json({'ok':False,'error':'Link tải đã hết hạn hoặc không hợp lệ.'},403)
            with JOBS_LOCK: j=JOBS.get(jid)
            if not j or j.get('status')!='ready': return self.send_json({'ok':False,'error':'File chưa sẵn sàng.'},404)
            path=Path(j.get('filepath',''))
            if not path.is_file(): return self.send_json({'ok':False,'error':'File không còn tồn tại.'},404)
            size=path.stat().st_size; name=safe_filename(j.get('filename') or path.name); start,end=0,size-1; range_header=self.headers.get('Range',''); partial=False
            if range_header:
                mr=re.fullmatch(r'bytes=(\d*)-(\d*)',range_header.strip())
                if mr:
                    a,b=mr.groups(); start=int(a or 0); end=int(b) if b else size-1; end=min(end,size-1)
                    if start>end or start>=size: self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
                    partial=True
            length=end-start+1; self.send_response(206 if partial else 200); self.send_header('Content-Type','application/octet-stream'); self.send_header('Content-Length',str(length)); self.send_header('Accept-Ranges','bytes')
            if partial: self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(name)); self.send_header('Cache-Control','private, no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers()
            try:
                with path.open('rb') as f:
                    f.seek(start); remaining=length
                    while remaining>0:
                        chunk=f.read(min(1024*1024,remaining))
                        if not chunk: break
                        self.wfile.write(chunk); remaining-=len(chunk)
            except (BrokenPipeError,ConnectionResetError): pass
            return
        self.send_json({'ok':False,'error':'Not found'},404)
    def do_POST(self):
        u=urlparse(self.path)
        if u.path not in ('/v1/analyze','/v1/jobs'): return self.send_json({'ok':False,'error':'Not found'},404)
        if not self.auth(): return
        data=self.read_json(); url=str(data.get('url') or '').strip()
        if not is_youtube_url(url): return self.send_json({'ok':False,'error':'Link YouTube không hợp lệ.'},422)
        if u.path=='/v1/analyze':
            try: return self.send_json({'ok':True,'video':analyze_url(url)})
            except Exception as e: return self.send_json({'ok':False,'error':str(e)[:1500]},500)
        typ=str(data.get('type') or 'video').lower(); height=int(data.get('height') or 0)
        if typ not in ('video','mp3'): return self.send_json({'ok':False,'error':'Loại tải không hợp lệ.'},422)
        if typ=='video' and height not in (2160,1440,1080,720): return self.send_json({'ok':False,'error':'Chất lượng không hợp lệ.'},422)
        try: return self.send_json({'ok':True,'job_id':create_job(url,typ,height),'status':'queued'},202)
        except Exception as e: return self.send_json({'ok':False,'error':str(e)[:800]},429)

if __name__=='__main__':
    if not API_KEY or not DOWNLOAD_SECRET: print('WARNING: API_KEY/DOWNLOAD_SECRET chưa cấu hình',flush=True)
    load_existing(); threading.Thread(target=cleanup_loop,daemon=True).start(); print(f'Worker listening on {HOST}:{PORT}',flush=True); ThreadingHTTPServer((HOST,PORT),Handler).serve_forever()
