#!/usr/bin/env python3
"""One-shot, idempotent: wire a region's Zoom Room alerts to SeaTalk.

Usage: python3 setup_seatalk.py CNGR|SG
(with ZBX_API_URL, ZBX_API_TOKEN and the region's webhook var from .env)

Creates on zabbix.cit.insea.io per region:
  1. media type "Seatalk-ZoomRooms-<region>" — clone of the house "Seatalk"
     webhook media type (id 42) with the region's group webhook URL and
     chat-friendly message templates
  2. user group "Zoom Rooms Alerts" (no frontend, read on Rooms/* groups)
     + user "svc-zoomrooms-seatalk" carrying one media per region
  3. trigger action "Zoom Rooms <region> - SeaTalk alerts"
     (host group, severity >= Average, problem + recovery)
"""
import json, os, ssl, sys, urllib.request

REGIONS = {
    "CNGR": {"hostgroup": "512", "webhook_env": "SEATALK_WEBHOOK_URL"},
    "SG":   {"hostgroup": "507", "webhook_env": "SEATALK_WEBHOOK_URL_SG"},
}

if len(sys.argv) != 2 or sys.argv[1].upper() not in REGIONS:
    sys.exit(f"usage: {sys.argv[0]} {'|'.join(REGIONS)}")
REGION = sys.argv[1].upper()
CFG = REGIONS[REGION]

URL = os.environ['ZBX_API_URL']
TOKEN = os.environ['ZBX_API_TOKEN']
NEW_HOOK = os.environ[CFG['webhook_env']]  # from .env — secret, keep out of git
SRC_MEDIATYPE = "42"  # house "Seatalk" media type to clone
SRC_HOOK = "https://openapi.seatalk.io/webhook/group/giNuXFuNRWOv_tMcHRJ6uQ"
MT_NAME = f"Seatalk-ZoomRooms-{REGION}"
ACTION_NAME = f"Zoom Rooms {REGION} - SeaTalk alerts"

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
# one issue per line in chat: {EVENT.NAME} joins issues with "; ", macros can't split it
_ANCHOR = "var email_list;"
assert _ANCHOR in script, "source media type script changed — check _ANCHOR"
script = script.replace(
    _ANCHOR,
    'params.alert_message = params.alert_message.split("; ").join("\\n- ");\n'
    # dashboards label Zabbix severity 3 "Medium"; keep chat wording identical
    'params.alert_message = params.alert_message.replace("**Severity:** Average", "**Severity:** Medium");\n'
    # green circle on recovery, red on High+, yellow below (emoji as JS escapes)
    'params.alert_subject = (params.event_value === "0" ? "\\ud83d\\udfe2" : '
    '(parseInt(params.nseverity, 10) >= 4 ? "\\ud83d\\udd34" : "\\ud83d\\udfe1")) + '
    '" " + params.alert_subject;\n\n'
    + _ANCHOR)

# compact chat-friendly templates (house ones repeat the problem name 3x).
# No event timestamp: the chat bubble's own time is within one 5-min poll of
# the event and renders in each viewer's timezone. SeaTalk renders markdown
# when the webhook payload has format:1 (house default).
OVERRIDES = {
    ('0', '0'): {"subject": "**{HOST.NAME}**",
                 "message": "\n**Severity:** {EVENT.SEVERITY}\n\n**Issue:**\n- {EVENT.NAME}"},
    ('0', '1'): {"subject": "**{HOST.NAME}**",
                 "message": "\n**Resolved after** {EVENT.DURATION}\n\n**Issue:**\n- {EVENT.NAME}"},
}

existing = rpc('mediatype.get', {"filter": {"name": MT_NAME}, "output": ["mediatypeid"]})
if existing:
    mtid = existing[0]['mediatypeid']
    print("media type exists:", mtid)
