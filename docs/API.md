# API ThermoCalc

ThermoCalc expose deux familles d'endpoints:

- des pages HTML orientees exploitation
- des endpoints techniques JSON ou PDF

## Endpoints publics

### `GET /`

Dashboard principal.

- Affiche la repartition mensuelle courante.
- Signale la source des donnees utilisees: MQTT temps reel ou JSON de test.
- Detaille chaque tete thermostatique prise en compte dans le calcul.

### `GET /api/report`

Retourne le rapport mensuel au format JSON.

Structure principale:

- `month_label`
- `generated_at`
- `allocations[]`
- `zones[]`
- `methodology`

Usage typique:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/report
```

### `GET /reports/monthly.pdf`

Genere le PDF mensuel courant.

- integre la part chauffage par occupant
- integre la part ECS si un calcul ECS correspondant existe
- detaille les zones et scores de chauffe

## Endpoints proteges par session admin

Les pages et actions ci-dessous redirigent vers `/admin/login` si la session n'est pas ouverte.

### Authentification

- `GET /admin/login` : formulaire de connexion
- `POST /admin/login` : ouverture de session
- `POST /admin/logout` : fermeture de session

### Administration metier

- `GET /admin` : ecran principal d'administration
- `POST /admin/occupants` : cree ou met a jour un occupant
- `POST /admin/occupants/delete` : supprime un occupant
- `POST /admin/thermostats` : cree ou met a jour une tete thermostatique
- `POST /admin/thermostats/delete` : supprime une tete thermostatique
- `POST /admin/schedule` : modifie la planification PDF
- `POST /admin/reports/generate` : genere un PDF archive immediatement

### Pilotage chauffage

- `GET /pilotage-chauffage` : page de pilotage chauffage par occupant et par tete
- `POST /pilotage-chauffage/profils` : cree ou met a jour un profil rapide utilisateur
- `POST /pilotage-chauffage/profils/delete` : supprime un profil rapide
- `POST /pilotage-chauffage/plannings` : cree un ou plusieurs creneaux hebdomadaires pour une tete
- `POST /pilotage-chauffage/plannings/delete` : supprime un creneau hebdomadaire
- `POST /pilotage-chauffage/override` : applique un override temporaire a une tete
- `POST /pilotage-chauffage/override/delete` : retire l'override d'une tete
- `POST /pilotage-chauffage/occupants/apply` : applique immediatement les consignes actives a toutes les tetes d'un occupant
- `POST /pilotage-chauffage/occupants/hors-gel` : force toutes les tetes d'un occupant en mode vacances hors-gel
- `POST /pilotage-chauffage/occupants/hors-gel/delete` : retire les overrides en cours d'un occupant

Principes:

- un profil rapide pre-remplit heure de debut, heure de fin et temperature cible
- un creneau peut etre copie sur plusieurs jours en une seule soumission
- un override temporaire reste prioritaire sur le planning
- un mode `hors-gel` occupant est represente visuellement differemment d'un simple override manuel

### Archives PDF

- `GET /admin/archives/export` : export ZIP des archives filtrees
- `GET /admin/archives/{filename}` : telechargement d'une archive PDF
- `POST /admin/archives/rename` : renomme une archive
- `POST /admin/archives/delete` : supprime une archive

Filtres disponibles sur l'export et la liste d'archives:

- `start_month`
- `end_month`
- `owner_name`

### Zigbee et Zigbee2MQTT

- `POST /admin/controllers` : cree ou met a jour un controleur Zigbee
- `POST /admin/controllers/delete` : supprime un controleur
- `POST /admin/controllers/connectivity-test` : teste la connectivite MQTT
- `POST /admin/controllers/discover` : lance une discovery distante
- `POST /admin/controllers/pairing-mode` : ouvre `permit_join`
- `POST /admin/controllers/pair-new-thermostat` : workflow guide d'appairage d'une nouvelle TRV
- `POST /admin/zigbee/devices` : cree ou met a jour un device
- `POST /admin/zigbee/devices/delete` : supprime un device
- `POST /admin/zigbee/pairings` : cree ou met a jour un lien logique
- `POST /admin/zigbee/pairings/delete` : supprime un lien logique

### ECS

- `GET /ecs` : page de saisie et d'historique ECS
- `POST /ecs/calculate` : memorise de nouveaux indexes et calcule une repartition

Principes:

- le premier releve initialise les indexes
- les releves suivants calculent un delta par occupant
- la facture combustible totale est transformee en composante ECS proportionnelle au delta
- l'historique conserve plusieurs calculs consecutifs
- la synthese finale par occupant se fait en combinant chauffage et ECS

### Test de calculs

- `GET /test-calculs` : page de simulation de scenarios de chauffe
- `POST /test-calculs` : calcule un scenario manuel sans modifier l'etat persistant
- `GET /test-consommation` : page de simulation de consommation chauffage plus ECS
- `POST /test-consommation` : calcule un scenario de consommation sans modifier l'etat persistant

Cette page sert a:

- charger un preset de scenario
- modifier les valeurs par zone
- verifier la repartition produite par le moteur

Le mode consommation ajoute:

- une saisie ECS par occupant
- une facture combustible totale et son libelle
- une synthese combinee chauffage plus ECS

Le pilotage chauffage publie, lui, de vraies consignes MQTT et modifie `data/admin_state.json`.

## OpenAPI native FastAPI

FastAPI publie automatiquement:

- `GET /docs`
- `GET /openapi.json`

Cette documentation native est utile pour l'exploration technique, mais la presente page reste la reference fonctionnelle pour l'exploitation ThermoCalc.