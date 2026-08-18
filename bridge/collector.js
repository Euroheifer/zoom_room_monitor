// Zoom Room monitoring collector — runs INSIDE Zabbix as a script item.
// Faithful port of bridge/poll.py + mapper.py: Zoom OAuth -> /rooms ->
// device subset (rotating window over online rooms) -> history.push back
// into this Zabbix server's own trapper items.
//
// ONE item covers ALL regions: the account-wide /rooms and /metrics sweeps
// happen once per cycle and rooms are bucketed per region here, instead of
// one item per region each repeating the same sweeps.
//
// Item parameters (from host macros, see install_collector.py):
//   account_id, client_id, client_secret  — Zoom S2S OAuth app
//   zbx_url, zbx_token                    — this server's API + token
//   regions             — JSON list [{name, location_root?, fleet_host?}];
//                         rooms are selected by the location-directory subtree
//                         under the node named location_root (default: name) —
//                         the directory is the single source of truth, room
//                         naming conventions are NOT trusted
//   carrier_fleet_host  — host this item lives on (gets its summary from the
//                         script return; other regions get theirs pushed to
//                         their fleet host's zoom.bridge.run trapper item)
//   subset_size, interval — device-detail rotation budget, GLOBAL across all
//                           regions (30 / 300): API cost stays flat as regions
//                           are added; the sweep just takes longer, so keep
//                           ceil(total_rooms/subset)*interval under
//                           DEVICE_STALE_WINDOW (provision.py)
//
// Zabbix JS is Duktape (ES5): var/function only, no template literals.

var p = JSON.parse(value);
var SUBSET = parseInt(p.subset_size || '10', 10);
var INTERVAL = parseInt(p.interval || '120', 10);
var REGIONS = JSON.parse(p.regions);
var CARRIER = p.carrier_fleet_host;

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

function fetchPaged(auth, path, listKey) {
    var out = [], tok = '';
    while (true) {
        var url = 'https://api.zoom.us/v2' + path + '?page_size=300' + (tok ? '&next_page_token=' + tok : '');
        var r = getJson(url, [auth]);
        out = out.concat(r[listKey] || []);
        tok = r.next_page_token || '';
        if (!tok) break;
    }
    return out;
}

// All location ids at or under the directory node named `root`.
function locationSubtree(locs, root) {
    var sub = {}, i, changed = true;
    for (i = 0; i < locs.length; i++)
        if (locs[i].name === root) sub[locs[i].id] = true;
    while (changed) {
        changed = false;
        for (i = 0; i < locs.length; i++)
            if (!sub[locs[i].id] && sub[locs[i].parent_location_id]) {
                sub[locs[i].id] = true; changed = true;
            }
    }
    return sub;
}

