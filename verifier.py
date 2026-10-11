# -*- coding: utf-8 -*-
"""
Contrôle du template avant de le pousser (même rôle que ceux de Freeciv, Unciv, Mumble).

    python verifier.py

1. tous les JSON se parsent ;
2. le .kvp ne référence que des fichiers présents, le port principal existe, le bloc
   Console.* / Limits.* est complet, la console d'AMP écrit dans le serveur ;
3. chaque réglage exposé dans AMP arrive dans le modèle scripts/AMP_wesnothd.cfg (rendu
   par AMP en wesnothd.cfg), et chaque {{...}} du modèle a son réglage ;
4. chaque texte est écrit en chaîne brute WML <<...>> : entre guillemets droits, une
   accolade est lue comme une macro et wesnothd plante au démarrage (essai du 10/10/2026) ;
5. aller-retour : on rend le modèle comme AMP (remplacement brut), on applique la même
   correction que lancer-wesnothd.sh, puis on relit la ligne comme le lecteur WML
   (la chaîne brute s'arrête au premier >>). Valeur vide, espaces, accents, virgules,
   apostrophes, accolades, # : la valeur relue doit être identique ;
6. les fichiers téléchargés à l'Update existent dans scripts/, à l'URL du dépôt du manifest ;
7. le lanceur : fins de ligne LF, aucun {{, même binaire que le paquet Debian et l'étape
   de vérification, chemin absolu de la config, fifo hors du dossier de l'instance,
   et `bash -n` s'il y a un bash sous la main ;
8. les regex de console reconnaissent les vraies lignes de wesnothd 1.18.5 (relevées le
   10 oct. 2026 dans un conteneur jetable cubecoders/ampbase:debian) et pas les autres.
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
NOM = 'wesnoth'
MODELE = 'scripts/AMP_wesnothd.cfg'
LANCEUR = 'scripts/lancer-wesnothd.sh'
soucis = []


def lire(nom, binaire=False):
    chemin = os.path.join(ICI, nom)
    if binaire:
        with open(chemin, 'rb') as f:
            return f.read()
    with io.open(chemin, encoding='utf-8') as f:
        return f.read()


def py(motif):
    # AMP est en C# : (?<nom>...) ; Python veut (?P<nom>...)
    return re.compile(motif.replace('(?<', '(?P<'))


# ── 1. JSON ──────────────────────────────────────────────────────────────────
data = {}
for nom in ('manifest.json', NOM + 'config.json', NOM + 'metaconfig.json', NOM + 'ports.json', NOM + 'updates.json'):
    try:
        data[nom] = json.loads(lire(nom))
        print('ok   %-24s JSON valide' % nom)
    except Exception as e:
        soucis.append('%s : JSON invalide (%s)' % (nom, e))
if soucis:
    print('\n'.join('NON  ' + s for s in soucis))
    sys.exit(1)
config = data[NOM + 'config.json']
updates = data[NOM + 'updates.json']
ports = data[NOM + 'ports.json']

# ── 2. kvp ───────────────────────────────────────────────────────────────────
kvp = lire(NOM + '.kvp')
cles = dict(l.split('=', 1) for l in kvp.splitlines() if '=' in l)
for ref in re.findall(r'@IncludeJson\[([^\]]+)\]', kvp):
    if not os.path.isfile(os.path.join(ICI, ref)):
        soucis.append('@IncludeJson[%s] : fichier absent' % ref)
for cle in ('Meta.ConfigManifest', 'Meta.MetaConfigManifest'):
    if not os.path.isfile(os.path.join(ICI, cles.get(cle, '?'))):
        soucis.append('%s pointe sur un fichier absent' % cle)
refs = {p['Ref'] for p in ports}
if cles.get('App.PrimaryApplicationPortRef') not in refs:
    soucis.append('PrimaryApplicationPortRef ne correspond à aucun port')
cmd = cles.get('App.CommandLineArgs', '')
for r in re.findall(r'\{\{\$(\w+)\}\}', cmd):
    if r not in refs and r != 'FullBaseDir':
        soucis.append('{{$%s}} : aucun port ne porte ce Ref' % r)
if '{{$%s}}' % cles.get('App.PrimaryApplicationPortRef') not in cmd:
    soucis.append('le port principal n’est pas passé au lanceur')
print('ok   ports                    %s' % ', '.join('%s %s/%s' % (p['Ref'], p['Port'], p['Protocol']) for p in ports))
ATTENDUES = ['App.SupportsUniversalSleep', 'App.WakeupMode', 'App.ApplicationReadyMode', 'Console.FilterMatchRegex', 'Console.FilterMatchReplacement', 'Console.ThrowawayMessageRegex', 'Console.AppReadyRegex', 'Console.UserJoinRegex', 'Console.UserLeaveRegex', 'Console.UserChatRegex', 'Console.UpdateAvailableRegex', 'Console.PreConnectRegex', 'Console.ConnectIPRegex', 'Console.MetricsRegex', 'Console.HideFromConsoleRegex', 'Console.SuppressLogAtStart', 'Console.UserActions', 'Limits.SleepMode', 'Limits.SleepOnStart', 'Limits.SleepDelayMinutes', 'Limits.DozeDelay', 'Limits.AutoRetryCount', 'Limits.SleepStartThresholdSeconds']
absentes = [c for c in ATTENDUES if c not in cles]
if absentes:
    soucis.append('clés absentes du .kvp : ' + ', '.join(absentes))
else:
    print('ok   kvp complet              les %d clés Console/Limits sont là' % len(ATTENDUES))
if cles.get('App.ApplicationReadyMode') == 'RegexMatch' and not cles.get('Console.AppReadyRegex'):
    soucis.append('RegexMatch sans AppReadyRegex : l’instance ne serait jamais déclarée prête')
if cles.get('App.HasWriteableConsole') != 'True' or cles.get('App.AdminMethod') != 'STDIO':
    soucis.append('la console d’AMP doit écrire dans le lanceur (HasWriteableConsole=True, AdminMethod=STDIO)')
if cles.get('App.ExitMethod') != 'SIGTERM':
    soucis.append('App.ExitMethod doit être SIGTERM : le lanceur le traduit en « shut_down now »')
if cles.get('Meta.URL') != data['manifest.json']['url']:
    soucis.append('Meta.URL et manifest.json ne désignent pas le même dépôt')

# ── 3. réglages ↔ modèle ─────────────────────────────────────────────────────
modele = lire(MODELE)
dans_modele = re.findall(r'\{\{([A-Za-z0-9_]+)\}\}', modele)
params = {}
for c in config:
    p = c.get('ParamFieldName')
    if p in params:
        soucis.append('réglage en double : %s' % p)
    params[p] = c
    if c['FieldName'] != p:
        soucis.append('%s : FieldName et ParamFieldName différents (%s)' % (p, c['FieldName']))
    if p not in dans_modele:
        soucis.append('réglage %s exposé dans AMP mais absent de %s' % (p, MODELE))
    if dans_modele.count(p) > 1:
        soucis.append('{{%s}} écrit deux fois dans le modèle' % p)
    if c['InputType'] == 'number' and not str(c.get('DefaultValue', '')).isdigit():
        soucis.append('%s : valeur par défaut non numérique' % p)
orphelins = set(dans_modele) - set(params)
if orphelins:
    soucis.append('{{...}} sans réglage dans AMP : %s' % ', '.join(sorted(orphelins)))
else:
    print('ok   correspondance           %d réglages, tous dans %s' % (len(params), MODELE))
meta = data[NOM + 'metaconfig.json'][0]
racine = cles['App.RootDir'].strip('./').strip('/')
if meta.get('ConfigType') != 'template' or meta.get('ConfigFileTemplate') != racine + '/AMP_wesnothd.cfg':
    soucis.append('metaconfig : ConfigFileTemplate devrait être %s/AMP_wesnothd.cfg' % racine)
if meta.get('ConfigFile') != 'wesnothd.cfg' or 'CFG=wesnothd.cfg' not in lire(LANCEUR):
    soucis.append('le fichier rendu par AMP (ConfigFile) n’est pas celui que lit le lanceur')
if 'TeamKit.fr' not in params['motd']['DefaultValue'] or 'discord.gg/EuAjGMYPHY' not in params['motd']['DefaultValue']:
    soucis.append('le message d’accueil par défaut doit citer TeamKit.fr et le Discord')

# ── 4. forme des lignes du modèle ────────────────────────────────────────────
for p, c in params.items():
    ligne = [l for l in modele.splitlines() if '{{%s}}' % p in l]
    if not ligne:
        continue
    ligne = ligne[0]
    if c['InputType'] in ('text', 'password'):
        if ligne != '%s=<<{{%s}}>>' % (p, p):
            soucis.append('%s doit s’écrire %s=<<{{%s}}>> (chaîne brute WML), pas : %s' % (p, p, p, ligne))
    elif ligne != '%s={{%s}}' % (p, p):
        soucis.append('ligne inattendue pour %s : %s' % (p, ligne))
for l in modele.splitlines():
    if l.startswith('#') or not l.strip():
        continue
    if '"{{' in l:
        soucis.append('un réglage entre guillemets droits : %s' % l)
    if not re.match(r'^(?:[a-z_]+=.*|\{\./perso\.cfg\})$', l):
        soucis.append('ligne du modèle ni attribut ni inclusion : %s' % l)
    if l.startswith('{') and not l.startswith('{./'):
        soucis.append('inclusion sans ./ : le lecteur WML chercherait dans data/ : %s' % l)
if not modele.rstrip().endswith('{./perso.cfg}'):
    soucis.append('{./perso.cfg} doit être la dernière ligne (perso.cfg passe après les réglages d’AMP)')
for l in modele.splitlines():
    if l.startswith('#') and '{' in l:
        soucis.append('accolade dans un commentaire du modèle : à éviter (préprocesseur) : %s' % l)
print('ok   forme du modèle          textes en <<...>>, nombres nus, perso.cfg en dernier')


# ── 5. aller-retour rendu AMP -> lanceur -> lecteur WML ──────────────────────
def rendre(valeurs):
    t = modele
    for p, v in valeurs.items():
        t = t.replace('{{%s}}' % p, v)
    return t


class Refus(Exception):
    pass


def corriger_comme_le_lanceur(t):
    # Même travail que le awk de lancer-wesnothd.sh : corrige la ligne motd, refuse
    # >> ou un > final dans passwd et versions_accepted (Refus = le lanceur s'arrête).
    sortie = []
    for l in t.splitlines():
        for cle in ('passwd', 'versions_accepted'):
            if l.startswith(cle + '=<<') and l.endswith('>>') and len(l) >= len(cle) + 5:
                v = l[len(cle) + 3:-2]
                if '>>' in v or v.endswith('>'):
                    raise Refus(cle)
        if l.startswith('motd=<<') and l.endswith('>>') and len(l) >= 9:
            v = l[7:-2].replace('"', "'")
            while '>>' in v:
                v = v.replace('>>', '> >', 1)
            if v.endswith('>'):
                v += ' '
            l = 'motd=<<' + v + '>>'
        sortie.append(l)
    return '\n'.join(sortie)


def relire(t, cle):
    # Lecteur WML : cle=<<brut>> s'arrête au premier >> ; cle=nombre jusqu'à la fin.
    for l in t.splitlines():
        if l.startswith(cle + '=<<'):
            reste = l[len(cle) + 3:]
            fin = reste.find('>>')
            if fin < 0 or reste[fin + 2:].strip():
                return None  # chaîne cassée : wesnothd refuserait le fichier
            return reste[:fin]
        if l.startswith(cle + '='):
            return l[len(cle) + 1:]
    return None


defauts = {p: str(c.get('DefaultValue', '')) for p, c in params.items()}
ESSAIS_TEXTE = [
    '',
    'avec des espaces',
    'Serveur francophone hébergé gratuitement par TeamKit.fr — teamkit.fr · Discord : discord.gg/EuAjGMYPHY',
    "Bienvenue, l'équipe : règles {ici} #1, 100 % + < > ; fin",
    '1.18.*, 1.19.*',
]
n = 0
for p, c in params.items():
    if c['InputType'] not in ('text', 'password'):
        continue
    for v in ESSAIS_TEXTE:
        vals = dict(defauts)
        vals[p] = v
        lu = relire(corriger_comme_le_lanceur(rendre(vals)), p)
        n += 1
        if lu != v:
            soucis.append('aller-retour %s : écrit %r, relu %r' % (p, v, lu))
# ce que le lanceur doit corriger dans le message d'accueil
for v, attendu in [('Dites "bonjour"', "Dites 'bonjour'"), ('a >> b', 'a > > b'), ('a >>> b >', 'a > > > b > ')]:
    vals = dict(defauts)
    vals['motd'] = v
    lu = relire(corriger_comme_le_lanceur(rendre(vals)), 'motd')
    n += 1
    if lu != attendu:
        soucis.append('correction du motd : %r devient %r au lieu de %r' % (v, lu, attendu))
for p, c in params.items():
    if c['InputType'] == 'number':
        for v in (c['DefaultValue'], ''):
            vals = dict(defauts)
            vals[p] = v
            n += 1
            if relire(rendre(vals), p) != v:
                soucis.append('aller-retour %s : %r' % (p, v))
# ce que le lanceur doit refuser (mot de passe et versions : les modifier changerait leur sens)
REFUSES = ['a>>b', 'abc>', 'a >>> b', '>>']
for p in ('passwd', 'versions_accepted'):
    for v in REFUSES:
        vals = dict(defauts)
        vals[p] = v
        n += 1
        try:
            corriger_comme_le_lanceur(rendre(vals))
            soucis.append('%s = %r : le lanceur devrait refuser' % (p, v))
        except Refus:
            pass
    vals = dict(defauts)
    vals[p] = 'a > b'
    n += 1
    if relire(corriger_comme_le_lanceur(rendre(vals)), p) != 'a > b':
        soucis.append('%s : un > isolé doit passer tel quel' % p)
for p in ('passwd', 'versions_accepted'):
    if '>>' not in params[p]['Description'] and '"' not in params[p]['Description']:
        soucis.append('%s : la description doit prévenir pour " et >>' % p)
print('ok   aller-retour             %d valeurs (vide, espaces, accents, virgules, {, #, ", >>)' % n)

# ── 6. fichiers téléchargés à l'Update ───────────────────────────────────────
depot = data['manifest.json']['url'].replace('https://github.com/', '')
fetch = [e for e in updates if e['UpdateSource'] == 'FetchURL']
for e in fetch:
    attendu = 'https://raw.githubusercontent.com/%s/main/scripts/%s' % (depot, e['UpdateSourceArgs'])
    if e['UpdateSourceData'] != attendu:
        soucis.append('URL inattendue pour %s : %s' % (e['UpdateSourceArgs'], e['UpdateSourceData']))
    elif not os.path.isfile(os.path.join(ICI, 'scripts', e['UpdateSourceArgs'])):
        soucis.append('scripts/%s absent du dépôt' % e['UpdateSourceArgs'])
    else:
        print('ok   téléchargé à l’Update    scripts/%s' % e['UpdateSourceArgs'])
if {e['UpdateSourceArgs'] for e in fetch} != {'AMP_wesnothd.cfg', 'lancer-wesnothd.sh'}:
    soucis.append('l’Update doit déposer AMP_wesnothd.cfg et lancer-wesnothd.sh')

# ── 7. lanceur ───────────────────────────────────────────────────────────────
for nom in (LANCEUR, MODELE):
    brut = lire(nom, binaire=True)
    if b'\r' in brut:
        soucis.append('%s : fins de ligne Windows (CRLF)' % nom)
lanceur = lire(LANCEUR)
if '{{' in lanceur:
    soucis.append('le lanceur contient {{ : AMP pourrait le remplacer')
paquets = json.loads(cles['Meta.ExtraContainerPackages'])
m = re.search(r'^BIN=(\S+)$', lanceur, re.M)
binaire = m.group(1) if m else None
serie = re.match(r'wesnoth-(\d+\.\d+)-server$', paquets[0]) if paquets else None
if not serie or binaire != '/usr/games/wesnothd-%s' % serie.group(1):
    soucis.append('binaire %s et paquet %s ne vont pas ensemble' % (binaire, paquets))
elif binaire not in updates[0]['UpdateSourceArgs']:
    soucis.append('l’étape de vérification ne teste pas %s' % binaire)
else:
    print('ok   paquet                   %s -> %s' % (paquets[0], binaire))
    # Par défaut : 1.18.8 et suivantes (faille côté client corrigée en 1.18.8).
    motifs = [m.strip() for m in params['versions_accepted']['DefaultValue'].split(',')]
    if not motifs or any(not m.startswith(serie.group(1) + '.') for m in motifs):
        soucis.append('versions acceptées par défaut hors de la série du paquet %s : %s' % (serie.group(1), motifs))
    # même jeu de caractères que utils::wildcard_string_match : * et ?
    def accepte(v):
        return any(re.fullmatch(re.escape(m).replace(r'\*', '.*').replace(r'\?', '.'), v) for m in motifs)
    for v, attendu in [('1.18.8', True), ('1.18.9', True), ('1.18.10', True), ('1.18.19', True),
                       ('1.18.7', False), ('1.18.5', False), ('1.18.1', False), ('1.18.0', False),
                       ('1.19.28', False), ('1.16.12', False)]:
        if accepte(v) != attendu:
            soucis.append('versions par défaut : %s %s' % (v, 'refusée' if attendu else 'acceptée'))
for besoin, pourquoi in [
    ('-c "$PWD/$CFG"', 'chemin absolu de la config, sinon {./perso.cfg} est introuvable'),
    ('FIFO="${XDG_RUNTIME_DIR:-/tmp}/', 'fifo hors du dossier de l’instance (sauvegardes AMP)'),
    ('/^fifo_path=/', 'le lanceur doit réécrire fifo_path'),
    ('/^motd=<<.*>>$/', 'le lanceur doit corriger le motd'),
    ('shut_down now', 'arrêt propre'),
    ('--pdeathsig TERM', 'wesnothd ne doit pas survivre au lanceur'),
    ('echo "TeamKit : wesnothd pret, il ecoute sur le port $PORT."', 'ligne prêt'),
]:
    if besoin not in lanceur:
        soucis.append('lanceur : %s (%s)' % (besoin, pourquoi))
if not re.search(r'^fifo_path=', modele, re.M):
    soucis.append('le modèle doit contenir une ligne fifo_path= (remplacée par le lanceur)')
bash = shutil.which('bash')
if bash:
    r = subprocess.run([bash, '-n', os.path.join(ICI, LANCEUR)], capture_output=True, text=True)
    if r.returncode:
        soucis.append('bash -n %s : %s' % (LANCEUR, r.stderr.strip()))
    else:
        print('ok   bash -n                  %s' % LANCEUR)
else:
    print('--   bash -n                  pas de bash ici, syntaxe non vérifiée')
# Le vrai awk du lanceur, face au miroir Python ci-dessus (section 5).
awk = shutil.which('awk')
debut = lanceur.find('awk -v fifo="$FIFO" -v q="\'" \'\n')
fin = lanceur.find('\n\' "$CFG" > "$CFG.tmp"\n', debut)
prog = lanceur[lanceur.index('\n', debut) + 1:fin + 1] if 0 <= debut < fin else None
if not prog:
    soucis.append('lanceur : bloc awk introuvable (le vérificateur ne sait plus le tester)')
elif awk:
    import tempfile
    k = 0
    avant = len(soucis)
    # Programme dans un fichier (-f), fifo et q posées par un BEGIN au lieu de -v : sous
    # Windows (Git Bash), un argument multiligne ou une apostrophe seule sont abîmés.
    with tempfile.NamedTemporaryFile('w', suffix='.awk', delete=False, encoding='utf-8', newline='\n') as f:
        f.write('BEGIN { fifo = "x.fifo"; q = sprintf("%c", 39) }\n' + prog)
    fichier_awk = f.name.replace('\\', '/')
    for p, v in [('motd', 'Dites "bonjour" >> a >'), ('passwd', 'secret > ok'), ('passwd', 'a>>b'), ('passwd', 'fin>'),
                 ('versions_accepted', '1.18.*'), ('versions_accepted', '1.18.*>>')]:
        vals = dict(defauts)
        vals[p] = v
        t = rendre(vals)
        try:
            attendu, code_attendu = corriger_comme_le_lanceur(t).replace('fifo_path="remplace au demarrage par lancer-wesnothd.sh"', 'fifo_path="x.fifo"'), 0
        except Refus:
            attendu, code_attendu = None, 3
        r = subprocess.run([awk, '-f', fichier_awk], input=t + '\n',
                           capture_output=True, text=True, encoding='utf-8')
        k += 1
        if r.returncode != code_attendu or (attendu is not None and r.stdout.rstrip('\n') != attendu):
            soucis.append('awk du lanceur, %s = %r : code %d au lieu de %d' % (p, v, r.returncode, code_attendu))
        elif code_attendu == 3 and 'ERREUR' not in r.stderr:
            soucis.append('awk du lanceur, %s = %r : refus sans message' % (p, v))
    os.remove(f.name)
    if len(soucis) == avant:
        print('ok   awk du lanceur           %d essais, mêmes résultats que le miroir Python' % k)
else:
    print('--   awk                      pas de awk ici, bloc du lanceur non exécuté')

# ── 8. regex de console sur de vraies lignes (wesnothd 1.18.5, 10/10/2026) ────
pret_ligne = 'TeamKit : wesnothd pret, il ecoute sur le port 15000.'
ESSAIS = [
    ('Console.AppReadyRegex', pret_ligne, {}),
    ('Console.UserJoinRegex', '20261010 16:38:41 info server: 127.0.0.1\tKevin\thas logged on', {'username': 'Kevin'}),
    ('Console.UserJoinRegex', '20261010 16:38:46 info server: 127.0.0.1\tDebut118\thas logged on', {'username': 'Debut118'}),
    # format du code (server.cpp) : connexion TLS = « + » devant l'IP, compte du forum
    ('Console.UserJoinRegex', '20261010 16:38:41 info server: +2a01:e0a:1:2::3\tJean-Luc_2\thas logged on to a registered account', {'username': 'Jean-Luc_2'}),
    ('Console.UserLeaveRegex', '20261010 16:38:45 info server: 127.0.0.1\tKevin\thas logged off', {'username': 'Kevin'}),
    ('Console.ThrowawayMessageRegex', '20261010 16:38:41 error server: 127.0.0.1\tTLS requested by client but not enabled on server', {}),
]
for cle, ligne, attendu in ESSAIS:
    m = py(cles.get(cle) or '^$').search(ligne)
    if not m or any(m.group(k) != v for k, v in attendu.items()):
        soucis.append('%s ne reconnaît pas : %r' % (cle, ligne))
PIEGES = [
    ('Console.UserJoinRegex', '20261010 16:38:41 info server: 127.0.0.1\tplayer joined using accepted version 1.18.8:\ttelling them to log in.'),
    ('Console.UserJoinRegex', '20261010 16:38:51 info server: 127.0.0.1\tFaux\thas logged off'),
    ('Console.UserJoinRegex', '20261010 16:38:43 info server: <server> Kevin has logged on demain'),
    ('Console.UserLeaveRegex', '20261010 16:38:41 info server: 127.0.0.1\tKevin\thas logged on'),
    ('Console.UserLeaveRegex', '20261010 16:38:48 info server: 127.0.0.1\tconnection closed'),
    ('Console.AppReadyRegex', '20261010 16:38:41 info server: opened fifo at \'/tmp/wesnothd-15000.fifo\'. Server commands may be written to this file.'),
    ('Console.ThrowawayMessageRegex', '20261010 16:38:41 info server: 127.0.0.1\tKevin\thas logged on'),
    ('Console.ThrowawayMessageRegex', '20261010 16:38:45 error server: <unknown address>\tConnection reset by peer'),
]
for cle, ligne in PIEGES:
    if py(cles[cle]).search(ligne):
        soucis.append('%s attrape une ligne qui n’est pas pour lui : %r' % (cle, ligne))
print('ok   console                  %d lignes réelles, %d pièges' % (len(ESSAIS), len(PIEGES)))

print()
if soucis:
    print('%d problème(s) :' % len(soucis))
    print('\n'.join('  NON  ' + s for s in soucis))
    sys.exit(1)
print('Tout est bon.')