else:
    mtid = rpc('mediatype.create', {
        "type": 4, "name": MT_NAME, "status": 0,
        "script": script,
        "description": f"Zoom Room monitor -> SeaTalk group '{REGION} Zoom Room Alerts'. "
                       "Cloned from 'Seatalk' (id 42). Owner: luhl@sea.com",
        "parameters": [{"name": p["name"], "value": p["value"]} for p in src["parameters"]]
                      + [{"name": "nseverity", "value": "{EVENT.NSEVERITY}"},
                         {"name": "event_value", "value": "{EVENT.VALUE}"}],
        "message_templates": [
            {**{k: t[k] for k in ("eventsource", "recovery", "subject", "message")},
             **OVERRIDES.get((t["eventsource"], t["recovery"]), {})}
            for t in src["message_templates"]],
    })['mediatypeids'][0]
    print("media type created:", mtid)

# 2. role + user group + user (shared across regions)
roles = rpc('role.get', {"filter": {"name": ["User role", "Viewer"]}, "output": ["roleid"]})
if not roles:
    sys.exit("no user-level role named 'User role' or 'Viewer' found — pick one from role.get")
role = roles[0]['roleid']

# read access to every region's host group — Zabbix silently drops alerts
# for hosts the receiving user can't read, so re-assert rights on every run
rights = [{"id": g["hostgroup"], "permission": 2} for g in REGIONS.values()]
ug = rpc('usergroup.get', {"filter": {"name": "Zoom Rooms Alerts"}, "output": ["usrgrpid"]})
if ug:
    ugid = ug[0]['usrgrpid']
    rpc('usergroup.update', {"usrgrpid": ugid, "hostgroup_rights": rights})
    print("usergroup exists, rights ensured:", ugid)
else:
    ugid = rpc('usergroup.create', {"name": "Zoom Rooms Alerts", "gui_access": 3,
        "hostgroup_rights": rights})['usrgrpids'][0]
    print("usergroup created:", ugid)

# sendto "-": house script @mentions ALERT.SENDTO as emails; "-" mentions nobody
new_media = {"mediatypeid": mtid, "sendto": "-", "severity": 63,
             "active": 0, "period": "1-7,00:00-24:00"}
u = rpc('user.get', {"filter": {"username": "svc-zoomrooms-seatalk"},
                     "output": ["userid"], "selectMedias": "extend"})
if u:
    uid = u[0]['userid']
    medias = [{k: m[k] for k in ("mediatypeid", "sendto", "severity", "active", "period")}
              for m in u[0]['medias']]
    if any(m['mediatypeid'] == mtid for m in medias):
        print("user exists with this media:", uid)
    else:
        rpc('user.update', {"userid": uid, "medias": medias + [new_media]})
        print("user exists, media added:", uid)
else:
    uid = rpc('user.create', {"username": "svc-zoomrooms-seatalk",
        "name": "Zoom Rooms SeaTalk notifier", "roleid": role,
        "usrgrps": [{"usrgrpid": ugid}],
        "medias": [new_media]})['userids'][0]
    print("user created:", uid)

# 3. trigger action
a = rpc('action.get', {"filter": {"name": ACTION_NAME}, "output": ["actionid"]})
if a:
    print("action exists:", a[0]['actionid'])
else:
    aid = rpc('action.create', {
        "name": ACTION_NAME, "eventsource": 0, "status": 0,
        "esc_period": "1h", "pause_suppressed": 1,
        "filter": {"evaltype": 0, "conditions": [
            {"conditiontype": 0, "operator": 0, "value": CFG["hostgroup"]},  # host group
            {"conditiontype": 4, "operator": 5, "value": "3"}]},             # severity >= Average
        "operations": [{"operationtype": 0, "esc_step_from": 1, "esc_step_to": 1,
            "opmessage": {"default_msg": 1, "mediatypeid": mtid},
            "opmessage_usr": [{"userid": uid}]}],
        "recovery_operations": [{"operationtype": 0,
            "opmessage": {"default_msg": 1, "mediatypeid": mtid},
            "opmessage_usr": [{"userid": uid}]}],
    })['actionids'][0]
    print("action created:", aid)

print(f"\nDone. Next {REGION} problem (severity >= Average) posts to SeaTalk.")
