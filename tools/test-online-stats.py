#!/usr/bin/env python3
"""Online stats, phase 1 (lab branch, karimialireza36-cmd/doctor-dns).

What has to hold, on the relay's side: nginx's usage line carries $status at
its end; each connection is counted as carried (ok), refused for a name port
443 does not carry (sni_denied) or failed for no exit (exit_failed); a line
from before $status counts its bytes as it always did and gets no verdict;
the per-exit count still reads the last address, not the status; one address
asking for names without end cannot grow the count without bound; and what
was not delivered is kept, what was delivered cleared.
"""
import importlib.machinery
import importlib.util
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + repr(detail)) if detail != "" and not cond else ""))
    if not cond:
        fails.append(label)


def load(path, mod):
    spec = importlib.util.spec_from_loader(
        mod, importlib.machinery.SourceFileLoader(mod, os.path.join(HERE, "..", path)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def read(rel):
    with open(os.path.join(HERE, "..", rel), encoding="utf-8") as fh:
        return fh.read()


sync = load("templates/smartdns-sync", "sync")
sync.log = lambda *a: None
sync.sh = lambda *a: None
sync.is_single = lambda: False
sync.current_exit_ip = lambda: "198.51.100.7"

print("nginx's line")
conf = read("templates/relay-nginx.conf")
check("the usage line ends with $status, after the exit it went to",
      "$bytes_received $upstream_addr $status';" in conf)
check("the installer carries the same line",
      "$bytes_received $upstream_addr $status';" in read("doctor-dns.sh"))

print("how a connection ended")
check("200 through an exit is ok", sync.verdict_of("127.0.0.1:18443", "200") == "ok")
check("the closed port is sni_denied, whatever the status",
      sync.verdict_of("127.0.0.1:9", "502") == "sni_denied"
      and sync.verdict_of("127.0.0.1:9", "200") == "sni_denied")
check("502 and 503 are exit_failed",
      sync.verdict_of("127.0.0.1:18443, 198.51.100.7:443", "502") == "exit_failed"
      and sync.verdict_of("198.51.100.7:443", "503") == "exit_failed")
check("a line with no status, or another status, says nothing",
      sync.verdict_of("198.51.100.7:443", None) is None
      and sync.verdict_of("-", "400") is None and sync.verdict_of("-", "500") is None)
check("a status is only taken from a line long enough to have one",
      sync.split_status("a 443 n 1 1 x:443 200".split()) == ("a 443 n 1 1 x:443".split(), "200")
      and sync.split_status("a 443 n 1 1 x:443".split()) == ("a 443 n 1 1 x:443".split(), None)
      and sync.split_status("a 443 1 1".split())[1] is None)

print("the relay's count")
tmp = tempfile.mkdtemp()
sync.USAGE_LOG = os.path.join(tmp, "usage")
sync.USAGE_TAKEN = sync.USAGE_LOG + ".taken"
with open(sync.USAGE_TAKEN, "w") as fh:
    fh.write("203.0.113.5 443 gs2.playstation.net 900 100 127.0.0.1:18443 200\n"
             "203.0.113.5 443 gs2.playstation.net 50 50 127.0.0.1:18443 200\n"
             "203.0.113.5 443 www.example.org 0 517 127.0.0.1:9 502\n"
             "203.0.113.5 443 gs2.playstation.net 0 300"
             " 127.0.0.1:18443, 198.51.100.7:443 502\n"
             "203.0.113.5 80 - 10 10 198.51.100.7:80 200\n"
             "203.0.113.6 443 old.example 7 3 198.51.100.7:443\n"
             "garbage\n")
sync.USAGE_PENDING.clear()
sync.EXIT_PENDING.clear()
sync.VERDICT_PENDING.clear()
services = sync.take_usage()
check("bytes by name are what they were",
      services == {"203.0.113.5": {"gs2.playstation.net": 1400, "www.example.org": 517,
                                   ":80": 20},
                   "203.0.113.6": {"old.example": 10}}, services)
check("each connection is counted by how it ended, with its bytes",
      sync.VERDICT_PENDING == {"203.0.113.5": {
          "gs2.playstation.net": {"ok": [2, 1100], "exit_failed": [1, 300]},
          "www.example.org": {"sni_denied": [1, 517]},
          ":80": {"ok": [1, 20]}}}, sync.VERDICT_PENDING)
check("the per-exit count reads the exit, not the status",
      sync.EXIT_PENDING["203.0.113.5"]["198.51.100.7"] == [100 + 50 + 300 + 10, 900 + 50 + 10]
      and sync.EXIT_PENDING["203.0.113.6"] == {"198.51.100.7": [3, 7]},
      sync.EXIT_PENDING)
check("the line is deleted once read", not os.path.exists(sync.USAGE_TAKEN))

print("an address asking for names without end")
sync.VERDICT_PENDING.clear()
for i in range(sync.VERDICT_NAMES_MAX + 50):
    sync.count_verdict("203.0.113.9", "n%d.example" % i, "sni_denied", 1)
per = sync.VERDICT_PENDING["203.0.113.9"]
check("the names stop at the limit, the rest under _other",
      len(per) == sync.VERDICT_NAMES_MAX + 1 and per["_other"]["sni_denied"] == [50, 50])
sync.VERDICT_PENDING.clear()

print("delivery")
src = read("templates/smartdns-sync")
check("the sync sends the count and clears it only once the panel has it",
      'payload["verdicts"]' in src
      and src.index('answer = post("/sync", payload)')
      < src.index("        VERDICT_PENDING.clear()"))

print()
if fails:
    print("%d failed" % len(fails))
    sys.exit(1)
print("all passed")
