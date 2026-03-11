# ThermoCalc

Application web de suivi et de repartition de consommation de chauffage a partir de tetes thermostatiques Zigbee TRV26.

## Objectif

Chaque personne dispose d'un ensemble different de tetes thermostatiques, rattachees a des surfaces de chauffage differentes. Le projet estime une part relative de consommation sur une periode mensuelle a partir de:

- la temperature de consigne
- la temperature reelle de la piece
- la surface de chauffage associee a chaque tete
- le temps passe a demander du chauffage

Le resultat est une repartition relative en pourcentage, pas une mesure physique exacte en kWh. Le modele pourra ensuite etre calibre avec une consommation reelle de chaudiere ou de compteur global.

## Hypothese De Calcul

Pour chaque mesure d'une tete, ThermoCalc construit d'abord un facteur de demande composite:

- delta = max(temperature_consigne - temperature_reelle, 0)
- facteur_vanne = ouverture_vanne / 100
- facteur_etat = 1 si `running_state = heat`, 0 si `running_state = idle`, 0.5 si l'etat n'est pas connu
- facteur_duty = duty_cycle / 100 quand il est disponible, sinon on retombe sur `facteur_vanne`
- facteur_demande = 0.55 x facteur_vanne + 0.25 x facteur_etat + 0.20 x facteur_duty
- effort = delta x surface x facteur_demande

Sur un mois, on somme l'effort de toutes les tetes d'une personne, puis on normalise pour obtenir un pourcentage du total.

## Fonctionnalites Incluses

- API FastAPI
- page web de suivi mensuel
- ecran d'administration pour gerer occupants, tetes et surfaces
- page de test de calculs pour rejouer des scenarios de chauffe via une interface dediee
- page de test de consommation pour simuler chauffage plus ECS par occupant
- generation de rapport PDF mensuel
- planification mensuelle automatique de generation PDF
- authentification simple par session sur l'administration
- gestion fine des archives PDF: filtrage, renommage, suppression et export ZIP
- zone Zigbee modulaire en admin pour plusieurs controleurs, detecteurs, tetes et recepteurs
- integration Zigbee2MQTT reelle via MQTT pour discovery, permit_join et telemetrie temps reel
- synchronisation automatique des thermostats Zigbee vers les affectations de consommation
- vue de topologie par controleur
- panneau de telemetrie TRV26 avec batterie, running state, preset, error status et duty cycle
- alerte mail quand une batterie descend sous le seuil configure
- tests unitaires du modele de calcul et des integrations principales

## Documentation Markdown

Une documentation detaillee est disponible dans `docs/`:

- `docs/README.md` : point d'entree de la documentation
- `docs/API.md` : endpoints HTML, JSON, PDF et actions admin
- `docs/ARCHITECTURE.md` : architecture applicative et flux de donnees
- `docs/EXPLOITATION.md` : installation, configuration et exploitation
- `docs/TEST_CALCULS.md` : mode de simulation de scenarios de chauffe

## Test De Consommation

La page `/test-consommation` etend le mode test de chauffe avec une saisie ECS par occupant.

Elle permet de:

- charger un scenario de chauffe predefini ou manuel
- saisir un volume ECS de test par occupant
- definir une facture combustible totale et son libelle
- visualiser la synthese combinee chauffage plus ECS sans rien enregistrer en base JSON
- repartir cette facture via une ponderation configurable entre part chauffage et part ECS

## Demarrage

1. Creer un environnement Python 3.11 ou plus.
2. Installer le projet en mode editable avec les dependances de dev.
3. Ajuster le fichier `thermocalc.config.toml` a la racine du projet.
4. Lancer le serveur Uvicorn.

Commandes typiques:

```powershell
python -m pip install -e .[dev]
python -m uvicorn app.main:app --reload
```

L'interface web sera disponible sur `http://127.0.0.1:8000`.

## Fichier De Configuration

Les parametres transverses et sensibles sont centralises dans `thermocalc.config.toml` a la racine du projet.

Le fichier couvre notamment:

- les identifiants admin
- le secret de session
- la ponderation de facture entre chauffage et ECS
- le stockage local des dernieres mesures TRV
- l'activation du mode temps reel MQTT et la fenetre de fraicheur des mesures
- la fenetre de calcul du duty cycle TRV26 et la retention d'historique
- le seuil batterie faible et l'adresse mail de notification
- la configuration SMTP d'envoi d'alerte
- les valeurs par defaut du bridge Zigbee2MQTT
- l'URL MQTT, le login, le mot de passe et le `base_topic`
- l'intervalle d'auto-discovery
- la duree par defaut de `permit_join`

Exemple de sections:

