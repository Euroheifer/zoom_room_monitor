#!/usr/bin/env bash
# Onboard one region: provision its hosts, then teach the collector about it.
# Alerts and dashboards stay manual — they need a human-created SeaTalk group.
set -euo pipefail
cd "$(dirname "$0")"
[ $# -eq 1 ] || { echo "usage: $0 <REGION>"; exit 1; }
./run_provision.sh "$1"
./run_install_collector.sh
cat <<EOF

Next, by hand:
  1. Create the SeaTalk group + System Account webhook
  2. Add its URL to bridge/.env  (see regions.py for the var name)
  3. python3 setup_seatalk.py <scope...>   (region $1, or its building
     scopes — see SCOPES in setup_seatalk.py)
No dashboard step: the fleet dashboard picks the region up automatically.
EOF
