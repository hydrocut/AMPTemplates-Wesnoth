#!/bin/bash
# lancer-wesnothd.sh - pose par le template AMP TeamKit (recree a chaque Update).
# Argument : <port>
#
# 1. corrige dans wesnothd.cfg (ecrit par AMP) ce qui empecherait les joueurs
#    d'entrer, et y place le chemin de la fifo de commandes ;
# 2. lance wesnothd ;
# 3. relaie la console d'AMP vers la fifo (wesnothd ne lit pas son entree) ;
# 4. ecrit une ligne « pret » quand le port ecoute vraiment (wesnothd n'en
#    ecrit aucune) ;
# 5. a l'arret demande par AMP (SIGTERM), envoie « shut_down now » a wesnothd.
cd "$(dirname "$0")" || exit 1
PORT="${1:-15000}"
BIN=/usr/games/wesnothd-1.18
CFG=wesnothd.cfg
# Hors du dossier de l'instance : une sauvegarde AMP qui lirait la fifo resterait bloquee.
FIFO="${XDG_RUNTIME_DIR:-/tmp}/wesnothd-$PORT.fifo"
export LANG=C.UTF-8 LC_ALL=C.UTF-8

if [ ! -x "$BIN" ]; then
  echo "ERREUR : $BIN absent. Cette instance doit tourner en conteneur : le paquet wesnoth-1.18-server est installe par ExtraContainerPackages."
  exit 1
fi
if [ ! -f "$CFG" ]; then
  echo "ERREUR : $CFG absent. AMP l'ecrit au demarrage a partir de AMP_wesnothd.cfg : lance Update."
  exit 1
fi
if [ ! -f perso.cfg ]; then
  printf '%s\n' \
    "# perso.cfg - reglages wesnothd en plus, au format WML, un par ligne." \
    "# Exemple : save_replays=yes puis, a la ligne, replay_save_path=\"replays\"" \
    "# Lu a chaque demarrage, a la fin de wesnothd.cfg. Le template ne l'ecrase jamais." \
    "# Attention : une erreur ici peut empecher le serveur de demarrer (voir la console)." > perso.cfg
fi

# Message d'accueil : wesnothd le renvoie a chaque joueur sans echapper les
# guillemets droits, et la connexion echoue (essai du 10/10/2026). Un >> fermerait
# la chaine brute <<...>> trop tot. On remplace donc " par ' et >> par > >.
awk -v fifo="$FIFO" -v q="'" '
  /^motd=<<.*>>$/ {
    v = substr($0, 8, length($0) - 9)
    avant = v
    gsub(/"/, q, v)
    while (index(v, ">>")) sub(/>>/, "> >", v)
    if (v ~ />$/) v = v " "
    if (v != avant) change = 1
    $0 = "motd=<<" v ">>"
  }
  /^fifo_path=/ { $0 = "fifo_path=\"" fifo "\"" }
  { print }
  END {
    if (change) print "TeamKit : guillemets droits ou >> remplaces dans le message d accueil (ils empechent les joueurs de se connecter)." > "/dev/stderr"
  }
' "$CFG" > "$CFG.tmp" && mv -f "$CFG.tmp" "$CFG"

rm -f "$FIFO"
# --pdeathsig : si ce script est tue net (SIGKILL), wesnothd recoit SIGTERM au
# lieu de rester orphelin sur le port.
# Chemin ABSOLU de la config : sinon {./perso.cfg} est introuvable (essai du 10/10).
setpriv --pdeathsig TERM -- "$BIN" -c "$PWD/$CFG" -p "$PORT" &
PID=$!

ARRET=0
arreter() {
  trap - TERM INT
  ARRET=1
  echo "TeamKit : arret demande, fermeture de wesnothd."
  if kill -0 "$PID" 2>/dev/null && [ -p "$FIFO" ]; then
    timeout 2 bash -c 'printf "shut_down now\n" > "$1"' _ "$FIFO"
  fi
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    kill -0 "$PID" 2>/dev/null || return
    sleep 0.5
  done
  kill -TERM "$PID" 2>/dev/null
}
trap arreter TERM INT

# Ligne « pret » pour AMP, des que le port est en ecoute (LISTEN = 0A).
(
  motif=$(printf ':%04X$' "$PORT")
  for _ in $(seq 1 150); do
    kill -0 "$PID" 2>/dev/null || exit 0
    for t in /proc/net/tcp /proc/net/tcp6; do
      if [ -r "$t" ] && awk -v p="$motif" '$2 ~ p && $4 == "0A" { t = 1 } END { exit !t }' "$t"; then
        echo "TeamKit : wesnothd pret, il ecoute sur le port $PORT."
        exit 0
      fi
    done
    sleep 0.2
  done
  echo "TeamKit : ATTENTION, le port $PORT n'ecoute toujours pas apres 30 secondes."
) &

# Console d'AMP -> fifo de wesnothd (une commande par ligne : help, msg, kick...).
exec 3<&0
(
  while IFS= read -r ligne <&3; do
    ligne="${ligne%$'\r'}"
    [ -n "$ligne" ] || continue
    if kill -0 "$PID" 2>/dev/null && [ -p "$FIFO" ]; then
      timeout 2 bash -c 'printf "%s\n" "$1" > "$2"' _ "$ligne" "$FIFO" \
        || echo "TeamKit : commande non transmise a wesnothd."
    fi
  done
) &
RELAIS=$!
exec 3<&-

# Le SIGTERM d'AMP interrompt ce « wait » (code 143) : on attend une seconde
# fois pour rendre le vrai code de sortie de wesnothd (0 apres shut_down now).
wait "$PID"
CODE=$?
if [ "$ARRET" = 1 ]; then
  wait "$PID"
  CODE=$?
fi
kill "$RELAIS" 2>/dev/null
rm -f "$FIFO"
if [ "$CODE" = 134 ]; then
  # abort() : en pratique une erreur du preprocesseur WML (accolade, fichier inclus absent).
  echo "TeamKit : wesnothd s'est arrete sur une erreur de configuration. Relis perso.cfg (accolades, guillemets) ; wesnothd.cfg est reecrit par AMP a chaque demarrage."
fi
exit "$CODE"
