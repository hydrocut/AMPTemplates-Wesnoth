# AMPTemplates-Wesnoth — Battle for Wesnoth multiplayer server for AMP

**AMP Generic Module** template for **wesnothd**, the official multiplayer server of
**Battle for Wesnoth** (<https://www.wesnoth.org/>, source <https://github.com/wesnoth/wesnoth>).
Written for TeamKit, a free French game host, on 10 Oct 2026. CubeCoders ships no Wesnoth template.

> Résumé en français à la fin du fichier.

## Which version, and why

| Source | Version | Verdict |
|---|---|---|
| Latest stable (tag `1.18.8`, 18 Aug 2026; Steam app 599390 is on the stable branch) | 1.18.8 | what players run |
| Development branch (tags up to `1.19.28`, 21 Sep 2026) | 1.19.x | not a release; **there is no 1.20 yet** (no tag, no branch) |
| Debian 13 `wesnoth-1.18-server` (in `cubecoders/ampbase:debian`) | **1.18.5** | **used** |
| Debian `trixie-backports` | 1.18.8 | not reachable: the image's apt sources have no backports |

Why 1.18.5 is fine for 1.18.8 players:

- wesnothd only checks the client version against `versions_accepted` (wildcards `*`, `?`, `+`,
  `utils::wildcard_string_match`); its built-in default (1.18.5 and 1.18.8) is `1.18.*` and `test`.
  Tested with `1.18.*`: clients announcing 1.18.0 and 1.18.8 log in, 1.16.12 gets
  `[reject] accepted_versions="1.18.*"`.
- The protocol does not change inside a stable series; the server relays game data and does not
  run the game or its Lua.
- Server-side changes between 1.18.5 and 1.18.8 (`git log 1.18.5..1.18.8 -- src/server`): four
  commits. Two only touch the forum database code (`dbconn.cpp`, unused here), one replaces a
  deprecated Boost call, and one — *servers: avoid hard failure to start if IPv6 is disabled* —
  matters only on a kernel booted without IPv6. AMP containers on the TeamKit host have `::1`
  and wesnothd binds fine (tested). On a host with `ipv6.disable=1`, 1.18.5 would refuse to start.
- Compiling 1.18.8 would mean a ~500 MB source tarball and a Boost toolchain in every container
  for no functional gain.

`apt-get install wesnoth-1.18-server` is done by the AMP image itself (`/ampstart.sh`, from
`Meta.ExtraContainerPackages`), so the template **requires** container mode. It adds ~19 MB
(binary + Boost 1.83 libraries). The binary is `/usr/games/wesnothd-1.18`.

## Files

| File | Role |
|---|---|
| `wesnoth.kvp`, `wesnoth*.json`, `manifest.json` | the AMP template |
| `scripts/AMP_wesnothd.cfg` | settings model; AMP renders it to `wesnothd.cfg` (`ConfigType: template`) |
| `scripts/lancer-wesnothd.sh` | start script (see below) |
| `verifier.py` | pre-push checks, must print `Tout est bon.` |

Both `scripts/` files are fetched from this repository (raw.githubusercontent.com, branch `main`)
at each Update, so **the repository must be public**.

## How the server is started

`/bin/bash lancer-wesnothd.sh <port>`, which:

1. fixes in the rendered `wesnothd.cfg` what would lock players out (see *Text values*) and writes
   the FIFO path;
2. runs `wesnothd-1.18 -c <absolute path>/wesnothd.cfg -p <port>` under `setpriv --pdeathsig TERM`
   (if the script is SIGKILLed, wesnothd dies too instead of keeping the port — tested);
3. relays the AMP console to wesnothd's command FIFO: **wesnothd does not read stdin**, admin
   commands go through `fifo_path`;
4. prints `TeamKit : wesnothd pret, il ecoute sur le port <port>.` as soon as the port is in
   LISTEN state (`/proc/net/tcp*`): **wesnothd prints no "ready" line of its own**, and its last
   start-up line is written *before* it binds the port;
5. on SIGTERM (AMP stop) writes `shut_down now` to the FIFO; wesnothd logs
   `Server has been shut down: shut down by admin command` and exits 0. Hard kill after 5 s.

Details that cost a test each:

- **Absolute config path.** With a relative `-c wesnothd.cfg`, `{./perso.cfg}` is "missing".
- **FIFO outside the instance folder**: `$XDG_RUNTIME_DIR` (set by the AMP image) or `/tmp`,
  named after the port. A FIFO inside the instance would be read by AMP backups, which would hang.
- **A WML preprocessor error aborts wesnothd** (`terminate called… preproc_config::error`, exit
  134, core dump) — it does not fall back to defaults. The script prints a French hint then.

## Settings exposed in AMP (French UI)

| AMP setting | wesnothd key | Default |
|---|---|---|
| Port du jeu (Network tab) | `-p` | 15000/TCP (client default when no port is typed) |
| Message d'accueil | `motd` | French TeamKit message with the Discord link |
| Mot de passe administrateur | `passwd` | empty (nobody can become admin in game) |
| Versions du jeu acceptées | `versions_accepted` (comma list, `*` / `?` wildcards) | `1.18.8,1.18.9,1.18.1?` |
| Connexions par adresse IP | `connections_allowed` | 5 (wesnothd default) |

**Why not `1.18.*` by default.** The developers' Steam announcement of 1.18.8 (18 Aug 2026) says it
fixes a security vulnerability present since 1.13.5 and that older versions will be blocked from the
official 1.18 servers. The 1.18.7 → 1.18.8 diff shows Lua API hardening (no function addresses,
`%p` forbidden in `string.format`, `name_generator`, RNG): a **client-side** issue, wesnothd has no
Lua and is not affected. But a player on an older client could be targeted by another player's
game, so the default follows the official servers: 1.18.8, 1.18.9 and 1.18.10–1.18.19 (tested:
1.18.8 and 1.18.12 accepted; 1.18.5, 1.18.0, 1.19.28, 1.16.12 rejected). Set `1.18.*` to let older
1.18 clients in (e.g. Linux distribution packages). No CVE or written advisory was found.

Fixed in the model: `ban_save_file="bans.cfg.gz"` (bans survive restarts — tested), `fifo_path`,
and `{./perso.cfg}` as the last line, a file the script creates once and never overwrites, for any
other wesnothd key (`save_replays`, `disallow_names`, `max_messages`…; list in `load_config()` of
`src/server/wesnothd/server.cpp`).

**wesnothd has no global player or game limit**, so none is exposed. `App.MaxUsers=30` is only the
capacity AMP and the TeamKit site display: 30 players at once is the load tested (17 MB of RAM).
There is no user database either (`[user_handler]` needs MariaDB and the forum tables): nicknames
are first come, first served, and names containing `admin`, `server`, `moderator` are refused by
default (tested: `Admin` → *reserved*).

### Text values: why `<<...>>`

AMP writes values verbatim. The config file goes through the **WML preprocessor**, so:

| In the value | `motd="..."` | `motd=<<...>>` (used) |
|---|---|---|
| accents, `—`, `·`, comma, apostrophe, `;`, `+`, `<`, `>` | ok | ok |
| `{` … `}` | **macro call → wesnothd aborts at start** | ok, kept as is |
| `#` | | ok, kept as is |
| `"` | ends the string | kept, **but every login then fails**: wesnothd sends the motd back without escaping it (`did not find newline after end of attribute`) |
| `>>` | | ends the raw string early |

All tested on wesnothd 1.18.5. So every text is a WML raw string, and the start script replaces,
in the motd only, `"` with `'` and `>>` with `> >`, with a console notice. The admin password and
the version list are not rewritten (that would silently change the password): a `>>` or a final `>`
in them stops the start script with a French error naming the setting. The description also asks to
avoid `"`.

## Console and player list

AMP console → FIFO: `help`, `msg <text>`, `status`, `kick <nick>`, `ban <ip mask> <time> <reason>`,
`bans`, `unban`, `games`, `motd <text>`… (`help`, `msg`, `status`, `ban`, `bans` tested). Players with the admin password
type `/query admin <password>` in the lobby, then `/query help`. A failed attempt is logged
**with the password typed** (wesnothd's choice).

Real lines (tab-separated, wesnothd 1.18.5):

```
20261010 16:38:41 info server: 127.0.0.1	Kevin	has logged on          <- UserJoinRegex
20261010 16:38:45 info server: 127.0.0.1	Kevin	has logged off         <- UserLeaveRegex
TeamKit : wesnothd pret, il ecoute sur le port 15000.                  <- AppReadyRegex (start script)
20261010 16:38:41 error server: 127.0.0.1	TLS requested by client but not enabled on server
```

The last one is **normal**: the 1.18 client always asks for TLS first, then falls back to plain TCP
when the server answers `0xFFFFFFFF` (`wesnothd_connection.cpp`). It would show as an *error* on
every connection, so `Console.ThrowawayMessageRegex` drops it. TLS could be enabled with a real
certificate (`tls_enabled`, `tls_fullchain`, `tls_private_key` in `perso.cfg`), not done here.

## How a player connects

The server is **not listed anywhere** (the official lobby only shows its own games). In Wesnoth:
**Multiplayer → Connect to Server** (French: *Multijoueur → Se connecter au serveur*), type
`IP:port` (just `IP` if the port is 15000), pick a nickname, **Connect**. Then create or join games
in the lobby as usual. Clients must be 1.18.x (1.18.8 or later with the default setting).

## Resources (measured)

| | |
|---|---|
| RAM | 14 MB idle, 17 MB with 30 logged-in clients (+4 MB for the bash wrapper) |
| Start | ~0.3 s to the ready line |
| Disk | ~19 MB of packages, plus `bans.cfg.gz` (and replays if enabled in `perso.cfg`) |
| CPU | negligible: the server relays game data, clients simulate the game |

## Before pushing

```
python verifier.py
```

Must print `Tout est bon.`: JSON, includes, port refs, complete `Console.*` / `Limits.*` block,
every AMP setting present in the model and the reverse, raw-string form, a render → start-script
fix → WML read round trip (empty value, spaces, accents, commas, `{`, `#`, `"`, `>>`), download
URLs, LF endings, package/binary/version series consistency, `bash -n`, console regexes on real lines.

## Install in AMP

ADS → Configuration → Instance Deployment → **Configuration Repositories**: add
`hydrocut/AMPTemplates-Wesnoth:main`, save, **Fetch latest**. Create Instance → **Battle for
Wesnoth (TeamKit)** → **Update** (must print `Battle for Wesnoth server 1.18.5`) → **Start**.

## Moving to 1.20

When Wesnoth 1.20 is out *and* Debian 13 ships a `wesnoth-1.20-server` (otherwise: compile),
change the package in `Meta.ExtraContainerPackages`, `BIN=` in the start script, the binary in the
Update check and the default of `versions_accepted`; `verifier.py` checks they agree. A new container
is needed for the package (AMP installs it when the container is created).

## Credits

Battle for Wesnoth is free software (GPL-2.0+) by the Wesnoth project. This repository only
contains the template; the server comes from Debian's `wesnoth-1.18-server` package.

---

## Résumé en français

Template AMP pour le **serveur multijoueur officiel de Battle for Wesnoth** (`wesnothd`).
La version stable du jeu est la **1.18.8** (Steam) ; **la 1.20 n'est pas sortie**. Le serveur vient
du paquet Debian 13 `wesnoth-1.18-server` (**1.18.5**), installé dans le conteneur par AMP :
le serveur ne regarde que le numéro du client, et accepte toute la série 1.18. Par défaut, le
template n'ouvre qu'aux clients **1.18.8 et suivants** (faille côté joueur corrigée en 1.18.8,
comme sur les serveurs officiels) ; `1.18.*` ouvre à toutes les 1.18. Conteneur obligatoire.
Un seul port, **15000 en TCP**.

- **Se connecter** : le serveur n'apparaît dans **aucune liste**. Dans le jeu : Multijoueur →
  « Se connecter au serveur » → taper `IP:port` (ou juste l'IP si le port est 15000).
- **Réglages en français dans AMP** : message d'accueil (TeamKit + Discord par défaut), mot de
  passe administrateur (`/query admin <mot de passe>` dans le salon), versions acceptées
  (1.18.8 et suivantes), connexions par IP (5). Pas de limite globale de joueurs : wesnothd n'en a pas.
- **Textes** : écrits en chaîne brute `<<...>>`, accents, virgules, apostrophes, `{` et `#` passent.
  Un guillemet droit `"` dans le message d'accueil empêcherait tout le monde d'entrer : le script
  de lancement le remplace par `'`.
- **Console d'AMP branchée** : `help`, `msg`, `status`, `kick`, `ban`… ; joueurs visibles dans AMP ;
  arrêt propre (`shut_down now`) ; bannissements gardés après un redémarrage.
- **Testé en vrai** le 10 oct. 2026 dans un conteneur jetable : 14 Mo de RAM, prêt en 0,3 s.
- Avant de pousser : `python verifier.py` doit répondre « Tout est bon. ».
