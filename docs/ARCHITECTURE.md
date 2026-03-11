# Architecture ThermoCalc

## Vue d'ensemble

ThermoCalc est une application FastAPI server-side rendue avec Jinja2.

Le systeme assemble cinq blocs:

1. collecte de mesures et metadonnees
2. persistence JSON locale
3. moteur de calcul chauffage et ECS
4. restitution HTML et PDF
5. orchestration en tache de fond

## Composants principaux

### Application web

- `app/main.py` initialise FastAPI, les fichiers statiques et la session.
- `app/api/routes.py` regroupe toutes les routes HTML, JSON et PDF.
- `app/templates/` contient les vues Jinja2.
- `app/static/css/site.css` porte le style global.

### Moteur metier

- `app/services/consumption.py` calcule la repartition chauffage.
- `app/services/reporting.py` produit les PDF mensuels.
- `app/services/admin_state.py` gere l'etat admin, les affectations et l'historique ECS.
- `app/services/thermostat_control.py` resout la consigne active par tete et pilote les TRV.
- `app/services/test_scenarios.py` genere des scenarios synthetiques pour le mode test.

### Integration Zigbee

- `app/services/zigbee.py` formate les vues metier Zigbee.
- `app/services/zigbee2mqtt.py` dialogue avec Zigbee2MQTT via MQTT.
- `app/services/runtime_measurements.py` stocke les dernieres mesures et derive le duty cycle.

Le meme canal Zigbee2MQTT sert a deux usages:

- remonter la telemetrie TRV26
- publier des consignes de temperature sur les tetes

### Taches de fond

- `app/services/scheduler.py` orchestre les PDF planifies et les rafraichissements de controleurs.

## Stockage local

Le projet utilise des fichiers JSON plutot qu'une base de donnees.

- `data/admin_state.json` : occupants, TRV, controleurs, ECS, planning
- `data/admin_state.json` stocke aussi les profils rapides, creneaux hebdomadaires, overrides et etats de commande.
- `data/runtime_measurements.json` : dernieres mesures recues et historique court
- `data/archive_index.json` : index des PDF archives
- `data/sample_data.json` : jeu de test local de secours

## Flux de calcul chauffage

1. La route charge un payload.
2. La priorite va au MQTT temps reel si les mesures sont recentes.
3. Sinon, le JSON de test local est applique.
4. Les affectations admin remappent les metadonnees des TRV si besoin.
5. `build_monthly_allocation` calcule les scores par zone puis les agrege par occupant.
6. Le rapport alimente la page HTML, l'API JSON ou le PDF.

## Formule de demande

Pour chaque tete:

- `delta = max(consigne - temperature_reelle, 0)`
- `facteur_vanne = vanne / 100`
- `facteur_etat = 1` pour `heat`, `0` pour `idle`, `0.5` sinon
- `facteur_duty = duty_cycle / 100` ou `facteur_vanne` si absent
- `facteur_demande = 0.55 * facteur_vanne + 0.25 * facteur_etat + 0.20 * facteur_duty`
- `effort = delta * surface * facteur_demande`

## Flux ECS

1. L'admin saisit de nouveaux indexes ECS par occupant.
2. Le systeme calcule le delta depuis le releve precedent.
3. Le montant total saisi est reparti proportionnellement.
4. Le dernier calcul et l'historique sont stockes dans `admin_state.json`.
5. Le PDF courant ou planifie peut reinjecter cette part ECS dans la synthese par occupant.

## Flux de pilotage chauffage

1. L'utilisateur cree des profils rapides comme Confort, Eco ou Nuit.
2. Un ou plusieurs creneaux hebdomadaires sont affectes a chaque tete TRV.
3. Un override temporaire ou un mode hors-gel occupant peut prendre la priorite.
4. `app/services/thermostat_control.py` resout la consigne active a partir de cet ordre de priorite.
5. Le scheduler republie les consignes utiles vers Zigbee2MQTT sur les tetes concernees.
6. L'etat de la derniere commande et un badge occupant permettent de distinguer planning, override temporaire et vacances hors-gel.

## Mode test

Le mode `test de calculs` contourne volontairement la telemetrie reelle.

- il ne lit pas MQTT
- il ne modifie pas `runtime_measurements.json`
- il n'ecrit ni archive ni PDF
- il n'altere pas les affectations admin

Il sert uniquement a valider le comportement du moteur de repartition dans des cas controles.