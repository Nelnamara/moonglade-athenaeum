# FAQ

**Is this official / affiliated with PixAI?**
No. It's an unofficial personal-use tool that uses your own API key plus PixAI's
private frontend queries. PixAI's terms grant you copyright of your own generations.

**Will this get my account banned / does it steal credits?**
It's built to do the opposite of abuse: it only reads/manages *your own* account,
defaults to the **cheaper** generation priority, has no credit-farming or purchase
automation, and is rate-paced to be polite. Generation spends your own credits and
always asks before doing so.

**Do I really only need an API key?**
Yes. `USER_ID` auto-resolves from the key and the persisted-query hashes ship as
defaults. See [Setup](Setup) and [How It Works](How-It-Works).

**Why are there "hashes" if I don't need to set them?**
They're public identifiers of PixAI's own frontend queries (not secrets), baked in so
you don't capture anything. You only touch one if PixAI overhauls their frontend —
[Troubleshooting](Troubleshooting) covers recapture.

**Where do my files and credentials go?**
Everything is local. `config.json`, `token.txt`, and `pixai_backup/` are git-ignored.
Nothing phones home.

**Can I run it on my phone/tablet?**
Yes — launch the gallery with `--host 0.0.0.0 --https` and open it on your device
(installable as a PWA). [Select mode](Collections) is touch-friendly. Note: a
LAN-exposed gallery can make API calls, so only do this on a trusted network.

**Does organizing files break the gallery?**
No. Lookups are by `media_id`, so files can live in any subfolder.
[Collections](Collections) are catalog-based and survive Organize too.

**How do I update?**
`git pull`. If using the GUI, **fully quit and reopen it** (Stop/Launch doesn't
reload the code) — see [Troubleshooting](Troubleshooting).

**Something broke after a PixAI change.**
See [Troubleshooting](Troubleshooting) — usually a one-line hash recapture.
