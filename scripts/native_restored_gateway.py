"""Owned native-test ingress. Container ports must be published on loopback only.

Auth/Storage are checked on every request; no positive gate cache or raw TCP
bypass. The database port is a separate credentialed operator channel. Upstream
services remain on a fresh internal Docker network with no published ports.
"""
import argparse
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import select
import socket
import socketserver
import threading
import time
from uuid import UUID

from talli_backend.adapters.restored_publication import publication_is_current

MAX_BODY = 32 * 1024 * 1024


def allowed(config):
    return publication_is_current(journal=Path(config['journal']),receipt=Path(config['receipt']),
        target=config['target'],stream=config['stream'],minimum_sequence=config['minimum_sequence'],
        minimum_sha256=config['minimum_sha256'])


class RequestHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self,*args):pass
    def unavailable(self,code=503):
        raw=b'Native recovery target is quarantined' if code==503 else b'Invalid native gateway request'
        self.send_response(code);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store');self.send_header('Connection','close')
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(raw)
        self.close_connection=True
    def forward(self):
        if not allowed(self.server.config):return self.unavailable()
        if self.headers.get('Transfer-Encoding'):return self.unavailable(413)
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self.unavailable(400)
        if not 0<=length<=MAX_BODY:return self.unavailable(413)
        path=self.path
        if self.server.mode=='gateway':
            if path.startswith('/auth/v1/'):
                mode='auth';path=path[len('/auth/v1'):]
            elif path.startswith('/storage/v1/'):
                mode='storage';path=path[len('/storage/v1'):]
            else:return self.unavailable(404)
        else:mode=self.server.mode
        host=self.server.config[mode+'_host'];port=9999 if mode=='auth' else 5000
        connection=HTTPConnection(host,port,timeout=10)
        try:
            self.connection.settimeout(10)
            body=self.rfile.read(length)
            if len(body)!=length:return self.unavailable(400)
            headers={k:v for k,v in self.headers.items() if k.lower() not in {'host','connection','content-length','transfer-encoding'}}
            if not allowed(self.server.config):return self.unavailable()
            connection.request(self.command,path,body,headers)
            response=connection.getresponse();raw=response.read(MAX_BODY+1)
            if len(raw)>MAX_BODY:return self.unavailable(502)
            if not allowed(self.server.config):return self.unavailable()
            self.send_response(response.status)
            for k,v in response.getheaders():
                if k.lower() not in {'content-length','connection','transfer-encoding'}:self.send_header(k,v)
            self.send_header('Content-Length',str(len(raw)));self.send_header('Connection','close');self.end_headers()
            if self.command!='HEAD':self.wfile.write(raw)
            self.close_connection=True
        except (OSError,ValueError):
            self.unavailable()
        finally:connection.close()
    do_GET=do_POST=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=do_HEAD=forward


class ControlServer(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True


class ControlHandler(socketserver.BaseRequestHandler):
    def handle(self):
        with socket.create_connection((self.server.config['database_host'],5432),timeout=5) as other:
            self.request.setblocking(False);other.setblocking(False);end=time.monotonic()+30
            while time.monotonic()<end:
                for source in select.select([self.request,other],[],[],1)[0]:
                    raw=source.recv(65536)
                    if not raw:return
                    destination=other if source is self.request else self.request
                    destination.settimeout(5);destination.sendall(raw);destination.setblocking(False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(args.config.read_bytes());nonce=os.environ.get('TALLI_NATIVE_OWNED','')
    if str(UUID(nonce))!=str(UUID(config['target'])):raise ValueError('Unbound native gateway')
    for key in ('database_host','auth_host','storage_host'):
        if not re.fullmatch(r'[a-z][a-z0-9_]{1,100}',config[key]):raise ValueError('Invalid owned upstream')
    servers=[]
    control=ControlServer(('0.0.0.0',15432),ControlHandler);control.config=config;servers.append(control)
    for mode,port in (('auth',19999),('storage',19998),('gateway',19997)):
        server=ThreadingHTTPServer(('0.0.0.0',port),RequestHandler);server.config=config;server.mode=mode;servers.append(server)
    for server in servers:threading.Thread(target=server.serve_forever,daemon=True).start()
    print('OWNED_NATIVE_INGRESS_BOUND',flush=True)
    threading.Event().wait()


if __name__=='__main__':main()
