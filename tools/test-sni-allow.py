#!/usr/bin/env python3
"""Port 443 on a relay carries only the routed names (lab branch).

What has to hold: nginx sends 443 to the exit only for a name this relay's
DNS answers with this relay - the service list, the operator's domains, every
template's ticks - and closes every other name, and a connection with none;
smartdns-sync keeps that list from the resolvers' own files, so a domain added,
changed or taken off in the panel is followed on the next sync; the gate's
resolver, block rules and rules for other addresses are not on it; a name a
parent already covers is left out, since nginx refuses one twice; nginx checks
the list before it is reloaded, gets the old one back if it refuses, and is
reloaded only when the list changed; a list that comes out nearly empty is
not written; a machine whose nginx does not read the list is left alone; and
the installer seeds it before nginx first checks its config.
"""
import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
fails = []


def check(label, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label +
          ((" - " + str(detail)) if detail and not cond else ""))
    if not cond:
        fails.append(label)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


spec = importlib.util.spec_from_loader("sync", importlib.machinery.SourceFileLoader(
    "sync", os.path.join(ROOT, "templates", "smartdns-sync")))
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)
logged = []
sync.log = lambda level, msg: logged.append(msg)

ME = "198.51.100.7"
tmp = tempfile.mkdtemp()
dnsmasq_d = os.path.join(tmp, "dnsmasq.d")
profiles = os.path.join(tmp, "profiles")
os.makedirs(dnsmasq_d)
os.makedirs(profiles)


