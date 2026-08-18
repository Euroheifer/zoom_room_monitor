#!/usr/bin/env python3
"""Wire Zoom Room alerts to SeaTalk groups, one scope at a time.

A scope is a region or a building inside one: host group + optional host tags
(hosts carry region/building/floor tags from the Zoom location directory, and
Zabbix copies them onto events). Region-wide and building scopes coexist on
purpose — the building crew watches its own group, regional IT keeps the full
view.

Usage:
    set -a && . ./.env && set +a
    python3 setup_seatalk.py             # every scope whose webhook env var is set
    python3 setup_seatalk.py SG-GLX ...  # only these

Idempotent: re-running converges the media type, users and actions to the
state defined below. Scopes with no webhook env var are skipped.

Per scope it ensures:
  user   svc-zoom-<scope>  — routing row; its media "Send to" IS the webhook URL
  action Zoom Rooms <scope> - SeaTalk alerts — host group + severity + tags,
                              problem and recovery, via the shared media type

One shared media type serves every scope (it posts to whatever URL arrives in
{ALERT.SENDTO}), so the message format is maintained in exactly one place.
NOTE: an action sends to ALL of a user's media rows of that media type — hence
one user per scope rather than one user holding many webhooks.
"""
import json
import os
import ssl
import sys
import urllib.request

SCOPES = {
    # region-wide
    "SG":      {"hostgroup": "507", "tags": {}, "webhook_env": "SEATALK_WEBHOOK_URL_SG"},
    "CNGR":    {"hostgroup": "512", "tags": {}, "webhook_env": "SEATALK_WEBHOOK_URL"},
    # SG buildings — GLX ~20 alerts/day, RC ~6, 5SPD ~3 (14d sample, 2026-08-18).
    # Small sites (Cogent/LCS/Pandan/home) and the fleet watchdog stay with SG:
    # SG-Fleet-Summary carries no building tag, so only the region scope sees it.
    "SG-GLX":  {"hostgroup": "507", "tags": {"building": "GLX"},
                "webhook_env": "SEATALK_WEBHOOK_URL_SG_GLX"},
    "SG-RC":   {"hostgroup": "507", "tags": {"building": "RC"},
                "webhook_env": "SEATALK_WEBHOOK_URL_SG_RC"},
    "SG-5SPD": {"hostgroup": "507", "tags": {"building": "5SPD"},
                "webhook_env": "SEATALK_WEBHOOK_URL_SG_5SPD"},
}
MIN_SEVERITY = "3"          # Average and above (device disconnects + offline)
MT_NAME = "Seatalk-ZoomRooms"
UG_NAME = "Zoom Rooms Alerts"

# Duktape (ES5) — no let/const/arrow/template literals. Emoji stay as \uXXXX
# escapes: proven to survive the API round-trip and Duktape's source parser.
MT_SCRIPT = r"""try {
    var p = JSON.parse(value);
    if (!p.webhook || p.webhook.indexOf('http') !== 0)
        throw 'ALERT.SENDTO must be the SeaTalk webhook URL, got: ' + String(p.webhook).slice(0, 40);

    // one issue per bullet; dashboards label severity 3 "Medium", not "Average"
    var msg = p.alert_message.split('; ').join('\n- ')
        .replace('**Severity:** Average', '**Severity:** Medium');
    // green on recovery, red for High and above, yellow below
    var dot = (p.event_value === '0') ? '\ud83d\udfe2'
        : (parseInt(p.nseverity, 10) >= 4 ? '\ud83d\udd34' : '\ud83d\udfe1');

    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json');
    // format:1 renders markdown in SeaTalk (format:2 shows literal asterisks)
    var resp = req.post(p.webhook, JSON.stringify(
        { tag: 'text', text: { format: 1, content: dot + ' ' + p.alert_subject + '\n' + msg } }));
    if (req.getStatus() !== 200)
        throw 'HTTP ' + req.getStatus() + ' ' + String(resp).slice(0, 200);
    var r = JSON.parse(resp);
    if (r.code) throw 'SeaTalk code ' + r.code + ' ' + (r.msg || '');
    return 'OK';
}
catch (error) {
    Zabbix.log(3, '[ SeaTalk ZoomRooms ] ' + error);
    throw 'Failed with error: ' + error;
}
"""
MT_PARAMETERS = [
    {"name": "alert_subject", "value": "{ALERT.SUBJECT}"},
    {"name": "alert_message", "value": "{ALERT.MESSAGE}"},
    {"name": "webhook", "value": "{ALERT.SENDTO}"},
    {"name": "nseverity", "value": "{EVENT.NSEVERITY}"},
    {"name": "event_value", "value": "{EVENT.VALUE}"},
]
# no event timestamp: the chat bubble's own time is within one 5-min poll of the
# event and renders in each viewer's timezone
MT_TEMPLATES = [
    {"eventsource": 0, "recovery": 0, "subject": "**{HOST.NAME}**",
     "message": "\n**Severity:** {EVENT.SEVERITY}\n\n**Issue:**\n- {EVENT.NAME}"},
    {"eventsource": 0, "recovery": 1, "subject": "**{HOST.NAME}**",
     "message": "\n**Resolved after** {EVENT.DURATION}\n\n**Issue:**\n- {EVENT.NAME}"},
]

URL = os.environ['ZBX_API_URL']
TOKEN = os.environ['ZBX_API_TOKEN']
ctx = ssl.create_default_context()
if os.environ.get('ZBX_SSL_VERIFY', '1') in ('0', 'false', 'False'):
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE


