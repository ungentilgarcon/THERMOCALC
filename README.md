# ThermoCalc

Application web de suivi et de repartition approximative de consommation de chauffage a partir de tetes thermostatiques Zigbee TRV26.

## Objectif

Chaque personne dispose d'un ensemble different de tetes thermostatiques, rattachees a des surfaces de chauffage differentes. Le projet estime une part relative de consommation sur une periode mensuelle a partir de:

- la temperature de consigne
- la temperature reelle de la piece
- la surface de chauffage associee a chaque tete
- le temps passe a demander du chauffage

Le resultat est une repartition relative en pourcentage, pas une mesure physique exacte en kWh. Le modele pourra ensuite etre calibre avec une consommation reelle de chaudiere ou de compteur global.

## Hypothese de calcul initiale

Pour chaque mesure d'une tete:

- delta = max(temperature_consigne - temperature_reelle, 0)
- effort = delta x coefficient_surface x coefficient_ouverture

Sur un mois, on somme l'effort de toutes les tetes d'une personne, puis on normalise pour obtenir un pourcentage du total.

## Fonctionnalites incluses

- API FastAPI
- page web de suivi mensuel
- ecran d'administration pour gerer occupants, tetes et surfaces
- donnees d'exemple pour demarrage rapide
- generation de rapport PDF mensuel
- planification mensuelle automatique de generation PDF
- authentification simple par session sur l'administration
- gestion fine des archives PDF: filtrage, renommage, suppression et export ZIP
- zone Zigbee modulaire en admin pour plusieurs controleurs, detecteurs, tetes et recepteurs
- integration Zigbee2MQTT reelle via MQTT pour discovery et permit_join
- synchronisation automatique des thermostats Zigbee vers les affectations de consommation
- vue de topologie par controleur
- tests unitaires du modele de calcul

## Demarrage

1. Creer un environnement Python 3.11 ou plus.
2. Installer le projet en mode editable avec les dependances de dev.
3. Lancer le serveur Uvicorn.
4. Ajuster le fichier `thermocalc.config.toml` a la racine du projet.

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
- le stockage local des dernieres mesures TRV
- l'activation du mode temps reel MQTT et la fenetre de fraicheur des mesures
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

Le projet fonctionne en quatre couches principales:

1. collecte et administration des metadonnees
2. inventaire Zigbee et appairages logiques
3. calcul de repartition de consommation
4. restitution web, PDF et archives

### 1. Administration metier

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

### 3. Synchronisation thermostat

Quand une tete Zigbee de role `thermostat` est connue avec:

- un occupant
- une zone
- une surface

alors une affectation de consommation TRV correspondante est synchronisee automatiquement.

Inversement, si une affectation TRV est modifiee pour une tete deja connue dans l'inventaire Zigbee, les metadonnees du device Zigbee thermostat sont realignees.

### 4. Calcul de consommation

Le moteur de calcul privilegie maintenant les dernieres mesures TRV26 recues en MQTT. Si aucune mesure recente n'est disponible, il retombe sur le jeu JSON d'exemple. Il applique ensuite une ponderation simple:

- $
\Delta = \max(T_{consigne} - T_{reelle}, 0)
$
- $effort = \Delta \times surface \times ouverture$

Les scores par tete sont agreges par occupant puis normalises en pourcentage mensuel.

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
- `app/services/runtime_measurements.py` maintient les derniers releves TRV26 recus sur MQTT et gere les abonnements en fond.
- `app/services/scheduler.py` verifie la planification et ecrit les PDF sur disque.
- `app/services/zigbee2mqtt.py` pilote la discovery MQTT et `permit_join` pour les bridges Zigbee2MQTT.
- `data/sample_data.json` fournit un jeu de donnees de demonstration.
- `data/runtime_measurements.json` persiste les dernieres mesures temps reel retenues par le calcul.

## Administration

L'ecran `/admin` permet de:

- enregistrer les occupants
- declarer plusieurs controleurs Zigbee
- inventorier plusieurs detecteurs, tetes thermostatiques et recepteurs par controleur
- creer des liens d'appairage entre detecteurs, tetes et recepteurs
- lancer la discovery Zigbee2MQTT sur `bridge/devices`
- activer `permit_join` depuis l'administration pour un bridge Zigbee2MQTT
- tester la connectivite MQTT et l'etat du bridge
- activer une remontée automatique periodique de discovery par controleur
- preparer l'appairage guide d'une nouvelle tete thermostatique
- affecter une tete TRV26 a un occupant et a une surface de chauffage
- laisser le dashboard et les PDF basculer automatiquement sur les mesures MQTT recentes quand elles existent
- regler un planning mensuel de generation PDF
- lancer manuellement la generation d'un PDF archive sur disque
- filtrer les archives par plage de mois et par occupant
- renommer ou supprimer une archive existante
- exporter un lot d'archives en ZIP

Les fichiers de configuration sont stockes dans `data/admin_state.json`. Les PDF archives sont ecrits dans `generated_reports/`.

L'authentification admin est volontairement simple. Par defaut, ces valeurs sont lues depuis `thermocalc.config.toml`:

- identifiant: `admin`
- mot de passe: `thermocalc-admin`

## Couche Zigbee

La zone Zigbee en administration est modulaire:

- plusieurs controleurs peuvent coexister
- chaque controleur peut exposer plusieurs devices de type detecteur, tete thermostatique ou recepteur
- les liens d'appairage sont geres explicitement pour permettre plusieurs detecteurs et plusieurs recepteurs

Le provider `mock` est operationnel pour preparer la topologie. Le provider `zigbee2mqtt` est prevu comme point d'integration pour un bridge reel et un futur `permit_join` ou inventaire distant.

Le provider `zigbee2mqtt` est maintenant branche via MQTT:

- `endpoint_url` attend un broker du type `mqtt://hote:1883`
- `base_topic` vaut `zigbee2mqtt` par defaut
- la discovery lit `zigbee2mqtt/bridge/devices`
- l'appairage physique publie sur `zigbee2mqtt/bridge/request/permit_join`
- un test de connectivite s'abonne a `zigbee2mqtt/bridge/state` quand disponible
- les releves TRV sont ecoutes en fond sur `zigbee2mqtt/<friendly_name>` pour chaque controleur actif

Une auto-discovery periodique peut etre activee par controleur. Le scheduler applicatif rafraichit alors l'inventaire sans action manuelle et conserve les metadonnees metier deja saisies sur les thermostats.

Les mesures temps reel conservees pour le calcul sont stockees dans `data/runtime_measurements.json`. Seules les mesures recentes, dans la fenetre `realtime_measurement_max_age_minutes`, sont retenues.

Quand un device Zigbee de role `thermostat` est renseigne avec occupant, zone et surface, l'affectation de consommation correspondante est synchronisee automatiquement sur la tete homologue.

L'assistant d'appairage des nouvelles tetes peut en plus pre-creer une tete attendue avec son occupant, sa zone et sa surface pendant l'ouverture de `permit_join`, ce qui accelere la mise en production apres discovery.

La topologie est aussi rendue visuellement en SVG genere cote serveur pour chaque controleur.

## Source TRV

Le projet cible les tetes type TRV26 exposees via Zigbee2MQTT. L'integration MQTT directe couvre maintenant:

- la discovery des devices
- l'activation de `permit_join`
- le test de connectivite du bridge
- la remontee temps reel des mesures utilisees par le calcul de repartition

Le fichier `data/sample_data.json` reste present comme repli progressif tant que toutes les tetes ne remontent pas encore leurs mesures en MQTT.