def write(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


SERVICE = ["playstation.com", "xboxlive.com", "ea.com", "riotgames.com", "epicgames.com",
           "steampowered.com", "steamcontent.com", "battle.net", "blizzard.com",
           "rockstargames.com", "ubisoft.com", "nintendo.net", "roblox.com",
           "callofduty.com", "activision.com", "openai.com", "chatgpt.com",
           "netflix.com", "spotify.com", "github.com", "docker.com"]
write(os.path.join(dnsmasq_d, "smart-dns.conf"),
      "cache-size=10000\nlisten-address=127.0.0.1,%s\n" % ME
      + "".join("address=/%s/%s\n" % (d, ME) for d in SERVICE)
      + "address=/store.playstation.com/%s\n" % ME)
write(os.path.join(dnsmasq_d, "50-smartdns-custom.conf"),
      "# operator\naddress=/My-Game.example./%s\naddress=/a.test/b.test/%s\n" % (ME, ME))
write(os.path.join(dnsmasq_d, "bypass.conf"), "server=/stun.playstation.net/#\n")
write(os.path.join(dnsmasq_d, "60-iran-exit.conf"), "address=/elsewhere.example/203.0.113.5\n")
write(os.path.join(dnsmasq_d, "README"), "address=/readme.example/%s\n" % ME)
write(os.path.join(profiles, "2.conf"),
      "port=5302\naddress=/ads.example/\naddress=/tick.example/%s\n" % ME)
write(os.path.join(profiles, "gate.conf"),
      "address=/#/%s\naddress=/panel.example/%s\n" % (ME, ME))

sync.DNSMASQ_D = dnsmasq_d
sync.PROFILE_DIR = profiles
sync.GATE_CONF = os.path.join(profiles, "gate.conf")
sync.SNI_ALLOW_MAP = os.path.join(tmp, "smartdns-sni-allow.map")
sync.NGINX_CONF = os.path.join(tmp, "nginx.conf")
sync.CFG = {"SELF_IP": ME}
write(sync.NGINX_CONF, "stream { include %s; }\n" % sync.SNI_ALLOW_MAP)

ran = []
nginx_ok = [True]


class Done:
    def __init__(self, rc):
        self.returncode = rc
        self.stdout = self.stderr = ""


def fake_sh(*args):
    ran.append(args)
    if args[:2] == ("nginx", "-t"):
        return Done(0 if nginx_ok[0] else 1)
    return Done(0)


sync.sh = fake_sh


def listed():
    return re.findall(r"^\.(\S+) 1;$", open(sync.SNI_ALLOW_MAP).read(), re.M)


def reloads():
    return [a for a in ran if a == ("systemctl", "reload", "nginx")]


print("which names")
names = sync.routed_names((dnsmasq_d, profiles), ME, skip=(sync.GATE_CONF,))
check("the service list, the operator's own and a template's tick",
      {"playstation.com", "my-game.example", "a.test", "b.test", "tick.example"} <= names, names)
check("no gate names - its '#' would be every name there is",
      "#" not in names and "panel.example" not in names)
check("no block rules, no rules for another address, nothing outside a .conf",
      not {"ads.example", "elsewhere.example", "readme.example"} & names)
check("a name its parent covers is left out", "store.playstation.com" not in sync.outermost(names)
      and "playstation.com" in sync.outermost(names))
check("  but a name that only looks like a parent's tail is not",
      sync.outermost({"ea.com", "idea.com"}) == {"ea.com", "idea.com"})

print("the sync")
os.umask(0o077)  # as tight as a service may run with
check("written, checked by nginx, then reloaded", sync.apply_sni_allow() and
      ran[-2:] == [("nginx", "-t"), ("systemctl", "reload", "nginx")], ran)
check("  each name with everything under it, sorted",
      listed() == sorted(sync.outermost(names)) and ".playstation.com 1;" in
      open(sync.SNI_ALLOW_MAP).read())
check("  readable by nginx's workers", oct(os.stat(sync.SNI_ALLOW_MAP).st_mode & 0o777) == "0o644")
ran.clear()
check("nothing changed: no rewrite, no reload", not sync.apply_sni_allow() and not ran)

write(os.path.join(dnsmasq_d, "50-smartdns-custom.conf"), "address=/new-game.example/%s\n" % ME)
check("a domain the panel adds and takes off is followed on the next sync",
      sync.apply_sni_allow() and "new-game.example" in listed()
      and "my-game.example" not in listed() and len(reloads()) == 1)
check("  and the change is in the log", any("+new-game.example" in m and "-my-game.example" in m
                                            for m in logged), logged[-1:])

before = open(sync.SNI_ALLOW_MAP).read()
write(os.path.join(dnsmasq_d, "50-smartdns-custom.conf"), "address=/refused.example/%s\n" % ME)
nginx_ok[0] = False
ran.clear()
check("refused by nginx: the old list back, no reload",
      not sync.apply_sni_allow() and open(sync.SNI_ALLOW_MAP).read() == before
      and not reloads())
nginx_ok[0] = True
write(os.path.join(dnsmasq_d, "50-smartdns-custom.conf"), "address=/new-game.example/%s\n" % ME)

saved = os.path.join(tmp, "saved.conf")
shutil.move(os.path.join(dnsmasq_d, "smart-dns.conf"), saved)
ran.clear()
check("nearly empty - the files not readable - the list in place is kept",
      not sync.apply_sni_allow() and open(sync.SNI_ALLOW_MAP).read() == before and not ran)
shutil.move(saved, os.path.join(dnsmasq_d, "smart-dns.conf"))

write(sync.NGINX_CONF, "stream { proxy_pass $upstream; }\n")
ran.clear()
check("an nginx that does not read the list is left alone", not sync.apply_sni_allow() and not ran)
write(sync.NGINX_CONF, "stream { include %s; }\n" % sync.SNI_ALLOW_MAP)
sync.CFG = {}
check("  as is a relay that does not know its own address", not sync.apply_sni_allow())
sync.CFG = {"SELF_IP": ME}

sync_text = read("templates/smartdns-sync")
check("sync_once runs it every sync", "        apply_sni_allow()\n" in sync_text)

print("nginx")
conf = read("templates/relay-nginx.conf")
stream = conf[conf.index("stream {"):]
first_map = stream.index("    map ")
check("the hash sizes set before the first map reads them",
      -1 < stream.find("map_hash_max_size") < first_map
      and -1 < stream.find("map_hash_bucket_size") < first_map)
check("names matched as hostnames, from the file, closed by default",
      "map $ssl_preread_server_name $sni_routed {\n        hostnames;\n"
      "        include /etc/nginx/smartdns-sni-allow.map;\n        default 0;" in conf)
check("  a routed name to this customer's exit, anything else to the discard port",
      "map $sni_routed $sni_target {\n        1       ${to_exit}_https;\n"
      "        default 127.0.0.1:9;" in conf)
check("443 goes by it with DoH and without",
      "default       $sni_target;" in conf and "proxy_pass $sni_target;" in conf
      and "${to_exit}_https;" not in conf.replace("1       ${to_exit}_https;", ""))
check("the DoH names and local sites still come first",
      conf.index("smartdns-doh-names.map") < conf.index("default       $sni_target;")
      and conf.index("smartdns-local-sites.map") < conf.index("default       $sni_target;"))

print("the installer")
inst = read("doctor-dns.sh")
check("it seeds the list before nginx first checks a relay's config",
      'if [ "$ROLE" = relay ]; then\n    sni_allow_include\n'
      '    install_payload RELAY_NGINX' in inst)
check("the built installer carries the new nginx config",
      "#        default       $sni_target;" in inst)
body = inst[inst.index("sni_allow_include() {"):]
body = body[:body.index("\n}\n") + 3]
root = os.path.join(tmp, "root")
os.makedirs(os.path.join(root, "nginx"))
shutil.copytree(dnsmasq_d, os.path.join(root, "dnsmasq.d"))
shutil.copytree(profiles, os.path.join(root, "smartdns-profiles"))
body = body.replace("/etc/dnsmasq.d", os.path.join(root, "dnsmasq.d")).replace(
    "/etc/smartdns-profiles", os.path.join(root, "smartdns-profiles"))
seed = os.path.join(root, "nginx", "allow.map")
script = ('payload() { printf "playstation.com\\nXbox.com.\\nstore.playstation.com\\n"; }\n'
          'SNI_ALLOW_MAP=%s\nRELAY_IP=%s\n%s\nsni_allow_include\n' % (seed, ME, body))
r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
got = re.findall(r"^\.(\S+) 1;$", open(seed).read(), re.M) if os.path.exists(seed) else []
check("  from the service list and the resolvers' rules, as the sync would",
      r.returncode == 0 and "playstation.com" in got and "xbox.com" in got
      and "new-game.example" in got and "tick.example" in got, r.stderr or got)
check("  without the gate, block rules, other addresses or covered names",
      not {"panel.example", "ads.example", "elsewhere.example", "store.playstation.com"} & set(got))
write(seed, "# the operator's\n.kept.example 1;\n")
subprocess.run(["bash", "-c", script], capture_output=True, text=True)
check("  and an upgrade leaves a list that has names be",
      open(seed).read() == "# the operator's\n.kept.example 1;\n")

shutil.rmtree(tmp)
print()
print("FAILED: %d" % len(fails) if fails else "all passed")
sys.exit(1 if fails else 0)
