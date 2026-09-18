# Deploy from GitHub Actions

Two workflows live in `.github/workflows`.

| Workflow | When it runs | What it does |
|---|---|---|
| `tests.yml` | every push to `main`, every pull request, or by hand | installs ffmpeg, installs the dependencies, refuses a C level HTTP backend, runs pytest |
| `deploy.yml` | after `tests` passes on `main`, or by hand | connects to the server, updates the code, installs the dependencies, restarts the service, checks that the site answers |

The deploy runs only when the tests pass. A red test run stops it.

## What the deploy does on the server

1. `git fetch` and `git reset --hard origin/main`. The server holds no local edits.
2. `pip install --upgrade -r requirements.txt` inside the virtual environment.
3. Refuses to continue if `curl_cffi` is installed, because it bypasses the outbound address guard.
4. `systemctl restart`, then `systemctl is-active` to prove the service came back.
5. From the runner, `GET /login` on your domain must answer 200.

**Warning:** step 1 deletes any change you made on the server by hand. Make every change in the repository.

## Set up the server

Run these on the VPS, as a user with sudo.

### 1. Make the deploy user

The service user `ytdlp` has no shell, so it cannot receive an SSH connection. The deploy needs its own user.

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo mkdir -p /opt/ytdlp-web
sudo chown -R deploy:deploy /opt/ytdlp-web
sudo chmod 755 /opt/ytdlp-web
```

### 2. Let the deploy user restart one service and nothing else

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

### 3. Clone the code and make the virtual environment

```bash
sudo -u deploy -H bash
cd /opt/ytdlp-web
git clone <YOUR-REPOSITORY-URL> .
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
exit
```

If the repository is private, the server needs its own read key. Make one as the `deploy` user with `ssh-keygen -t ed25519 -C "ytdlp-web server"`, then add the public key to the repository under Settings, Deploy keys, with write access off.

### 4. Make the key that GitHub Actions uses

Make this key on your own machine, not on the server. The private half goes into GitHub. The public half goes onto the server.

```bash
ssh-keygen -t ed25519 -f ytdlp-deploy-key -C "github actions deploy" -N ""
```

Put the public half on the server:

```bash
sudo -u deploy mkdir -p /home/deploy/.ssh
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < ytdlp-deploy-key.pub
sudo -u deploy chmod 700 /home/deploy/.ssh
sudo -u deploy chmod 600 /home/deploy/.ssh/authorized_keys
```

### 5. Read the server host key

Run this on your own machine. It gives the line that pins your server, so the runner cannot be sent to a different machine.

```bash
ssh-keyscan -p 22 -t ed25519 your.server.address
```

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

Settings, Secrets and variables, Actions, Variables. Each one has a default, so add a variable only to change it.

| Variable | Default | Meaning |
|---|---|---|
| `DEPLOY_PORT` | `22` | the SSH port |
| `DEPLOY_PATH` | `/opt/ytdlp-web` | where the code lives |
| `SERVICE_NAME` | `ytdlp-web` | the systemd unit name |
| `PUBLIC_URL` | empty | for example `https://example.com`. When it is empty the final check is skipped |

## First run

1. Push to `main`, or open Actions and run `tests` by hand.
2. When `tests` is green, `deploy` starts.
3. Open the run and read the last lines. It prints the commit that is now running.

## When it fails

| Symptom | Cause |
|---|---|
| `Host key verification failed` | `DEPLOY_KNOWN_HOSTS` is wrong, or the server key changed |
| `Permission denied (publickey)` | the public half is not in `/home/deploy/.ssh/authorized_keys`, or the file permissions are wrong |
| `sudo: a password is required` | the sudoers file is missing, or the path to `systemctl` does not match |
| `is-active` fails | the service did not start. Read `journalctl -u ytdlp-web -n 50` on the server |
| The final check returns 502 | the service is down, or nginx points at the wrong port |
| The final check returns 303 | this is the login page redirect. Check that `PUBLIC_URL` has no path after the domain |

## The application password

`YTDLP_WEB_PASSWORD` lives in `/etc/ytdlp-web.env` on the server, mode 600, owned by root. It is never in the repository and never in a GitHub secret for this workflow. A deploy does not change it.
