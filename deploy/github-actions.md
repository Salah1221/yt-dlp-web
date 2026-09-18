# Deploy from GitHub Actions

Two workflows live in `.github/workflows`.

| Workflow | When it runs | What it does |
|---|---|---|
| `tests.yml` | every push to `main`, every pull request, or by hand | installs ffmpeg, installs the dependencies, refuses a C level HTTP backend, runs pytest |
| `deploy.yml` | after `tests` passes on `main`, or by hand | sends the code to the server with rsync, installs the dependencies, restarts the service, checks that the site answers |

The deploy runs only when the tests pass. A red test run stops it.

## The code travels from the runner, not from GitHub

The runner already holds the code, because it checked it out to run the tests. It sends those files straight to the server with rsync over the same SSH connection.

The server therefore needs no GitHub credential and no outbound access to GitHub. The only key on the server is the one that GitHub Actions uses to log in.

The deploy checks out the exact commit that the tests ran against, not the head of the branch. The head can move while the tests run, and deploying the head would ship code that nothing tested.

## What the deploy does, step by step

1. Checks out the tested commit.
2. Writes the SSH key and the pinned host key.
3. Opens one test connection, so a login fault fails with a clear message.
4. `rsync --archive --delete`, excluding `.git`, `.venv`, `__pycache__`, `.pytest_cache`, and `work`.
5. Makes the virtual environment if it is absent, then installs the requirements.
6. Refuses to continue if `curl_cffi` is present, because it bypasses the outbound address guard.
7. Restarts the service, then polls `systemctl is-active` for up to 30 seconds.
8. Requests `/login` on your domain until it answers 200, up to 10 times.
9. Deletes the key from the runner.

**Warning:** step 4 uses `--delete`. Any file you add inside the deploy path by hand is removed on the next deploy. The excluded folders are safe, and so is everything outside that path, such as `/etc/yt-dlp-web/ytdlp-web.env`, the certificate, and the nginx site file.

## Set up the server

Run these on the VPS, as a user with sudo.

### 1. Packages

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg nginx rsync
```

### 2. Users and folders

The service user has no shell, so it cannot receive an SSH connection. The deploy user is separate and exists only for GitHub Actions.

```bash
sudo adduser --system --group --no-create-home --disabled-login ytdlp
sudo adduser --disabled-password --gecos "" deploy

sudo mkdir -p /opt/ytdlp-web /var/lib/ytdlp-web/work
sudo chown -R deploy:deploy /opt/ytdlp-web
sudo chown -R ytdlp:ytdlp /var/lib/ytdlp-web
sudo chmod 755 /opt/ytdlp-web
```

### 3. Let the deploy user restart one service and nothing else

Find the real path first, because it differs between distributions.

```bash
command -v systemctl
```

Then write the rule. Change the path if the command above printed a different one.

```bash
sudo tee /etc/sudoers.d/ytdlp-deploy >/dev/null <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart ytdlp-web, /usr/bin/systemctl is-active ytdlp-web
EOF
sudo chmod 440 /etc/sudoers.d/ytdlp-deploy
sudo visudo -c
```

This user can restart that one service. It cannot become root, and it cannot touch any other service.

### 4. The key that GitHub Actions uses

Make this key on your own machine. The private half goes into GitHub. The public half goes onto the server.

```bash
ssh-keygen -t ed25519 -f ytdlp-deploy-key -C "github actions deploy" -N ""
```

Put the public half on the server, then fix the permissions. OpenSSH refuses a key file that other users can read.

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < ytdlp-deploy-key.pub
sudo -u deploy chmod 700 /home/deploy/.ssh
sudo -u deploy chmod 600 /home/deploy/.ssh/authorized_keys
```

### 5. Read the server host key

Run this on your own machine. It gives the line that pins your server.

```bash
ssh-keyscan -t ed25519 your.server.address
```

On Windows, use the OpenSSH client that Git installs. The Microsoft client offers a key exchange that it cannot perform, and the scan then returns nothing:

```bash
"/c/Program Files/Git/usr/bin/ssh-keyscan.exe" -t ed25519 your.server.address
```

### 6. The service, the settings, and nginx

Copy three files from your own checkout, because the server has no copy yet:

```bash
scp deploy/ytdlp-web.service deploy/nginx.conf deploy/ytdlp-web.env.example \
    you@your.server.address:/tmp/
```

Then, on the server, follow `deploy/README.md` for the settings file, the certificate, the systemd unit, nginx, and the firewall.

Enable the unit, but do **not** start it yet:

```bash
sudo systemctl enable ytdlp-web
```

The code is not there until the first deploy. The deploy restarts the unit, and a restart starts a unit that is not running.

## Set up GitHub

Open the repository, then Settings.

### Environments

Make an environment named `production`. Add yourself as a required reviewer if you want to approve every deploy by hand.

### Secrets

Settings, Secrets and variables, Actions, Secrets.

| Secret | Value |
|---|---|
| `DEPLOY_HOST` | the server address |
| `DEPLOY_USER` | `deploy` |
| `DEPLOY_SSH_KEY` | the whole contents of `ytdlp-deploy-key`, the private half, including the first and last lines |
| `DEPLOY_KNOWN_HOSTS` | the line that `ssh-keyscan` printed |

### Variables

Each one has a default, so add a variable only to change it.

| Variable | Default | Meaning |
|---|---|---|
| `DEPLOY_PORT` | `22` | the SSH port |
| `DEPLOY_PATH` | `/opt/ytdlp-web` | where the code lives |
| `SERVICE_NAME` | `ytdlp-web` | the systemd unit name |
| `PUBLIC_URL` | empty | for example `https://example.com`. When it is empty the final check is skipped |

## First run

Run `deploy` by hand from the Actions tab, or:

```bash
gh workflow run deploy
gh run watch
```

The first run makes the virtual environment, so it takes longer than the ones after it.

## When it fails

| Message | Cause |
|---|---|
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` is wrong, or the host in it does not match `DEPLOY_HOST` as text |
| `Permission denied (publickey)` | the public half is not in `/home/deploy/.ssh/authorized_keys`, or the permissions are wrong |
| `sudo: a password is required` | the sudoers file is missing, or the path to `systemctl` does not match |
| `did not come back within 30s` | the service failed to start. Read `journalctl -u ytdlp-web -n 50` |
| The final check reports `502` | the service is down, or nginx points at the wrong port |
| The final check reports `000` | the domain did not answer at all. Check DNS and the firewall |

## The application password

`YTDLP_WEB_PASSWORD` lives in `/etc/yt-dlp-web/ytdlp-web.env` on the server, mode 600, owned by root. It is never in the repository and never in a GitHub secret. A deploy does not change it.
