# Give the server cookies

A video site can answer a download with this line:

```
ERROR: [youtube] NX45ctOJnpg: Sign in to confirm you're not a bot.
```

The site asks the visitor to sign in. It asks a server more often than it
asks a home connection, because many people share one server address and the
site treats that traffic as a robot. Nothing in the URL and nothing in the
application causes it.

The answer is a cookie file. You sign in once in your own browser, export the
cookies to a file, and name that file in the environment. The server then
sends those cookies with every request, and the site treats it as your signed
in browser.

## 1. Export the cookies

Do this in a private window. A private window keeps its own session, so the
site does not rotate the cookies under your normal one and the export stays
valid.

1. Open a private window.
2. Sign in to the site.
3. Open the video page once, so the session is complete.
4. Export the cookies with a browser add-on that writes the Netscape format,
   for example *Get cookies.txt LOCALLY*. Save the file as `cookies.txt`.
5. Close the private window. **Do not press sign out.** Signing out ends the
   session, and the file you exported dies with it.

The file starts with this line:

```
# Netscape HTTP Cookie File
```

## 2. Put the file on the server

The file holds a live session of your account. Treat it like the password.

```bash
install -o root -g ytdlp -m 640 cookies.txt /etc/yt-dlp-web/cookies.txt
```

Root owns it, the service user reads it, and nobody else can open it.

## 3. Name the file in the environment

Add this line to `/etc/yt-dlp-web/ytdlp-web.env`:

```
YTDLP_WEB_COOKIES=/etc/yt-dlp-web/cookies.txt
```

Restart the service:

```bash
systemctl restart ytdlp-web
```

The application refuses to start when the variable names a file that is
absent or that the service user cannot read. It prints the reason.

## On your own machine

On a desktop the browser is on the same machine as the server, so you can
skip the export and read the browser profile directly:

```
YTDLP_WEB_COOKIES_FROM_BROWSER=firefox
```

The value is written the way the yt-dlp command line writes it:
`BROWSER[+KEYRING][:PROFILE][::CONTAINER]`, for example `chrome:Default`.
Close the browser first. Chrome and Edge lock their cookie database while
they run, and a locked database gives an error in place of a download.

This route needs a browser profile on the machine that runs the server, so it
does not work on a server.

## What the application does with the file

Each call into yt-dlp gets its own copy of the file, and the copy is deleted
when the call ends. yt-dlp writes the cookie jar back when it closes, so
without the copy two downloads at once would write over each other, and the
file you placed would change under you. The copy also lets the file live on a
read-only path, which is where the systemd unit puts it.

## When it stops working

A session does not last forever. The site can end it, and then the robot
message returns and the page says the cookies were refused. Export the file
again from step 1 and replace it on the server.

A file exported from an account you care about is a file worth protecting. A
second account, used for nothing else, keeps the risk small.
