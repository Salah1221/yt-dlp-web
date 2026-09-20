# Deploy ytdlp-web on Debian 12 or Ubuntu 22.04+

This guide installs the application on one server. The application listens on `127.0.0.1:8000`. nginx terminates TLS and passes the requests to it. Port 8000 stays closed to the outside.

Run every command as root, or put `sudo` in front of it.

## What you need before you start

| Item | Value |
| --- | --- |
| Operating system | Debian 12, or Ubuntu 22.04 and later |
| Python | 3.11 or later |
| Domain name | a name that points to this server (this guide writes `example.com`) |
| TLS certificate | a certificate file and a private key file that you already own |
| Access | root or sudo on the server |

This guide covers two routes for the certificate. You place your own files, or you let Let's Encrypt issue and renew them. Section 7 describes both.

## 1. Install the packages

```bash
apt update
apt install -y python3 python3-venv python3-pip ffmpeg nginx rsync
```

Check the Python version:

```bash
python3 --version
```

The output must show 3.11 or later.

## 2. Create the user and the work directory

The service runs as a dedicated user that cannot log in.

```bash
adduser --system --group --no-create-home --home /opt/ytdlp-web --shell /usr/sbin/nologin ytdlp
mkdir -p /var/lib/ytdlp-web/work
chown -R ytdlp:ytdlp /var/lib/ytdlp-web
chmod 750 /var/lib/ytdlp-web /var/lib/ytdlp-web/work
```

## 3. Put the application code in place

The GitHub Actions deploy fills this folder with rsync, so there is nothing to clone here and the server needs no GitHub credential.

Make the folder and give it to the deploy user:

```bash
adduser --disabled-password --gecos "" deploy
mkdir -p /opt/ytdlp-web
chown -R deploy:deploy /opt/ytdlp-web
chmod 755 /opt/ytdlp-web
```

The folder is readable by every user on the machine, and that is correct. The code holds no secret. The password lives in `/etc/yt-dlp-web/ytdlp-web.env`, which only root can read.

To deploy by hand instead, send the files from your own checkout:

```bash
rsync -az --delete --exclude '.git/' --exclude '.venv/'       ./ deploy@your.server.address:/opt/ytdlp-web/
```

After either route, the file `/opt/ytdlp-web/app/main.py` must exist.

## 4. Create the virtual environment

Skip this section if you use GitHub Actions. The first deploy makes the virtual environment by itself, which is why the first run takes longer than the ones after it.

To make it by hand:

```bash
sudo -u deploy python3 -m venv /opt/ytdlp-web/.venv
sudo -u deploy /opt/ytdlp-web/.venv/bin/pip install --upgrade pip
sudo -u deploy /opt/ytdlp-web/.venv/bin/pip install -r /opt/ytdlp-web/requirements.txt
```

Check that uvicorn is present:

```bash
/opt/ytdlp-web/.venv/bin/python -m uvicorn --version
```

## 5. Write the environment file

The file holds the password, so it lives in its own directory and only root may read it.

```bash
mkdir -p /etc/yt-dlp-web
chown root:root /etc/yt-dlp-web
chmod 755 /etc/yt-dlp-web
```

Copy the template. Take it from `/opt/ytdlp-web/deploy/` when the code is already there, or from wherever you copied it if this is a first bring-up:

```bash
install -o root -g root -m 600         /opt/ytdlp-web/deploy/ytdlp-web.env.example         /etc/yt-dlp-web/ytdlp-web.env
```

Generate a password:

```bash
openssl rand -base64 24
```

Open `/etc/yt-dlp-web/ytdlp-web.env` and paste the output into the `YTDLP_WEB_PASSWORD` line. Keep the other values as they are. In particular keep `YTDLP_WEB_HOST=127.0.0.1`, because nginx sits in front of the application.

Confirm the mode:

```bash
ls -l /etc/yt-dlp-web/ytdlp-web.env
```

The output must show `-rw------- 1 root root`.

## 6. Install the systemd unit