def rpc(method, params):
    req = urllib.request.Request(URL, data=json.dumps(
        {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
    r = json.loads(urllib.request.urlopen(req, timeout=120, context=ctx).read())
    if 'error' in r:
        sys.exit(f"{method} ERROR: {r['error']}")
    return r['result']


def ensure_media_type():
    body = {"type": 4, "name": MT_NAME, "status": 0, "script": MT_SCRIPT,
            "description": "Zoom Room alerts -> SeaTalk. Webhook URL comes from each "
                           "receiving user's media 'Send to'. Owner: luhl@sea.com",
            "parameters": MT_PARAMETERS, "message_templates": MT_TEMPLATES}
    got = rpc('mediatype.get', {"filter": {"name": MT_NAME}, "output": ["mediatypeid"]})
    if got:
        mtid = got[0]['mediatypeid']
        rpc('mediatype.update', {"mediatypeid": mtid, **body})
        print(f"media type {MT_NAME}: updated ({mtid})")
    else:
        mtid = rpc('mediatype.create', body)['mediatypeids'][0]
        print(f"media type {MT_NAME}: created ({mtid})")
    return mtid


def ensure_usergroup():
    # read access to every scope's host group — Zabbix silently drops alerts for
    # hosts the receiving user cannot read, so re-assert rights on every run
    rights = [{"id": g, "permission": 2}
              for g in sorted({s["hostgroup"] for s in SCOPES.values()})]
    got = rpc('usergroup.get', {"filter": {"name": UG_NAME}, "output": ["usrgrpid"]})
    if got:
        ugid = got[0]['usrgrpid']
        rpc('usergroup.update', {"usrgrpid": ugid, "hostgroup_rights": rights})
        print(f"usergroup {UG_NAME}: rights ensured ({ugid})")
    else:
        ugid = rpc('usergroup.create', {"name": UG_NAME, "gui_access": 3,
                                        "hostgroup_rights": rights})['usrgrpids'][0]
        print(f"usergroup {UG_NAME}: created ({ugid})")
    return ugid


def ensure_user(scope, webhook, mtid, ugid, roleid):
    username = "svc-zoom-" + scope.lower()
    media = [{"mediatypeid": mtid, "sendto": webhook, "severity": 63,
              "active": 0, "period": "1-7,00:00-24:00"}]
    got = rpc('user.get', {"filter": {"username": username}, "output": ["userid"]})
    if got:
        uid = got[0]['userid']
        rpc('user.update', {"userid": uid, "medias": media})
        print(f"  user {username}: media ensured ({uid})")
    else:
        uid = rpc('user.create', {"username": username, "name": f"Zoom alerts {scope}",
                                  "roleid": roleid, "usrgrps": [{"usrgrpid": ugid}],
                                  "medias": media})['userids'][0]
        print(f"  user {username}: created ({uid})")
    return uid


def ensure_action(scope, cfg, mtid, uid):
    name = f"Zoom Rooms {scope} - SeaTalk alerts"
    conditions = [
        {"conditiontype": 0, "operator": 0, "value": cfg["hostgroup"]},      # host group
        {"conditiontype": 4, "operator": 5, "value": MIN_SEVERITY},          # severity >=
    ]
    # event tag value (26): value2 = tag name, value = tag value, operator 0 = equals
    for tag, val in sorted(cfg["tags"].items()):
        conditions.append({"conditiontype": 26, "operator": 0, "value": val, "value2": tag})
    opmessage = {"default_msg": 1, "mediatypeid": mtid}
    body = {
        "name": name, "eventsource": 0, "status": 0, "esc_period": "1h",
        "pause_suppressed": 1,
        "filter": {"evaltype": 0, "conditions": conditions},   # and/or
        "operations": [{"operationtype": 0, "esc_step_from": 1, "esc_step_to": 1,
                        "opmessage": opmessage, "opmessage_usr": [{"userid": uid}]}],
        "recovery_operations": [{"operationtype": 0, "opmessage": opmessage,
                                 "opmessage_usr": [{"userid": uid}]}],
    }
    got = rpc('action.get', {"filter": {"name": name}, "output": ["actionid"]})
    if got:
        aid = got[0]['actionid']
        rpc('action.update', {"actionid": aid, **body})
        print(f"  action: updated ({aid})")
    else:
        aid = rpc('action.create', body)['actionids'][0]
        print(f"  action: created ({aid})")
    return aid


def main():
    asked = [a.upper() for a in sys.argv[1:]]
    unknown = [a for a in asked if a not in SCOPES]
    if unknown:
        sys.exit(f"unknown scope(s): {unknown}. Known: {sorted(SCOPES)}")

    todo = {}
    for scope, cfg in SCOPES.items():
        if asked and scope not in asked:
            continue
        webhook = os.environ.get(cfg["webhook_env"], "").strip()
        if not webhook:
            print(f"{scope}: skipped — {cfg['webhook_env']} not set in .env")
            continue
        todo[scope] = webhook
    if not todo:
        sys.exit("nothing to do: no scope has its webhook env var set")

    roles = rpc('role.get', {"filter": {"name": ["User role", "Viewer"]}, "output": ["roleid"]})
    if not roles:
        sys.exit("no user-level role named 'User role' or 'Viewer' — pick one from role.get")
    roleid = roles[0]['roleid']

    mtid = ensure_media_type()
    ugid = ensure_usergroup()
    for scope, webhook in todo.items():
        print(f"{scope}:")
        uid = ensure_user(scope, webhook, mtid, ugid, roleid)
        ensure_action(scope, SCOPES[scope], mtid, uid)

    print(f"\nDone: {', '.join(todo)}. Next matching problem posts to SeaTalk.")
    print("Superseded by this run (delete in the UI once alerts look right): "
          "media types Seatalk-ZoomRooms-SG / -CNGR, user svc-zoomrooms-seatalk.")


if __name__ == "__main__":
    main()
