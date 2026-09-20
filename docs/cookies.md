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
cookies to a file, and give the file to the server. The server then sends
those cookies with every request, and the site treats it as your signed in
browser.

There are two ways to hand the file over. The page is the short one, and the
one to use again when the session ends. The environment file is for a server
that must come up with cookies already in place.

## The short way: the Settings button

1. Export the cookies, following section 1 below.
2. Open the page and press **Settings**.
3. Press **Choose file** and pick the file, or paste its text into the box.
4. Press **Save**.

The box covers what you put in it, the way a password field does, so nobody
reads it over your shoulder. Save empties it, and so does closing the
dialog.

The panel then says how many cookies it holds, which sites they are for, and
when the first one expires. The next download uses them. Nothing restarts.

Press **Choose file** rather than pasting when you can. A paste through some
fields turns the tabs into spaces, and the format needs the tabs. The server
says so when it happens, but the file button never has the problem.

After that the page never shows the cookies again. It shows the count, the
sites, and the dates, and no route sends the content back. **Remove**
deletes the saved file.

Who can save them is who can open the page. In public mode that is the
password, like the rest of the page. In local mode there is no password, so
anything on your own machine can replace the cookies, which is the reach
that local mode gives to everything else as well. The file itself is written
so that only the user running the server can read it.

## 1. Export the cookies

Do this in a private window. A private window keeps its own session, so the
site does not rotate the cookies under your normal one and the export stays
valid.

1. Open a private window.
2. Sign in to the site.
3. Open the video page once, so the session is complete.
4. Export the cookies with a browser add-on that writes the Netscape format,
   for example *Get cookies.txt LOCALLY*. An add-on that writes several
   formats, such as *Cookie-Editor*, has to be set to Netscape: its own
   default is JSON, which no cookie file reader takes. Save the file as
   `cookies.txt`.
5. Close the private window. **Do not press sign out.** Signing out ends the
   session, and the file you exported dies with it.

The file starts with this line:

```
# Netscape HTTP Cookie File
```

## 2. Put the file on the server, the long way

Skip this section if you used the Settings button. This route is for a
server that must come up with cookies already working, before anybody opens
the page.

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

A file saved in the Settings panel wins over this one, because it is the
newer of the two. **Remove** in the panel deletes the saved file, and the
server falls back to this one.

The panel writes its file beside the work folders. `YTDLP_WEB_COOKIE_STORE`
moves it somewhere else. Wherever it sits, the service user must be able to
write the folder, and the panel says so when it cannot.

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

## Without a cookie file

Three things change the answer, and none of them always works.

**Where the server runs.** The check follows the address. Many people share
one server address, and the site counts that traffic together, so a rented
server meets the check far more often than a home connection does. The same
URL that fails on a server often works on your own machine, and on your own
machine `YTDLP_WEB_COOKIES_FROM_BROWSER` needs no export at all.

**A JavaScript runtime.** yt-dlp answers the signature challenge of YouTube
in JavaScript. It enables deno by itself and finds it on PATH. With no
runtime it falls back to the single client that needs none, which gives
fewer formats and meets the check more often. Install deno, or name the
runtime you already have:

```
YTDLP_WEB_JS_RUNTIMES=node
```

On a Debian server `apt install -y nodejs` is the short route. The server
writes a warning at startup when it finds no runtime, so the log tells you
whether this applies to you. The list replaces the default, so naming `node`
turns deno off.

**Another client.** YouTube serves the same video to a phone, a television,
and a browser, and it applies the check to each of them differently.

```
YTDLP_WEB_PLAYER_CLIENT=tv,web_safari
```

The clients are asked in that order. yt-dlp knows `web`, `web_safari`,
`web_embedded`, `web_music`, `web_creator`, `android`, `android_vr`, `ios`,
`visionos`, `mweb`, `tv`, `tv_downgraded`, and `tv_simply`. The server
refuses to start on a name it does not know, so a typo cannot pass in
silence. Which client answers changes from month to month. Treat this as
something to try, and the cookie file as the answer that lasts.

There is a fourth route, outside this application. YouTube accepts a proof
of work token in place of a sign in, and a yt-dlp plugin can mint one. The
yt-dlp wiki page *PO Token Guide* describes it. It is another moving part to
keep working, so try the three above first.

## What the application does with the file

Each call into yt-dlp gets its own copy of the file, and the copy is deleted
when the call ends. yt-dlp writes the cookie jar back when it closes, so
without the copy two downloads at once would write over each other, and the
file you placed would change under you. The copy also lets the file live on a
read-only path, which is where the systemd unit puts it.

## When it stops working

A session does not last forever. The site can end it, and then the robot
message returns and the page says the cookies were refused. Export the file
again from step 1 and save it again in the Settings panel. That is the whole
repair, and it is why the panel exists.

A file exported from an account you care about is a file worth protecting. A
second account, used for nothing else, keeps the risk small.
