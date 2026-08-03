// Zoom Room monitoring collector — runs INSIDE Zabbix as a script item.
// Faithful port of bridge/poll.py + mapper.py: Zoom OAuth -> /rooms ->
// device subset (rotating window over online rooms) -> history.push back
// into this Zabbix server's own trapper items.
//
// Item parameters (from host macros, see install_collector.py):
//   account_id, client_id, client_secret  — Zoom S2S OAuth app
//   zbx_url, zbx_token                    — this server's API + token
//   region, subset_size, interval         — SG / 10 / 120 (match poll.py)
//
// Zabbix JS is Duktape (ES5): var/function only, no template literals.

var p = JSON.parse(value);
var SUBSET = parseInt(p.subset_size || '10', 10);
var INTERVAL = parseInt(p.interval || '120', 10);
var REGION = (p.region || 'SG').toUpperCase();
var FLEET_HOST = 'SG-Fleet-Summary';

function getJson(url, headers) {
    var req = new HttpRequest();
    for (var i = 0; i < headers.length; i++) req.addHeader(headers[i]);
    var body = req.get(url);
    if (req.getStatus() !== 200)
        throw 'GET ' + url.split('?')[0] + ': HTTP ' + req.getStatus() + ' ' + String(body).slice(0, 200);
    return JSON.parse(body);
}

function zoomToken() {
    var req = new HttpRequest();
    req.addHeader('Authorization: Basic ' + btoa(p.client_id + ':' + p.client_secret));
    var body = req.post('https://zoom.us/oauth/token?grant_type=account_credentials&account_id='
        + encodeURIComponent(p.account_id), '');
    if (req.getStatus() !== 200)
        throw 'Zoom token: HTTP ' + req.getStatus() + ' ' + String(body).slice(0, 200);
    return JSON.parse(body).access_token;
}

// mapper.sanitize_host_name
function sanitizeHost(name) {
    return name.replace(/[^A-Za-z0-9 ._-]+/g, ' ').replace(/\s+/g, ' ')
        .replace(/^\s+|\s+$/g, '');
}

function fetchRegionRooms(auth) {
    var rooms = [], tok = '';
    while (true) {
        var url = 'https://api.zoom.us/v2/rooms?page_size=300' + (tok ? '&next_page_token=' + tok : '');
        var r = getJson(url, [auth]);
        rooms = rooms.concat(r.rooms || []);
        tok = r.next_page_token || '';
        if (!tok) break;
    }
    var out = [];
    for (var i = 0; i < rooms.length; i++)
        if ((rooms[i].name || '').toUpperCase().indexOf(REGION) === 0) out.push(rooms[i]);
    return out;
}

// poll.choose_subset: rotate over ONLINE rooms; offset derived from wall clock
// since script items keep no state between runs (cycle number * subset size).
function chooseSubset(rooms) {
    var online = [];
    for (var i = 0; i < rooms.length; i++)
        if (rooms[i].status !== 'Offline') online.push(rooms[i]);
    online.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
    if (!online.length) return [];
    var offset = Math.floor(Date.now() / 1000 / INTERVAL) * SUBSET;
    var start = offset % online.length, out = [];
    for (var j = 0; j < Math.min(SUBSET, online.length); j++)
        out.push(online[(start + j) % online.length]);
    return out;
}

// mapper.devices_to_values: collapse by role, worst (offline) status wins.
function deviceValues(devices) {
    var roles = { 'Zoom Rooms Computer': 'computer', 'Controller': 'controller' };
    var vals = {};
    for (var i = 0; i < devices.length; i++) {
        var role = roles[devices[i].device_type || ''];
        if (!role) continue;
        var online = String(devices[i].status || '').toLowerCase() === 'online' ? 1 : 0;
        var key = 'zoom.device.' + role + '.status';
        vals[key] = (key in vals) ? Math.min(vals[key], online) : online;
        var ver = devices[i].app_version || devices[i].device_firmware || '';
        if (ver) vals['zoom.device.' + role + '.version'] = ver;
    }
    return vals;
}

// --- one cycle -----------------------------------------------------------
var auth = 'Authorization: Bearer ' + zoomToken();
var rooms = fetchRegionRooms(auth);
var batch = [], offline = 0, k;

for (var i = 0; i < rooms.length; i++) {
    var status = rooms[i].status || 'Unknown';
    if (status === 'Offline') offline++;
    var host = sanitizeHost(rooms[i].name);
    batch.push({ host: host, key: 'zoom.room.status', value: status });
    batch.push({ host: host, key: 'zoom.room.online', value: String(status === 'Offline' ? 0 : 1) });
}

var subset = chooseSubset(rooms);
for (var s = 0; s < subset.length; s++) {
    var resp;
    try {
        resp = getJson('https://api.zoom.us/v2/rooms/' + subset[s].id + '/devices', [auth]);
    } catch (e) { continue; }  // per-room device fetch is best-effort, like poll.py
    var dv = deviceValues(resp.devices || []);
    for (k in dv) batch.push({ host: sanitizeHost(subset[s].name), key: k, value: String(dv[k]) });
}

var inmeeting = 0;
for (var m = 0; m < rooms.length; m++) if (rooms[m].status === 'InMeeting') inmeeting++;
var fleet = { 'zoom.fleet.total': rooms.length, 'zoom.fleet.offline': offline,
              'zoom.fleet.online': rooms.length - offline, 'zoom.fleet.inmeeting': inmeeting };
for (k in fleet) batch.push({ host: FLEET_HOST, key: k, value: String(fleet[k]) });

// history.push (Zabbix 6.4+) — feeds the same trapper items the Python bridge did.
var req = new HttpRequest();
req.addHeader('Content-Type: application/json-rpc');
req.addHeader('Authorization: Bearer ' + p.zbx_token);
var pushBody = req.post(p.zbx_url, JSON.stringify(
    { jsonrpc: '2.0', method: 'history.push', params: batch, id: 1 }));
if (req.getStatus() !== 200) throw 'history.push: HTTP ' + req.getStatus();
var push = JSON.parse(pushBody);
if (push.error) throw 'history.push: ' + JSON.stringify(push.error);

var failed = 0;
var data = (push.result && push.result.data) || [];
for (var d = 0; d < data.length; d++) if (data[d].error) failed++;

return JSON.stringify({ rooms: rooms.length, offline: offline, subset: subset.length,
                        items: batch.length, failed: failed });