```bash
install -o root -g root -m 644 /opt/ytdlp-web/deploy/ytdlp-web.service /etc/systemd/system/ytdlp-web.service
systemctl daemon-reload
systemctl enable --now ytdlp-web
systemctl status ytdlp-web --no-pager
```

The status must show `active (running)`.

Test the application before you put nginx in front of it:

```bash
curl -i http://127.0.0.1:8000/
```

A `200` answer means the application works.

## 7. Place the certificate and the key

Create the directory:

```bash
mkdir -p /etc/ssl/ytdlp-web
chmod 700 /etc/ssl/ytdlp-web
```

Copy your two files into it. Use these paths, owners and modes.

| File | Path | Owner | Mode | Content |
| --- | --- | --- | --- | --- |
| Certificate chain | `/etc/ssl/ytdlp-web/fullchain.pem` | root:root | 644 | your leaf certificate first, then the intermediate certificates |
| Private key | `/etc/ssl/ytdlp-web/privkey.pem` | root:root | 600 | the private key only |

```bash
chown root:root /etc/ssl/ytdlp-web/fullchain.pem /etc/ssl/ytdlp-web/privkey.pem
chmod 644 /etc/ssl/ytdlp-web/fullchain.pem
chmod 600 /etc/ssl/ytdlp-web/privkey.pem
```

The order inside `fullchain.pem` matters. Put your own certificate at the top of the file. Put the intermediate certificates of the issuer under it. Do not add the root certificate. A chain file without the intermediates breaks the site on some devices.

Check that the key belongs to the certificate. The two commands must print the same hash.

```bash
openssl x509 -in /etc/ssl/ytdlp-web/fullchain.pem -noout -pubkey | openssl sha256
openssl pkey -in /etc/ssl/ytdlp-web/privkey.pem -pubout | openssl sha256
```

`openssl pkey` reads an RSA key and an elliptic curve key. The older `openssl rsa` form fails on an elliptic curve key, and Let's Encrypt issues those by default.

Your provider may also give a public key file. Do not install it. nginx never reads one, because the public key is already inside the certificate.

## 7b. Let's Encrypt, with automatic renewal

A certificate that you install by hand expires, and the site then stops working with no warning. This route renews without you.

### A certificate for one host

Use this when you need `yt-dlp.example.com` only. It needs no API credential.

Let's Encrypt fetches a file over plain HTTP to prove that you control the name. The nginx site file in this folder already serves that path and does not redirect it.

```bash
apt install -y certbot
mkdir -p /var/www/certbot
certbot certonly --webroot -w /var/www/certbot -d yt-dlp.example.com
```

### A wildcard certificate

Use this when the same certificate must serve several hosts on one domain.

Let's Encrypt issues a wildcard only through the DNS-01 challenge. The tool has to create a TXT record at `_acme-challenge.<your domain>`, so it needs an API credential for your DNS provider. That credential can change every record on the account, and it lives on this server.

A wildcard covers one level only. `*.example.com` covers `a.example.com`. It does not cover `example.com` itself, and it does not cover `a.b.example.com`. Name both when you need both.

Install certbot and the plugin for your DNS provider in their own virtual environment, so the plugin and certbot always share one Python:

```bash
python3 -m venv /opt/certbot
/opt/certbot/bin/pip install --upgrade pip
/opt/certbot/bin/pip install certbot <your-dns-plugin>
ln -sf /opt/certbot/bin/certbot /usr/local/bin/certbot
certbot plugins
```

The last command lists the plugins that certbot can see. Confirm yours appears, then read its own options with `certbot --help <plugin name>`. The option names differ between plugins, so take them from that output rather than from a guide.

Write the credentials to a file that only root can read:

```bash
install -o root -g root -m 600 /dev/null /etc/letsencrypt/dns.ini
```

Then request the certificate. Add `--dry-run` the first time. Let's Encrypt limits how many identical certificates it will issue in a week, and a dry run does not count against that limit.

### Reload nginx after every renewal

certbot renews in the background, and nginx keeps the old certificate in memory until it is told to read the new one.

```bash
mkdir -p /etc/letsencrypt/renewal-hooks/deploy
cat > /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'EOF'
#!/bin/sh
systemctl reload nginx
EOF
chmod +x /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh
```

