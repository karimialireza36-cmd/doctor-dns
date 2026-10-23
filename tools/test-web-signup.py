#!/usr/bin/env python3
"""WEB_SIGNUP=off closes the customer panel's own sign-up.

For an operator whose customers get their accounts from the operator's own
sales bot (through the bot API) and are never meant to open one on this page.
What has to hold: off hides the button and the link and refuses /signup both
ways, sending people to sign in instead; sign-in itself is untouched; and with
nothing set, nothing changes. The installer writes the key only when given.
"""
import importlib.machinery
import importlib.util
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + ((" - " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        fails.append(label)


spec = importlib.util.spec_from_loader(
    "sync", importlib.machinery.SourceFileLoader("sync", os.path.join(HERE, "..", "templates", "smartdns-sync")))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
sync.log = lambda *a: None


class Fake(sync.UserPanel):
    def __init__(self, path, form=None):
        self.path = path
        self._form = form or {}
        self.out = None

    def sent_elsewhere(self, path):
        return False

    def session(self):
        return None

    def banner(self):
        return ""

    def form(self):
        return self._form

    def client_ip(self):
        return "5.112.84.20"

    def redirect(self, where, message="", bad=False):
        self.out = ("redirect", where, message)

    def send_html(self, body, *a, **k):
        self.out = ("html", body)


posted = []
sync.post = lambda endpoint, payload: posted.append(endpoint) or {"ok": False, "message": "x"}

print("default: sign-up open, as before")
sync.CFG = {}
check("open with nothing set", sync.signup_open())
check("the landing page offers it", "href='/signup'" in sync.landing())
check("the sign-in page links to it", "href='/signup'" in sync.login_form())
h = Fake("/signup"); h.do_GET()
check("GET /signup shows the form", h.out and h.out[0] == "html" and "password2" in h.out[1], h.out)

print("WEB_SIGNUP=off")
for v in ("off", "OFF", "0", "no"):
    sync.CFG = {"WEB_SIGNUP": v}
    check("closed with %r" % v, not sync.signup_open())
sync.CFG = {"WEB_SIGNUP": "off"}
check("no button on the landing page", "href='/signup'" not in sync.landing())
check("  the sign-in button stays", "href='/login'" in sync.landing())
check("no link on the sign-in page", "href='/signup'" not in sync.login_form())
h = Fake("/signup"); h.do_GET()
check("GET /signup goes to sign in, saying why",
      h.out and h.out[:2] == ("redirect", "/login") and "ربات" in h.out[2], h.out)
h = Fake("/signup?ref=abcd2345"); h.do_GET()
check("  an invitation link too", h.out and h.out[:2] == ("redirect", "/login"), h.out)
posted.clear()
h = Fake("/signup", {"username": "ashrafi", "password": "xxxxxxxx", "password2": "xxxxxxxx"}); h.do_POST()
check("POST /signup is refused before it reaches the panel",
      h.out and h.out[:2] == ("redirect", "/login") and not posted, (h.out, posted))
h = Fake("/login", {"username": "alireza", "password": "yyyyyyyy"}); h.do_POST()
check("sign-in still reaches the panel", posted == ["/user-password-login"], posted)
h = Fake("/login"); h.do_GET()
check("and its page still shows", h.out and h.out[0] == "html" and "password" in h.out[1], h.out)

print("installer")
logic = open(os.path.join(HERE, "installer-logic.sh"), encoding="utf-8").read()
check("writes WEB_SIGNUP only when given",
      'if [ -n "${WEB_SIGNUP:-}" ]; then' in logic
      and 'set_env_key /etc/smart-dns/sync.env WEB_SIGNUP "$WEB_SIGNUP"' in logic)

print()
print("FAILED: %d" % len(fails) if fails else "all ok")
sys.exit(1 if fails else 0)