```toml
[admin]
username = "admin"
password = "thermocalc-admin"
session_secret = "change-me"

[app]
scheduler_poll_seconds = 60
generated_reports_dir = "generated_reports"
runtime_measurements_path = "runtime_measurements.json"
realtime_mqtt_enabled = true
sample_fallback_enabled = true
realtime_measurement_max_age_minutes = 180
trv26_duty_cycle_window_hours = 24
trv26_history_retention_hours = 72

[billing]
heating_weight = 0.5
ecs_weight = 0.5

[alerts]
low_battery_threshold_percent = 10
email_to = "maintenance@example.com"
email_from = "thermocalc@example.com"

[smtp]
host = "smtp.example.com"
port = 587
username = "smtp-user"
password = "smtp-password"
use_tls = true

[zigbee2mqtt.defaults]
controller_id = "z2m-main"
controller_label = "Zigbee2MQTT Principal"
mqtt_url = "mqtt://localhost:1883"
mqtt_username = ""
mqtt_password = ""
base_topic = "zigbee2mqtt"
auto_discovery_enabled = true
discovery_interval_minutes = 15
permit_join_seconds = 60
```

## Fonctionnement Global

Le projet fonctionne en cinq couches principales:

1. collecte et administration des metadonnees
2. inventaire Zigbee et appairages logiques
3. collecte temps reel et telemetrie TRV26
4. calcul de repartition de consommation
5. restitution web, PDF et archives

### 1. Administration Metier

Depuis `/admin`, on renseigne:

- les occupants
- les surfaces de chauffage
- les affectations de tetes thermostatiques
- les bridges Zigbee et leur configuration MQTT

### 2. Inventaire Zigbee

Chaque controleur Zigbee peut:

- etre teste en connectivite MQTT
- ouvrir une fenetre `permit_join`
- lancer une discovery manuelle sur `bridge/devices`
- lancer une auto-discovery periodique via le scheduler applicatif

L'inventaire distant remonte des devices classes comme:

- `thermostat`
- `detector`
- `receiver`

### 3. Telemetrie TRV26

Le provider `zigbee2mqtt` ecoute les releves TRV en fond sur `zigbee2mqtt/<friendly_name>` pour chaque controleur actif.

ThermoCalc conserve:

- les derniers points utiles au calcul
- un historique roulant local pour chaque tete
- les champs de telemetrie `battery`, `running_state`, `preset` et `error_status`

Le panneau "Telemetrie TRV26" de l'administration affiche aussi un premier duty cycle calcule sur la fenetre `trv26_duty_cycle_window_hours`.

Si une tete descend sous `low_battery_threshold_percent`, elle est marquee `A remplacer` dans l'administration et une alerte mail est envoyee a `alerts.email_to` quand le SMTP est configure.

### 4. Calcul De Consommation

Le moteur de calcul privilegie les dernieres mesures TRV26 recues en MQTT. Si aucune mesure recente n'est disponible, il retombe sur le jeu JSON de test local.

Il applique ensuite une ponderation simple:

- $\Delta = \max(T_{consigne} - T_{reelle}, 0)$
- $f_{vanne} = ouverture / 100$
- $f_{etat} = 1$ si `heat`, $0$ si `idle`, sinon $0.5$
- $f_{duty} = duty\_cycle / 100$ ou $f_{vanne}$ si le duty cycle n'est pas disponible
- $f_{demande} = 0.55 \times f_{vanne} + 0.25 \times f_{etat} + 0.20 \times f_{duty}$
- $effort = \Delta \times surface \times f_{demande}$

Les scores par tete sont agreges par occupant puis normalises en pourcentage mensuel.

Quand une facture combustible totale doit etre repartie, ThermoCalc combine ensuite:

- la part chauffage de chaque occupant
- la part ECS de chaque occupant

Par defaut, les deux composantes sont ponderees a 50/50 via `billing.heating_weight` et `billing.ecs_weight` dans `thermocalc.config.toml`.

Cette formule garde la vanne comme signal principal, mais elle corrige le calcul avec:

- l'etat instantane de chauffe `running_state`
- l'activite recente de la tete via le duty cycle

Cela evite qu'une simple ouverture instantanee de vanne pondere trop fortement une tete qui n'est presque jamais en chauffe sur la periode recente.

### 5. Restitution

Le projet produit:

- une page de suivi
- une administration securisee par session
- des PDF mensuels
- des archives filtrables et exportables
- une topologie Zigbee visuelle en SVG par controleur

## Structure