### Prove that renewal works

Do not wait 60 days to find out.

```bash
certbot renew --dry-run
systemctl list-timers | grep certbot
```

The first performs a real renewal against the staging service and changes nothing. The second shows the timer that runs it twice a day.

## 8. Install the nginx site

```bash
install -o root -g root -m 644 /opt/ytdlp-web/deploy/nginx.conf /etc/nginx/sites-available/ytdlp-web
ln -sf /etc/nginx/sites-available/ytdlp-web /etc/nginx/sites-enabled/ytdlp-web
rm -f /etc/nginx/sites-enabled/default
```

Open `/etc/nginx/sites-available/ytdlp-web` and change these lines.

| Line | Change it to |
| --- | --- |
| `server_name example.com www.example.com;` (in both server blocks) | your own domain names |
| `ssl_certificate` | the path of your certificate chain file |
| `ssl_certificate_key` | the path of your private key file |

Test and reload:

```bash
nginx -t
systemctl reload nginx
```

Fix every error that `nginx -t` reports before you reload.

## 9. Open the firewall

Allow SSH, HTTP and HTTPS. Block everything else. Port 8000 must stay closed.

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
ufw status verbose
```

Check from another machine that port 8000 is closed:

```bash
curl --max-time 5 http://example.com:8000/
```

The command must fail or time out.

## 10. Verify

Do these checks in order.

| Check | Command or action | Expected result |
| --- | --- | --- |
| Service runs | `systemctl status ytdlp-web` | `active (running)` |
| Local answer | `curl -i http://127.0.0.1:8000/` | `200` |
| Redirect | `curl -I http://example.com/` | `301` to the `https://` address |
| TLS chain | `openssl s_client -connect example.com:443 -servername example.com < /dev/null` | `Verify return code: 0 (ok)` |
| Login page | open `https://example.com/login` in a browser | the page opens, and the password works |
| Progress bar | start a download | the bar moves during the download |
| File download | let a job finish | the file arrives, and the transfer starts at once |
| Logs | `journalctl -u ytdlp-web -f` | no repeated restart |

## 11. Cookies for the video site

Skip this section until a download fails with this line:

```
Sign in to confirm you're not a bot
```

The site wants a signed in visitor. It asks a server address more often than it asks a home connection, because many people share one server address.

Export the cookies of a browser that is signed in, following `docs/cookies.md`, and copy the file to the server. The file holds a live session of that account, so root owns it and only the service reads it:

```bash
install -o root -g ytdlp -m 640 cookies.txt /etc/yt-dlp-web/cookies.txt
```

Add this line to `/etc/yt-dlp-web/ytdlp-web.env`:

```
YTDLP_WEB_COOKIES=/etc/yt-dlp-web/cookies.txt
```

Restart the service:

```bash
systemctl restart ytdlp-web
```

The unit needs no change. The application copies the file for each download and never writes the one you placed, so the read-only `/etc` of the hardened unit is fine. The service refuses to start when the variable names a file that is absent or unreadable, and the log says which.

A session does not last forever. When the message returns, export the file again and replace it.

### Before you export anything

Two cheaper things change the same answer.

yt-dlp answers the signature challenge of YouTube in JavaScript, and it looks for deno alone. Without a runtime YouTube gives fewer formats and asks for a sign in more often. The service writes a warning at startup when it finds none:

```bash
journalctl -u ytdlp-web -n 50 | grep -i javascript
```

Install a runtime and name it, if the warning is there:

```bash
apt install -y nodejs
```

```
YTDLP_WEB_JS_RUNTIMES=node
```

The other is the client that yt-dlp asks for. YouTube applies the check differently to a television and to a browser:

```
YTDLP_WEB_PLAYER_CLIENT=tv,web_safari
```