// poll.choose_subset: rotate over ONLINE rooms; offset derived from wall clock
// since script items keep no state between runs (cycle number * subset size).
// `entries` are {room, region} across ALL regions — one shared budget keeps the
// per-cycle Zoom call count flat no matter how many regions exist.
function chooseSubset(entries) {
    var online = [];
    for (var i = 0; i < entries.length; i++)
        if (entries[i].room.status !== 'Offline') online.push(entries[i]);
    online.sort(function (a, b) {
        return a.room.name < b.room.name ? -1 : a.room.name > b.room.name ? 1 : 0;
    });
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
var allRooms = fetchPaged(auth, '/rooms', 'rooms');
var locs = fetchPaged(auth, '/rooms/locations', 'locations');

var batch = [], regionOf = [];   // regionOf[i] = region name of batch[i]
var perRegion = {};              // name -> {rooms, offline, subset, fleet_host}
var regionByHost = {}, uc = {};  // sanitized host -> region name / under construction
var candidates = [];             // {room, region} for the global device rotation
var k, i, r;

for (r = 0; r < REGIONS.length; r++) {
    var cfg = REGIONS[r];
    var name = cfg.name.toUpperCase();
    var fleetHost = cfg.fleet_host || (name + '-Fleet-Summary');
    var sub = locationSubtree(locs, cfg.location_root || cfg.name);

    var rooms = [];
    for (i = 0; i < allRooms.length; i++)
        if (sub[allRooms[i].location_id]) rooms.push(allRooms[i]);

    var offline = 0, inmeeting = 0;
    for (i = 0; i < rooms.length; i++) {
        var status = rooms[i].status || 'Unknown';
        if (status === 'Offline') offline++;
        if (status === 'InMeeting') inmeeting++;
        var host = sanitizeHost(rooms[i].name);
        regionByHost[host] = name;
        // rooms marked Under Construction in Zoom admin: suppress issue alerts
        if (status === 'UnderConstruction') uc[host] = true;
        batch.push({ host: host, key: 'zoom.room.status', value: status });
        batch.push({ host: host, key: 'zoom.room.online', value: String(status === 'Offline' ? 0 : 1) });
        regionOf.push(name); regionOf.push(name);
        candidates.push({ room: rooms[i], region: name });
    }

    var fleet = { 'zoom.fleet.total': rooms.length, 'zoom.fleet.offline': offline,
                  'zoom.fleet.online': rooms.length - offline, 'zoom.fleet.inmeeting': inmeeting };
    for (k in fleet) {
        batch.push({ host: fleetHost, key: k, value: String(fleet[k]) });
        regionOf.push(name);
    }

    perRegion[name] = { rooms: rooms.length, offline: offline, subset: 0,
                        fleet_host: fleetHost };
}

// device detail for one rotating slice of the whole fleet (shared budget)
var subset = chooseSubset(candidates);
for (var s = 0; s < subset.length; s++) {
    var resp;
    try {
        resp = getJson('https://api.zoom.us/v2/rooms/' + subset[s].room.id + '/devices', [auth]);
    } catch (e) { continue; }  // per-room device fetch is best-effort, like poll.py
    var dv = deviceValues(resp.devices || []);
    perRegion[subset[s].region].subset++;
    for (k in dv) {
        batch.push({ host: sanitizeHost(subset[s].room.name), key: k, value: String(dv[k]) });
        regionOf.push(subset[s].region);
    }
}

// Dashboard metrics: fleet-wide per-room health + component issues (mic /
// speaker / camera / controller) in one paged call; keep only our rooms.
try {
    var metrics = fetchPaged(auth, '/metrics/zoomrooms', 'zoom_rooms');
    for (var g = 0; g < metrics.length; g++) {
        var mh = sanitizeHost(metrics[g].room_name || '');
        if (!regionByHost[mh]) continue;
        var probs = [];
        var raw = metrics[g].issues || [];
        for (var q = 0; q < raw.length; q++) if (raw[q]) probs.push(raw[q]);
        batch.push({ host: mh, key: 'zoom.room.health', value: metrics[g].health || 'unknown' });
        batch.push({ host: mh, key: 'zoom.room.issues', value: (probs.length && !uc[mh]) ? probs.join('; ') : 'none' });
        regionOf.push(regionByHost[mh]); regionOf.push(regionByHost[mh]);
    }
} catch (e) { /* metrics scope optional — room/device data still flows without it */ }

// history.push (Zabbix 6.4+) — feeds the same trapper items the Python bridge did.
function historyPush(params) {
    var req = new HttpRequest();
    req.addHeader('Content-Type: application/json-rpc');
    req.addHeader('Authorization: Bearer ' + p.zbx_token);
    var body = req.post(p.zbx_url, JSON.stringify(
        { jsonrpc: '2.0', method: 'history.push', params: params, id: 1 }));
    if (req.getStatus() !== 200) throw 'history.push: HTTP ' + req.getStatus();
    var push = JSON.parse(body);
    if (push.error) throw 'history.push: ' + JSON.stringify(push.error);
    return (push.result && push.result.data) || [];
}

var data = historyPush(batch);
for (var d = 0; d < data.length; d++) if (data[d].error) {
    var rg = perRegion[regionOf[d]];
    if (rg) rg.failed = (rg.failed || 0) + 1;
}

// per-region cycle summaries -> zoom.bridge.run on each non-carrier fleet
// host (keeps the per-region nodata triggers meaningful); the carrier's
// summary is this script's return value.
var summaries = {}, remote = [];
for (k in perRegion) {
    r = perRegion[k];
    summaries[k] = { rooms: r.rooms, offline: r.offline, subset: r.subset, failed: r.failed || 0 };
    if (r.fleet_host !== CARRIER)
        remote.push({ host: r.fleet_host, key: 'zoom.bridge.run', value: JSON.stringify(summaries[k]) });
}
if (remote.length) historyPush(remote);

return JSON.stringify({ regions: summaries, items: batch.length });
