#!/usr/bin/env bash
# Install the proof token server beside ytdlp-web, and the yt-dlp plugin
# that asks it. Run as root on the server. Safe to run again.
#
# YouTube hands a proof token to a browser and holds its streams from a
# server without one. This server mints the token, and yt-dlp asks it
# through the plugin. See deploy/README.md section 12.
set -euo pipefail

VERSION="${POT_VERSION:-2.0.0}"          # plugin and server share a version
APP="${YTDLP_WEB_HOME:-/opt/ytdlp-web}"
HOME_DIR="${POT_HOME:-/opt/bgutil-ytdlp-pot-provider}"
STATE="${YTDLP_WEB_STATE:-/var/lib/ytdlp-web}"
SERVICE_USER="${YTDLP_WEB_USER:-ytdlp}"
DENO="${DENO:-/usr/local/bin/deno}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
MANAGE_SERVICE="${MANAGE_SERVICE:-yes}"  # "no" installs the files and stops

say() { printf '\n== %s\n' "$*"; }

# A proxy and its certificate, when the server sits behind one. sudo drops
# the environment, so these are carried across by hand.
passthrough() {
    local name
    for name in HTTPS_PROXY HTTP_PROXY NO_PROXY ALL_PROXY https_proxy http_proxy \
                no_proxy SSL_CERT_FILE SSL_CERT_DIR DENO_CERT NODE_EXTRA_CA_CERTS; do
        if [ -n "${!name:-}" ]; then printf '%s=%s\n' "$name" "${!name}"; fi
    done
}

say "Checking deno"
if ! "$DENO" --version >/dev/null 2>&1; then
    cat >&2 <<'EOF'
deno is not installed at /usr/local/bin/deno. Install it first:

  apt install -y unzip
  curl -fsSL -o /tmp/deno.zip \
    https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip
  unzip -o /tmp/deno.zip -d /usr/local/bin
  chmod 755 /usr/local/bin/deno
EOF
    exit 1
fi
"$DENO" --version | head -1

say "Fetching the server source, version $VERSION"
if [ -d "$HOME_DIR/.git" ]; then
    git -C "$HOME_DIR" fetch --quiet --depth 1 origin "refs/tags/$VERSION:refs/tags/$VERSION"
    git -C "$HOME_DIR" checkout --quiet "$VERSION"
else
    git -c advice.detachedHead=false clone --quiet --single-branch \
        --branch "$VERSION" --depth 1 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$HOME_DIR"
fi
mkdir -p "$STATE/deno"
chown -R "$SERVICE_USER:$SERVICE_USER" "$HOME_DIR" "$STATE/deno"

say "Installing the server's dependencies as $SERVICE_USER"
# The cache lands where the unit points DENO_DIR, so the service finds it.
# canvas ships a native part, and its build script is the one allowed.
(
    cd "$HOME_DIR/server"
    # shellcheck disable=SC2046
    sudo -u "$SERVICE_USER" env HOME="$STATE" DENO_DIR="$STATE/deno" \
        DENO_NO_PROMPT=1 DENO_NO_UPDATE_CHECK=1 $(passthrough) \
        "$DENO" install --allow-scripts=npm:canvas --frozen 2>&1 | tail -3
)

say "Installing the yt-dlp plugin into the application's virtual environment"
"$APP/.venv/bin/python" -m pip install --quiet --upgrade --disable-pip-version-check "bgutil-ytdlp-pot-provider==$VERSION"
"$APP/.venv/bin/python" -m pip show bgutil-ytdlp-pot-provider | grep -E "^(Name|Version):"

say "Installing the unit"
install -o root -g root -m 644 "$APP/deploy/ytdlp-pot.service" "$UNIT_DIR/ytdlp-pot.service"

if [ "$MANAGE_SERVICE" != "yes" ]; then
    say "Files are in place. MANAGE_SERVICE=$MANAGE_SERVICE, so the service is left to you."
    exit 0
fi

systemctl daemon-reload
systemctl enable --now ytdlp-pot

say "Waiting for the server to answer"
for _ in $(seq 1 30); do
    if answer="$(curl -fsS -m 3 http://127.0.0.1:4416/ping 2>/dev/null)"; then
        printf '%s\n' "$answer"
        break
    fi
    sleep 1
done
if [ -z "${answer:-}" ]; then
    echo "The server did not answer on 127.0.0.1:4416. See: journalctl -u ytdlp-pot -n 50" >&2
    exit 1
fi

say "Restarting ytdlp-web, so it notices the server"
systemctl restart ytdlp-web
sleep 2
journalctl -u ytdlp-web -n 20 --no-pager | grep -i "proof token" || true
say "Done"