- `app/main.py` initialise l'application FastAPI.
- `app/api/routes.py` expose le dashboard HTML, l'administration, l'API JSON et l'endpoint PDF.
- `app/services/consumption.py` contient le modele de repartition.
- `app/services/reporting.py` genere le PDF mensuel.
- `app/services/admin_state.py` persiste la configuration occupants, tetes et planning.
- `app/services/runtime_measurements.py` maintient les derniers releves TRV26 recus sur MQTT, l'historique roulant et les abonnements en fond.
- `app/services/notifications.py` envoie les alertes mail de batterie faible.
- `app/services/scheduler.py` verifie la planification et ecrit les PDF sur disque.
- `app/services/zigbee2mqtt.py` pilote la discovery MQTT et `permit_join` pour les bridges Zigbee2MQTT.
- `data/sample_data.json` fournit un jeu JSON de test.
- `data/runtime_measurements.json` persiste les dernieres mesures temps reel retenues par le calcul et la telemetrie.

## Administration

L'ecran `/admin` permet de:

- enregistrer les occupants
- declarer plusieurs controleurs Zigbee
- inventorier plusieurs detecteurs, tetes thermostatiques et recepteurs par controleur
- creer des liens d'appairage entre detecteurs, tetes et recepteurs
- lancer la discovery Zigbee2MQTT sur `bridge/devices`
- activer `permit_join` depuis l'administration pour un bridge Zigbee2MQTT
- tester la connectivite MQTT et l'etat du bridge
- activer une remontee automatique periodique de discovery par controleur
- preparer l'appairage guide d'une nouvelle tete thermostatique
- affecter une tete TRV26 a un occupant et a une surface de chauffage
- suivre la telemetrie TRV26 avec batterie, running state, preset, error status et duty cycle
- laisser le dashboard et les PDF basculer automatiquement sur les mesures MQTT recentes quand elles existent
- regler un planning mensuel de generation PDF
- lancer manuellement la generation d'un PDF archive sur disque
- filtrer les archives par plage de mois et par occupant
- renommer ou supprimer une archive existante
- exporter un lot d'archives en ZIP

## Test De Calculs

La page `/test-calculs` est reservee a la session admin et permet de verifier le moteur de repartition sur des scenarios controles.

Elle permet de:

- charger des presets de chauffe typiques
- modifier manuellement toutes les valeurs par zone
- executer un calcul sans toucher aux mesures reelles, a l'ECS ou aux archives
- visualiser la repartition finale et le detail du score par zone

Les fichiers de configuration metier sont stockes dans `data/admin_state.json`. Les PDF archives sont ecrits dans `generated_reports/`.

L'authentification admin est volontairement simple. Par defaut, ces valeurs sont lues depuis `thermocalc.config.toml`:

- identifiant: `admin`
- mot de passe: `thermocalc-admin`

## Couche Zigbee

La zone Zigbee en administration est modulaire:

- plusieurs controleurs peuvent coexister
- chaque controleur peut exposer plusieurs devices de type detecteur, tete thermostatique ou recepteur
- les liens d'appairage sont geres explicitement pour permettre plusieurs detecteurs et plusieurs recepteurs

Le provider `zigbee2mqtt` est branche via MQTT:

- `endpoint_url` attend un broker du type `mqtt://hote:1883`
- `base_topic` vaut `zigbee2mqtt` par defaut
- la discovery lit `zigbee2mqtt/bridge/devices`
- l'appairage physique publie sur `zigbee2mqtt/bridge/request/permit_join`
- un test de connectivite s'abonne a `zigbee2mqtt/bridge/state` quand disponible

Une auto-discovery periodique peut etre activee par controleur. Le scheduler applicatif rafraichit alors l'inventaire sans action manuelle et conserve les metadonnees metier deja saisies sur les thermostats.

Quand un device Zigbee de role `thermostat` est renseigne avec occupant, zone et surface, l'affectation de consommation correspondante est synchronisee automatiquement sur la tete homologue.

L'assistant d'appairage des nouvelles tetes peut en plus pre-creer une tete attendue avec son occupant, sa zone et sa surface pendant l'ouverture de `permit_join`, ce qui accelere la mise en production apres discovery.

La topologie est aussi rendue visuellement en SVG genere cote serveur pour chaque controleur.

## Source TRV

Le projet cible les tetes type TRV26 exposees via Zigbee2MQTT. L'integration MQTT directe couvre maintenant:

- la discovery des devices
- l'activation de `permit_join`
- le test de connectivite du bridge
- la remontee temps reel des mesures utilisees par le calcul de repartition
- la remontee de telemetrie TRV26 et les alertes batterie faible

Le fichier `data/sample_data.json` reste present comme jeu JSON de test tant que toutes les tetes ne remontent pas encore leurs mesures en MQTT.
