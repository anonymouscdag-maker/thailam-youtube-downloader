#!/usr/bin/env python3
import base64, hmac, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST='127.0.0.1'
PORT=10002
API_KEY=os.getenv('API_KEY','')
COOKIE_FILE=Path('/tmp/youtube-cookies.txt')

def out(h,obj,status=200):
    body=json.dumps(obj,ensure_ascii=False,separators=(',',':')).encode()
    h.send_response(status); h.send_header('Content-Type','application/json; charset=utf-8'); h.send_header('Content-Length',str(len(body))); h.send_header('Cache-Control','no-store'); h.end_headers(); h.wfile.write(body)

class H(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_POST(self):
        if self.path != '/v1/cookies': return out(self,{'ok':False,'error':'Not found'},404)
        if not API_KEY or not hmac.compare_digest(self.headers.get('X-API-Key',''),API_KEY): return out(self,{'ok':False,'error':'API Key không hợp lệ.'},401)
        try:
            n=int(self.headers.get('Content-Length','0'))
            if n<=0 or n>3*1024*1024: raise ValueError('Cookie quá lớn hoặc rỗng.')
            data=json.loads(self.rfile.read(n) or b'{}')
            raw=base64.b64decode(str(data.get('youtube_cookies_b64') or ''),validate=True)
            if len(raw)>2*1024*1024: raise ValueError('Cookie quá lớn.')
            text=raw.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')
            first=next((x.strip() for x in text.split('\n') if x.strip()),'')
            if first not in ('# Netscape HTTP Cookie File','# HTTP Cookie File'): raise ValueError('Cookie phải là cookies.txt định dạng Netscape.')
            if '.youtube.com' not in text and '\tyoutube.com\t' not in text: raise ValueError('Cookie không có dữ liệu youtube.com.')
            COOKIE_FILE.write_text(text.rstrip('\n')+'\n',encoding='utf-8',newline='\n')
            os.chmod(COOKIE_FILE,0o600)
            return out(self,{'ok':True,'saved':True})
        except Exception as e:
            return out(self,{'ok':False,'error':str(e)[:500]},422)

ThreadingHTTPServer((HOST,PORT),H).serve_forever()
