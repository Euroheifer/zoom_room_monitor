#!/usr/bin/env python3
"""One-shot, idempotent: wire CNGR room alerts to SeaTalk.

Creates on zabbix.cit.insea.io (via ZBX_API_URL/ZBX_API_TOKEN from .env):
  1. media type "Seatalk-ZoomRooms-CNGR" — clone of the house "Seatalk"
     webhook media type (id 42) with our group webhook URL
  2. user group "Zoom Rooms Alerts" (no frontend, read on Rooms/* groups)
     + user "svc-zoomrooms-seatalk" carrying the media
  3. trigger action "Zoom Rooms CNGR - SeaTalk alerts"
     (host group Rooms/CNGR, severity >= Average, problem + recovery)

Run: set -a && . ./.env && set +a && python3 setup_seatalk_cngr.py
"""
import json, os, ssl, sys, urllib.request

URL = os.environ['ZBX_API_URL']
TOKEN = os.environ['ZBX_API_TOKEN']
NEW_HOOK = os.environ['SEATALK_WEBHOOK_URL']  # from .env — secret, keep out of git
SRC_MEDIATYPE = "42"  # house "Seatalk" media type to clone
SRC_HOOK = "https://openapi.seatalk.io/webhook/group/giNuXFuNRWOv_tMcHRJ6uQ"
SG_GROUP, CNGR_GROUP = "507", "512"  # Rooms/Singapore, Rooms/CNGR

ctx = ssl.create_default_context()
if os.environ.get('ZBX_SSL_VERIFY', '1') in ('0', 'false', 'False'):
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE


def rpc(method, params):
    req = urllib.request.Request(URL, data=json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
    r = json.loads(urllib.request.urlopen(req, timeout=100, context=ctx).read())
    if 'error' in r:
        sys.exit(f"{method} ERROR: {r['error']}")
    return r['result']


# 1. media type
src = rpc('mediatype.get', {"mediatypeids": [SRC_MEDIATYPE], "output": "extend",
                            "selectMessageTemplates": "extend"})[0]
script = src['script'].replace(SRC_HOOK, NEW_HOOK)
assert NEW_HOOK in script, "source media type script changed — check SRC_HOOK"

existing = rpc('mediatype.get', {"filter": {"name": "Seatalk-ZoomRooms-CNGR"},
                                 "output": ["mediatypeid"]})
if existing:
    mtid = existing[0]['mediatypeid']
    print("media type exists:", mtid)
else:
    mtid = rpc('mediatype.create', {
        "type": 4, "name": "Seatalk-ZoomRooms-CNGR", "status": 0,
        "script": script,
        "description": "Zoom Room monitor -> SeaTalk group 'CNGR Zoom Room Alerts'. "
                       "Cloned from 'Seatalk' (id 42). Owner: luhl@sea.com",
        "parameters": [{"name": p["name"], "value": p["value"]} for p in src["parameters"]],
        "message_templates": [{k: t[k] for k in ("eventsource", "recovery", "subject", "message")}
                              for t in src["message_templates"]],
    })['mediatypeids'][0]
    print("media type created:", mtid)

# 2. role + user group + user
roles = rpc('role.get', {"filter": {"name": ["User role", "Viewer"]}, "output": ["roleid"]})
if not roles:
    sys.exit("no user-level role named 'User role' or 'Viewer' found — pick one from role.get")
role = roles[0]['roleid']
ug = rpc('usergroup.get', {"filter": {"name": "Zoom Rooms Alerts"}, "output": ["usrgrpid"]})
if ug:
    ugid = ug[0]['usrgrpid']
    print("usergroup exists:", ugid)
else:
    ugid = rpc('usergroup.create', {"name": "Zoom Rooms Alerts", "gui_access": 3,
        "hostgroup_rights": [{"id": SG_GROUP, "permission": 2},
                             {"id": CNGR_GROUP, "permission": 2}]})['usrgrpids'][0]
    print("usergroup created:", ugid)

u = rpc('user.get', {"filter": {"username": "svc-zoomrooms-seatalk"}, "output": ["userid"]})
if u:
    uid = u[0]['userid']
    print("user exists:", uid)
else:
    uid = rpc('user.create', {"username": "svc-zoomrooms-seatalk",
        "name": "Zoom Rooms SeaTalk notifier", "roleid": role,
        "usrgrps": [{"usrgrpid": ugid}],
        # sendto "-": house script @mentions ALERT.SENDTO as emails; "-" mentions nobody
        "medias": [{"mediatypeid": mtid, "sendto": "-", "severity": 63,
                    "active": 0, "period": "1-7,00:00-24:00"}]})['userids'][0]
    print("user created:", uid)

# 3. trigger action
a = rpc('action.get', {"filter": {"name": "Zoom Rooms CNGR - SeaTalk alerts"},
                       "output": ["actionid"]})
if a:
    print("action exists:", a[0]['actionid'])
else:
    aid = rpc('action.create', {
        "name": "Zoom Rooms CNGR - SeaTalk alerts", "eventsource": 0, "status": 0,
        "esc_period": "1h", "pause_suppressed": 1,
        "filter": {"evaltype": 0, "conditions": [
            {"conditiontype": 0, "operator": 0, "value": CNGR_GROUP},   # host group = Rooms/CNGR
            {"conditiontype": 4, "operator": 5, "value": "3"}]},        # severity >= Average
        "operations": [{"operationtype": 0, "esc_step_from": 1, "esc_step_to": 1,
            "opmessage": {"default_msg": 1, "mediatypeid": mtid},
            "opmessage_usr": [{"userid": uid}]}],
        "recovery_operations": [{"operationtype": 0,
            "opmessage": {"default_msg": 1, "mediatypeid": mtid},
            "opmessage_usr": [{"userid": uid}]}],
    })['actionids'][0]
    print("action created:", aid)

print("\nDone. Next CNGR problem (severity >= Average) posts to SeaTalk.")
