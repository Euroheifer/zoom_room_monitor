// Check the collector's global device-rotation slice. Run: node test_collector_subset.js
// Extracts chooseSubset() from collector.js so it tests the shipped code, not a copy.
const fs = require('fs'), assert = require('assert');

const src = fs.readFileSync(__dirname + '/collector.js', 'utf8');
const fn = src.match(/function chooseSubset\(entries\) \{[\s\S]*?\n\}/)[0];
const SUBSET = 30, INTERVAL = 300;
let NOW = 1_700_000_000_000;
const chooseSubset = new Function('SUBSET', 'INTERVAL', 'Date',
    fn + '; return chooseSubset;')(SUBSET, INTERVAL, { now: () => NOW });

// 3 regions, 100 rooms each, every 10th offline
const entries = [];
for (const region of ['SG', 'CNGR', 'BR'])
    for (let i = 0; i < 100; i++)
        entries.push({ room: { id: `${region}${i}`, name: `${region}-room-${String(i).padStart(3, '0')}`,
                               status: i % 10 === 0 ? 'Offline' : 'Available' }, region });

const pick = chooseSubset(entries);
assert.strictEqual(pick.length, SUBSET, 'budget is global, not per region');
assert.ok(pick.every(e => e.room.status !== 'Offline'), 'offline rooms are skipped');
assert.strictEqual(new Set(pick.map(e => e.room.id)).size, SUBSET, 'no room twice in one cycle');
assert.ok(pick.every(e => e.room.name.startsWith(e.region)), 'region attribution survives');

// consecutive cycles advance, and the whole fleet is covered without gaps
const seen = new Set();
const online = entries.filter(e => e.room.status !== 'Offline').length;
for (let c = 0; c < Math.ceil(online / SUBSET); c++) {
    chooseSubset(entries).forEach(e => seen.add(e.room.id));
    NOW += INTERVAL * 1000;
}
assert.strictEqual(seen.size, online, `sweep covers all ${online} online rooms, got ${seen.size}`);

// a fleet smaller than the budget must not loop back on itself
const tiny = entries.slice(0, 5).map(e => ({ ...e, room: { ...e.room, status: 'Available' } }));
assert.strictEqual(chooseSubset(tiny).length, 5, 'small fleet returns each room once');

console.log('collector chooseSubset: OK');