Which client answers changes from month to month, so a cookie file remains the steady answer. `docs/cookies.md` describes both in full.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| The progress bar does not move | the `location /ws/` block is missing, or the `map` block is missing | add the WebSocket block, run `nginx -t`, then reload nginx |
| A long pause before a download starts | `proxy_buffering` is on, so nginx stores the whole file first | set `proxy_buffering off;` in the `location /api/` block |
| The browser shows 502 Bad Gateway | the service is not running | run `systemctl status ytdlp-web` and `journalctl -u ytdlp-web -n 50` |
| A phone shows a certificate warning, a desktop does not | the intermediate certificates are missing from the chain file | put the leaf first and the intermediates under it in `fullchain.pem`, then reload nginx |
| The login always fails | `YTDLP_WEB_PASSWORD` is not set, or the service still runs with the old value | check `/etc/yt-dlp-web/ytdlp-web.env`, then run `systemctl restart ytdlp-web` |
| A job fails with a write error | the `ytdlp` user cannot write in the work directory | run `chown -R ytdlp:ytdlp /var/lib/ytdlp-web` |
| A login attempt returns 429 | the nginx rate limit stopped it (5 per minute per address) | wait one minute, or raise the rate in the `limit_req_zone` line |
| A download fails with "Sign in to confirm you're not a bot" | the site wants a signed in visitor, and it asks a server address more often than a home one | give the service a cookie file, as section 11 describes |
| The service does not start, and the log names `YTDLP_WEB_COOKIES` | the cookie file is absent, or the `ytdlp` user cannot read it | check the path and run `chown root:ytdlp` and `chmod 640` on the file |
| The log warns about a JavaScript runtime | deno is not installed, so YouTube gives fewer formats | run `apt install -y nodejs` and set `YTDLP_WEB_JS_RUNTIMES=node` |

## Keeping it working

Video sites change often. yt-dlp needs regular updates, because an old version stops working with a changed site. Update it once a month, and also when a download fails with an extractor error.

```bash
/opt/ytdlp-web/.venv/bin/pip install --upgrade yt-dlp
systemctl restart ytdlp-web
```

Restart the service after every update. The old version stays in memory until the restart.

Compare what is installed against what is released, when a site fails:

```bash
/opt/ytdlp-web/.venv/bin/yt-dlp --version
curl -s https://pypi.org/pypi/yt-dlp/json | python3 -c "import json,sys; print(json.load(sys.stdin)['info']['version'])"
```

Update the system packages as well, because ffmpeg comes from the distribution.

```bash
apt update && apt upgrade -y
```

## Warning: do not install curl_cffi

Do not install the `curl_cffi` package. Do not install any other package that gives yt-dlp a C-level HTTP backend.

The application has an outbound address guard. The guard works inside Python: it wraps the Python socket layer and checks every address before a connection opens. A C-level HTTP backend opens its sockets inside the C library. Those sockets never pass through the Python socket layer, so the guard never sees them. The guard is then off for all traffic that uses that backend. It fails silently, because nothing in the log says that a check was skipped.

Check after every dependency change:

```bash
/opt/ytdlp-web/.venv/bin/pip list | grep curl
```

The command must print nothing. If it prints a package, remove that package and restart the service.

```bash
/opt/ytdlp-web/.venv/bin/pip uninstall -y curl_cffi
systemctl restart ytdlp-web
```

## Disk sizing

Peak disk use is about 3 times the size of the final file, for each running job. Four files exist for a short time: the video stream, the audio stream, the merged output, and the faststart rewrite.

| Final file size | Free disk space for one job |
| --- | --- |
| 500 MB | about 1.5 GB |
| 1 GB | about 3 GB |
| 2 GB (the configured maximum) | about 6 GB |

`YTDLP_WEB_MAX_JOBS=1` keeps one job at a time, so the peak stays at one job. Add more free space if you raise that value.

`YTDLP_WEB_TTL=600` deletes a finished file after 10 minutes. Add one file size to your free space, because a finished file and a running job can exist together.

## Placeholders in this guide

| Placeholder | Replace it with |
| --- | --- |
| `example.com`, `www.example.com` | your own domain names |
| `<YOUR-REPOSITORY-URL>` | the source of the application code |
| `/etc/ssl/ytdlp-web/fullchain.pem` | the path of your certificate chain file |
| `/etc/ssl/ytdlp-web/privkey.pem` | the path of your private key file |
